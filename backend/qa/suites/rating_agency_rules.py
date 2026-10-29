"""Agency enum across ordinary and shared APIs; legacy data remains readable."""
import copy,json,os
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import EntitySnapshot
from masterdata.models import MasterRecord,MarketRatingProfile
from masterdata.views import validate_payload
from masterdata.lloyds_market import market_profile
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok):
 checks.append(bool(ok))
 if not ok:print('FAIL '+name,flush=True)
base=dict(agency='S&P Global',grade='A+',asOfDate='2026-10-22')
allowed=['S&P Global','A.M. Best',"Moody's",'Fitch']
invalid=['KBRA','AM Best','Fitch Ratings','Other Agency','S&P','fitch','',None,True,{},['Fitch'],'constructor']
for agency in allowed:
 value,error=validate_payload('reinsurer',dict(ratings=[{**base,'agency':agency}]))
 check('Accept '+agency,not error and value['ratings'][0]['agency']==agency)
for agency in invalid:
 check('Reject '+repr(agency),bool(validate_payload('reinsurer',dict(ratings=[{**base,'agency':agency}]))[1]))
class Rollback(Exception):pass
try:
 with transaction.atomic():
  cache.clear();u=get_user_model().objects.create_user(username='zz.rating.agency',password='Agency-Test-123')
  Personnel.objects.create(name='ZZ Rating Agency',department='admin',role_code='admin',auth_user_id=str(u.pk),account_status='active',created_by='t',updated_by='t')
  c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(u);c.get('/api/auth/csrf')
  def call(method,body,url='/api/master-data'):
   return getattr(c,method)(url,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
  for agency in allowed:
   response=call('post',dict(entityType='reinsurer',name='ZZ Agency '+agency,payload=dict(ratings=[{**base,'agency':agency}])));check('POST accepts '+agency,response.status_code==201 and response.json()['record']['payload']['ratings'][0]['agency']==agency)
  record=response.json()['record'];snapshot_count=EntitySnapshot.objects.count();record_count=MasterRecord.objects.count()
  for agency in invalid:
   response=call('post',dict(entityType='reinsurer',name='ZZ Invalid Agency',payload=dict(ratings=[{**base,'agency':agency}])));check('POST rejects '+repr(agency),response.status_code==400)
   response=call('put',dict(id=record['id'],rowVersion=record['rowVersion'],entityType='reinsurer',name=record['name'],payload=dict(ratings=[{**base,'agency':agency}])));check('PUT rejects '+repr(agency),response.status_code==400)
   response=call('put',dict(rowVersion=0,ratings=[{**base,'agency':agency}]),'/api/master-data/lloyds-ratings');check('Shared rejects '+repr(agency),response.status_code==400)
  check('Rejected writes preserve masters/version/history/profile',MasterRecord.objects.count()==record_count and MasterRecord.objects.get(pk=record['id']).row_version==record['rowVersion'] and EntitySnapshot.objects.count()==snapshot_count and MarketRatingProfile.objects.count()==0)
  rows=[{**base,'agency':agency} for agency in allowed]
  response=call('put',dict(rowVersion=0,ratings=rows),'/api/master-data/lloyds-ratings');check('Shared accepts exactly the four agencies',response.status_code==200 and [r['agency'] for r in response.json()['profile']['ratings']]==allowed)
  legacy=MasterRecord.objects.create(entity_type='reinsurer',name='ZZ Legacy KBRA',payload=dict(abbreviation='',fixedClauses=[],ratings=[{**base,'agency':'KBRA','ratingType':'Financial Strength','outlook':'','legalEntity':'','sourceUrl':'','status':'','checkedAt':''}]),created_by='t',updated_by='t')
  old=copy.deepcopy(legacy.payload)
  response=call('put',dict(id=legacy.pk,rowVersion=legacy.row_version,entityType='reinsurer',name=legacy.name,isActive=False,payload=old));legacy.refresh_from_db();check('Unchanged historical KBRA does not block lifecycle',response.status_code==200 and legacy.payload==old and not legacy.is_active)
  changed=copy.deepcopy(old);changed['ratings'][0]['grade']='AA-'
  response=call('put',dict(id=legacy.pk,rowVersion=legacy.row_version,entityType='reinsurer',name=legacy.name,payload=changed));check('Edited historical KBRA must select an allowed agency',response.status_code==400)
  changed['ratings'][0]['agency']="Moody's"
  response=call('put',dict(id=legacy.pk,rowVersion=legacy.row_version,entityType='reinsurer',name=legacy.name,payload=changed));check('Legacy can explicitly move to an allowed agency',response.status_code==200 and response.json()['record']['payload']['ratings'][0]['agency']=="Moody's")
  raise Rollback()
except Rollback:pass
print(f'{sum(checks)}/{len(checks)} passed; database changes rolled back',flush=True);assert all(checks)
