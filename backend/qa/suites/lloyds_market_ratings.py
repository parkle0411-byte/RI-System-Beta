"""Shared ratings remain authoritative across old masters and all MDM write paths."""
import copy,json,os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from masterdata.models import MasterRecord
from masterdata.serializers import MasterRecordSerializer
from masterdata.lloyds_market import SOURCE_NAME,is_lloyds_market,market_ratings
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA') == 'true', 'Run only in disposable QA'
checks=[]
def check(n,ok):
 checks.append((n,bool(ok)))
 if not ok:print('FAIL '+n)
def write(c,method,body):
 c.get('/api/auth/csrf')
 return getattr(c,method)('/api/master-data',data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
class Rollback(Exception):pass
try:
 with transaction.atomic():
  p=Personnel.objects.create(name='ZZ Lloyds Admin',department='admin',role_code='admin',created_by='t',updated_by='t')
  u=get_user_model().objects.create_user(username='zz.lloyds.admin',password='Lloyds-Test-Pass-1');p.auth_user_id=str(u.pk);p.account_status='active';p.save()
  c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');cache.clear();c.get('/api/auth/csrf');assert c.post('/api/auth/login',data=json.dumps(dict(username='zz.lloyds.admin',password='Lloyds-Test-Pass-1')),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value).status_code==200
  name="Lloyd's Underwriter Syndicate No. 9998 QA"
  expected=market_ratings();check('Four verified market financial strength ratings',[(r['agency'],r['grade']) for r in expected]==[('AM Best','A+'),('S&P Global','AA-'),('Fitch Ratings','AA-'),('KBRA','AA-')])
  check('Classification supports apostrophe/case/whitespace',is_lloyds_market('  lloyd’s  Underwriter Syndicate No. 1234 '))
  check('Other Lloyds-named companies are outside the market',not is_lloyds_market("Lloyd's Insurance Company"))
  raw=MasterRecord.objects.create(entity_type='reinsurer',name=name,payload={'ratings':[],'fixedClauses':[],'abbreviation':'LQA'},created_by='t',updated_by='t')
  before=copy.deepcopy(raw.payload);record=MasterRecordSerializer(raw).data
  check('Legacy master reads common ratings without a bulk rewrite',record['payload']['ratings']==expected and record['payload']['ratingsSource']==SOURCE_NAME and raw.payload==before)
  response=c.get('/api/master-data');body=response.json();profile=body['reinsurerMarkets']['lloyds'];check('GET publishes shared market profile',response.status_code==200 and profile['ratings']==expected and profile['checkedAt']=='2026-10-19')
  check('GET serializes all member ratings',next(r for r in body['records'] if r['id']==raw.pk)['payload']['ratings']==expected)
  base=dict(id=raw.pk,rowVersion=raw.row_version,entityType='reinsurer',code='',name=name)
  response=write(c,'put',{**base,'payload':dict(abbreviation='CHANGED',ratings=[dict(agency='Fake',grade='B')],fixedClauses=[])});raw.refresh_from_db()
  check('PUT prevents syndicate rating override',response.status_code==200 and raw.payload['ratings']==expected and response.json()['record']['payload']['ratingsSource']==SOURCE_NAME)
  check('Other fields still update normally',raw.payload['abbreviation']=='CHANGED' and raw.row_version==base['rowVersion']+1)
  response=write(c,'put',{**base,'rowVersion':raw.row_version,'isActive':False});raw.refresh_from_db()
  check('Deactivate with omitted payload keeps common ratings',response.status_code==200 and not raw.is_active and raw.payload['ratings']==expected)
  response=c.get('/api/master-data?entityType=reinsurer');check('Inactive members still read common ratings',next(r for r in response.json()['records'] if r['id']==raw.pk)['payload']['ratings']==expected)
  response=write(c,'put',{**base,'rowVersion':raw.row_version,'name':'ZZ Ordinary renamed QA'});raw.refresh_from_db()
  check('Renaming out removes inherited ratings and source',response.status_code==200 and raw.payload['ratings']==[] and 'ratingsSource' not in response.json()['record']['payload'])
  response=write(c,'put',{**base,'rowVersion':raw.row_version});raw.refresh_from_db()
  check('Renaming into the market automatically inherits ratings',response.status_code==200 and raw.payload['ratings']==expected)
  response=write(c,'post',dict(entityType='reinsurer',name="Lloyd's Underwriter Syndicate No. 9997 QA",payload=dict(ratings=None)));check('New syndicates ignore incompatible individual rating input',response.status_code==201 and response.json()['record']['payload']['ratings']==expected)
  response=write(c,'post',dict(entityType='reinsurer',name='ZZ Ordinary Manual QA',payload=dict(ratings=[dict(agency='Agency',grade='A')])));ordinary=response.json()['record'];check('Ordinary reinsurer ratings remain editable',response.status_code==201 and ordinary['payload']['ratings'][0]['agency']=='Agency' and 'ratingsSource' not in ordinary['payload'])
  response=write(c,'post',dict(entityType='reinsurer',name='ZZ Invalid Ordinary QA',payload=dict(ratings=None)));check('Ordinary ratings validation is preserved',response.status_code==400)
  response=write(c,'put',{**base,'rowVersion':1,'payload':{}});check('Version conflict protection is preserved',response.status_code==409)
  response=write(c,'post',dict(entityType='reinsurer',name="Lloyd's Underwriter Syndicate No. 9996 QA"));check('New syndicate without payload inherits shared ratings',response.status_code==201 and response.json()['record']['payload']['ratings']==expected)
  raise Rollback()
except Rollback:pass
passed=sum(ok for _,ok in checks);print(f'{passed}/{len(checks)} passed; database changes rolled back')
assert passed==len(checks)
