"""Versioned common rating updates affect every member without rewriting masters."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection,transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from audit.models import EntitySnapshot,AuditLog
from cases.models import Case
from masterdata.models import MasterRecord,MarketRatingProfile
from masterdata.lloyds_market import SOURCE_NAME,default_market_ratings,market_profile
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
URL='/api/master-data/lloyds-ratings';checks=[]
def check(name,ok):
 checks.append((name,bool(ok)))
 if not ok:print('FAIL '+name,flush=True)
def client(role,tag):
 u=get_user_model().objects.create_user(username='zz.market.'+tag,password='Market-Editor-Pass-1')
 Personnel.objects.create(name='ZZ Market '+tag,department='reinsurance',role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='t',updated_by='t')
 c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(u);c.get('/api/auth/csrf');return c
def put(c,body,path=URL):
 return c.put(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
class Rollback(Exception):pass
try:
 with transaction.atomic():
  cache.clear();c=client('sales','sales');readonly=client('president','president');blocked=client('accounting','finance')
  records=[MasterRecord(entity_type='reinsurer',name="Lloyd's Underwriter Syndicate No. "+str(9000+i)+' QA',payload=dict(abbreviation='QA '+str(i),fixedClauses=[],ratings=[]),is_active=i!=124,created_by='t',updated_by='t') for i in range(125)]
  MasterRecord.objects.bulk_create(records)
  ordinary=MasterRecord.objects.create(entity_type='reinsurer',name='ZZ Ordinary QA',payload=dict(ratings=[dict(agency='Ordinary Agency',grade='ORDINARY')]),created_by='t',updated_by='t')
  before=list(MasterRecord.objects.order_by('pk').values());case_count=Case.objects.count()
  response=c.get(URL);profile=response.json()['profile'];check('Initial read returns version zero and previous ratings',response.status_code==200 and profile['rowVersion']==0 and profile['ratings']==default_market_ratings())
  check('Reads do not create a settings row',MarketRatingProfile.objects.count()==0)
  default=copy.deepcopy(profile['ratings']);draft=copy.deepcopy(default);draft[0].update(grade='TEST-A',outlook='Positive',legalEntity='Wrong entity',asOfDate='2026-10-01')
  snapshots=EntitySnapshot.objects.count();audits=AuditLog.objects.count()
  response=put(c,dict(rowVersion=0,ratings=draft));saved=response.json().get('profile',{})
  check('Staff can save common ratings with the first version',response.status_code==200 and saved.get('rowVersion')==1 and saved.get('ratings',[{}])[0].get('grade')=='TEST-A')
  check('Shared entity is fixed and review date is not fabricated',saved['ratings'][0]['legalEntity']==SOURCE_NAME and all(r['checkedAt']=='' for r in saved['ratings']))
  check('One market row is stored independently of member masters',MarketRatingProfile.objects.count()==1 and list(MasterRecord.objects.order_by('pk').values())==before)
  snap=EntitySnapshot.objects.filter(entity_type='market_rating_profile',entity_id='lloyds',entity_version=1).first()
  check('Snapshot and audit are written in the same transaction',EntitySnapshot.objects.count()==snapshots+1 and AuditLog.objects.count()==audits+1 and snap.snapshot_data['ratings']==saved['ratings'])
  response=c.get(URL);check('Reload uses persisted common ratings',response.json()['profile']==saved)
  with CaptureQueriesContext(connection) as queries:response=c.get('/api/master-data')
  body=response.json();members=[r for r in body['records'] if r['name'].startswith("Lloyd's Underwriter")]
  check('All 125 members including inactive read the saved profile',len(members)==125 and all(r['payload']['ratings']==saved['ratings'] and r['payload']['ratingsSource']==SOURCE_NAME for r in members))
  check('Ordinary ratings and MDM counts remain independent',next(r for r in body['records'] if r['id']==ordinary.pk)['payload']['ratings'][0]['grade']=='ORDINARY' and body['counts']['reinsurer']==125)
  check('One common-profile query serves the whole MDM response',sum('ri_market_rating_profiles' in q['sql'] for q in queries)==1)
  conflict=put(c,dict(rowVersion=0,ratings=default));check('Two first-save editors cannot overwrite each other',conflict.status_code==409 and market_profile()==saved)
  invalid=[{},dict(rowVersion=True,ratings=default),dict(rowVersion=1.0,ratings=default),dict(rowVersion=-1,ratings=default),dict(rowVersion='1',ratings=default),dict(rowVersion=1,ratings=[]),dict(rowVersion=1,ratings=None),dict(rowVersion=1,ratings='bad'),dict(rowVersion=1,ratings=[None]),dict(rowVersion=1,ratings=[dict(agency='A',grade=' ')]),dict(rowVersion=1,ratings=[dict(agency=' ',grade='A')]),dict(rowVersion=1,ratings=[default[0]]*51),None,[1]]
  snapshots=EntitySnapshot.objects.count();audits=AuditLog.objects.count()
  for i,data in enumerate(invalid):check('Invalid shared update '+str(i)+' is rejected',put(c,data).status_code==400)
  check('Invalid writes preserve profile and version history',market_profile()==saved and EntitySnapshot.objects.count()==snapshots and AuditLog.objects.count()==audits)
  draft=copy.deepcopy(saved['ratings'][:2]);draft[1]['agency']='QA New Agency';draft[1]['grade']='TEST-B'
  response=put(c,dict(rowVersion=1,ratings=draft));updated=response.json()['profile'];check('Add/remove/change agencies updates one shared version',response.status_code==200 and updated['rowVersion']==2 and len(updated['ratings'])==2 and updated['ratings'][1]['agency']=='QA New Agency')
  response=put(c,dict(rowVersion=1,ratings=default));check('Stale edits return a version conflict without changes',response.status_code==409 and response.json()['currentRowVersion']==2 and market_profile()==updated)
  response=readonly.get(URL);check('MDM read-only role can read the saved profile',response.status_code==200 and response.json()['profile']==updated)
  check('MDM read-only role cannot change shared ratings',put(readonly,dict(rowVersion=2,ratings=default)).status_code==403 and market_profile()==updated)
  check('Role without MDM access cannot read or write profile',blocked.get(URL).status_code==403 and put(blocked,dict(rowVersion=2,ratings=default)).status_code==403)
  anonymous=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');check('Anonymous requests cannot read rating settings',anonymous.get(URL).status_code in (401,403))
  check('CSRF protection is enforced',c.put(URL,data=json.dumps(dict(rowVersion=2,ratings=default)),content_type='application/json').status_code==403)
  check('Common update never changes existing masters or cases',list(MasterRecord.objects.order_by('pk').values())==before and Case.objects.count()==case_count)
  member=members[0]
  response=put(c,dict(id=member['id'],rowVersion=member['rowVersion'],entityType='reinsurer',name=member['name'],payload=dict(ratings=default,fixedClauses=[])),path='/api/master-data')
  check('Individual member editing cannot override the shared ratings',response.status_code==200 and response.json()['record']['payload']['ratings']==updated['ratings'] and market_profile()==updated)
  check('New common snapshots retain each saved version',EntitySnapshot.objects.get(entity_type='market_rating_profile',entity_id='lloyds',entity_version=1).snapshot_data['ratings']==saved['ratings'] and EntitySnapshot.objects.get(entity_type='market_rating_profile',entity_id='lloyds',entity_version=2).snapshot_data['ratings']==updated['ratings'])
  raise Rollback()
except Rollback:pass
passed=sum(ok for _,ok in checks);print(f'{passed}/{len(checks)} passed; database changes rolled back',flush=True);assert passed==len(checks)
