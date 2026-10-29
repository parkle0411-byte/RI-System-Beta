"""Required rating dates, fixed type, optional checked date and legacy preservation."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import EntitySnapshot
from masterdata.models import MasterRecord,MarketRatingProfile
from masterdata.views import validate_payload
from masterdata.lloyds_market import SOURCE_NAME,market_profile
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(n,ok):
 checks.append((n,bool(ok)))
 if not ok:print('FAIL '+n,flush=True)
def validate(row):return validate_payload('reinsurer',dict(ratings=[row]))
base=dict(agency='S&P Global',grade='A+',asOfDate='2026-10-01')
for value in [None,'','2026-02-30','2025-02-29','2026-13-01','2026-1-01','2026-10-01T00:00:00Z','not a date',True,'0000-01-01']:
 row={**base,'asOfDate':value};payload,err=validate(row);check('Reject invalid/missing As-of '+repr(value),bool(err))
for value in ['2024-02-29','2000-02-29','2026-10-22']:
 payload,err=validate({**base,'asOfDate':value});check('Accept real date '+value,not err and payload['ratings'][0]['asOfDate']==value)
for value in ['',None,'2026-10-22']:
 payload,err=validate({**base,'checkedAt':value});check('Checked at optional or valid '+repr(value),not err and payload['ratings'][0]['checkedAt']==(value or ''))
for value in ['2026-02-30','2026-10','bad',True]:
 payload,err=validate({**base,'checkedAt':value});check('Reject invalid Checked at '+repr(value),bool(err))
payload,err=validate({**base,'ratingType':'Issuer Credit'});check('API fixes type to Financial Strength',not err and payload['ratings'][0]['ratingType']=='Financial Strength')
class Rollback(Exception):pass
try:
 with transaction.atomic():
  cache.clear();u=get_user_model().objects.create_user(username='zz.rating.fields',password='Rating-Fields-Pass-1')
  Personnel.objects.create(name='ZZ Rating Fields',department='admin',role_code='admin',auth_user_id=str(u.pk),account_status='active',created_by='t',updated_by='t')
  c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(u);c.get('/api/auth/csrf')
  def call(method,body,url='/api/master-data'):
   return getattr(c,method)(url,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
  before=MasterRecord.objects.count();snapshots=EntitySnapshot.objects.count()
  response=call('post',dict(entityType='reinsurer',name='ZZ Missing As-of',payload=dict(ratings=[dict(agency='S&P Global',grade='A')])));check('Ordinary POST rejects missing date without writes',response.status_code==400 and MasterRecord.objects.count()==before and EntitySnapshot.objects.count()==snapshots)
  response=call('post',dict(entityType='reinsurer',name='ZZ Valid Rating',payload=dict(ratings=[{**base,'ratingType':'Wrong','checkedAt':'2026-10-22'}])));row=response.json()['record'];check('Ordinary save accepts and retains optional Checked at',response.status_code==201 and row['payload']['ratings'][0]['checkedAt']=='2026-10-22' and row['payload']['ratings'][0]['ratingType']=='Financial Strength')
  response=call('put',dict(id=row['id'],rowVersion=row['rowVersion'],entityType='reinsurer',name=row['name'],payload=dict(ratings=[{**base,'checkedAt':'bad'}])));check('Ordinary PUT rejects invalid Checked at and preserves version',response.status_code==400 and MasterRecord.objects.get(pk=row['id']).row_version==row['rowVersion'])
  legacy=MasterRecord.objects.create(entity_type='reinsurer',name='ZZ Legacy',payload=dict(abbreviation='OLD',fixedClauses=[],ratings=[dict(agency='Old Agency',grade='A',ratingType='Financial Strength',asOfDate='',checkedAt='',outlook='Stable',legalEntity='Old Entity',sourceUrl='https://example.invalid/source',status='Historic')]),created_by='t',updated_by='t')
  old_payload=copy.deepcopy(legacy.payload)
  response=call('put',dict(id=legacy.pk,rowVersion=legacy.row_version,entityType='reinsurer',name=legacy.name,isActive=False,payload=old_payload));legacy.refresh_from_db();check('Legacy missing date does not block lifecycle updates',response.status_code==200 and not legacy.is_active and legacy.payload==old_payload)
  changed=copy.deepcopy(old_payload);changed['ratings'][0]['grade']='A+'
  response=call('put',dict(id=legacy.pk,rowVersion=legacy.row_version,entityType='reinsurer',name=legacy.name,payload=changed));check('Changing legacy rating requires its As-of date',response.status_code==400)
  changed['ratings'][0]['asOfDate']='2026-10-01';changed['ratings'][0]['agency']='A.M. Best'
  response=call('put',dict(id=legacy.pk,rowVersion=legacy.row_version,entityType='reinsurer',name=legacy.name,payload=changed));legacy.refresh_from_db();check('Legacy date can be filled without losing hidden historical metadata',response.status_code==200 and all(legacy.payload['ratings'][0][key]==old_payload['ratings'][0][key] for key in ['outlook','status','legalEntity','sourceUrl']))
  response=call('post',dict(entityType='reinsurer',name='ZZ No Ratings',payload=dict(ratings=[])));check('Ordinary master still permits zero ratings',response.status_code==201)
  profile_before=market_profile();snapshots=EntitySnapshot.objects.count()
  response=call('put',dict(rowVersion=0,ratings=[dict(agency='S&P Global',grade='A')]),'/api/master-data/lloyds-ratings');check('Shared save requires As-of date without settings/history writes',response.status_code==400 and MarketRatingProfile.objects.count()==0 and EntitySnapshot.objects.count()==snapshots)
  response=call('put',dict(rowVersion=0,ratings=[{**base,'ratingType':'Issuer','checkedAt':'2026-10-22','legalEntity':'Wrong Entity'}]),'/api/master-data/lloyds-ratings');profile=response.json()['profile'];check('Shared saves retain explicit Checked at and fix type/entity',response.status_code==200 and profile['ratings'][0]['checkedAt']=='2026-10-22' and profile['ratings'][0]['asOfDate']=='2026-10-01' and profile['ratings'][0]['ratingType']=='Financial Strength' and profile['ratings'][0]['legalEntity']==SOURCE_NAME)
  response=call('put',dict(rowVersion=profile['rowVersion'],ratings=[base]),'/api/master-data/lloyds-ratings');check('Shared Checked at may be omitted',response.status_code==200 and response.json()['profile']['ratings'][0]['checkedAt']=='')
  response=call('put',dict(rowVersion=response.json()['profile']['rowVersion'],ratings=[{**base,'checkedAt':'invalid'}]),'/api/master-data/lloyds-ratings');check('Shared invalid Checked at is rejected',response.status_code==400)
  ordinary_before=list(MasterRecord.objects.order_by('pk').values());response=c.get('/api/master-data');check('Reading masters never rewrites legacy dates or metadata',response.status_code==200 and list(MasterRecord.objects.order_by('pk').values())==ordinary_before)
  raise Rollback()
except Rollback:pass
passed=sum(ok for _,ok in checks);print(f'{passed}/{len(checks)} passed; database changes rolled back',flush=True);assert passed==len(checks)
