"""Complete insured membership, history, explicit renaming and policy snapshots."""
import copy,json,os
from django.utils import timezone
from io import StringIO
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.test import Client
from django.contrib.auth import get_user_model
from masterdata.models import MasterRecord
from cases.models import Case
from cases import insured_master as im
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok):
 checks.append((name,bool(ok)))
 if not ok:print('FAIL '+name,flush=True)
actor={'id':'qa-insured','name':'QA Insured'}
class Rollback(Exception):pass
try:
 with transaction.atomic():
  a=im.find_or_create('台積電',actor);ab=im.find_or_create('台積電/聯電',actor)
  check('single member differs from joint combination',a.pk!=ab.pk)
  try:im.rename(a,'台積電/聯電',actor,{'insuredMasterVersion':a.row_version});ok=False
  except Exception as exc:ok=getattr(exc,'code',None)=='insured_membership_change' or 'separate insured master' in str(exc)
  check('adding a member cannot masquerade as a legal rename',ok)
  for name in ['聯電/台積電',' 台積電 / 聯電 ','台積電/聯電/台積電']:
   check('order/spacing/repetition matches full membership '+name,im.find_or_create(name,actor).pk==ab.pk)
  check('different member remains separate',im.find_or_create('台積電/鴻海',actor).pk not in [a.pk,ab.pk])
  version=ab.row_version;history=copy.deepcopy(ab.payload['history']);im.rename(ab,'聯電/台積電',actor,{'insuredMasterVersion':version});ab.refresh_from_db()
  check('reordering is not a legal rename',ab.row_version==version and ab.payload['history']==history and ab.name=='台積電/聯電')
  for bad in ['','/','台積電/','/台積電','台積電//聯電']:
   try:im.find_or_create(bad,actor);ok=False
   except Exception as exc:ok=getattr(exc,'status_code',None)==400
   check('invalid empty member rejected '+repr(bad),ok)
  c1=Case.objects.create(status='draft',insured_master=ab,payload={'originalInsuredCn':'台積電/聯電',im.KEY:True},currency='TWD',created_by='qa',updated_by='qa')
  c2=Case.objects.create(status='draft',insured_master=ab,payload={'originalInsuredCn':'聯電/台積電',im.KEY:True},currency='TWD',created_by='qa',updated_by='qa')
  # Existing, previously-announced master fixture; its old policy names remain snapshots.
  ab.payload[im.OFFICIAL_KEY]=timezone.now().isoformat();ab.save()
  old=copy.deepcopy(c1.payload);changed={**old,'originalInsuredCn':'台積電'};linked=im.sync(c1,changed,actor)
  check('Draft membership change cannot link a master',linked is None and ab.name=='台積電/聯電')
  check('policy membership change does not rename the other combination',im.canonical(c2.insured_master).pk==ab.pk and c2.payload['originalInsuredCn']=='聯電/台積電')
  im.rename(ab,'台積電/聯華電子',actor,{'insuredMasterVersion':ab.row_version});ab.refresh_from_db()
  check('explicit legal rename records both names and actor',ab.payload['history'][-1]['action']=='renamed' and ab.payload['history'][-1]['before']=='台積電/聯電' and ab.payload['history'][-1]['after']=='台積電/聯華電子' and ab.payload['history'][-1]['byName']==actor['name'])
  c1.refresh_from_db();c2.refresh_from_db();check('legal rename preserves every policy snapshot',c1.payload==old and c2.payload['originalInsuredCn']=='聯電/台積電')
  check('reversed former name resolves to the renamed identity',im.find_or_create('聯電/台積電',actor).pk==ab.pk)
  before=copy.deepcopy(ab.payload);linked=im.sync(c2,{**c2.payload,'originalInsuredCn':'台積電/聯電'},actor);ab.refresh_from_db();check('Draft edits after a legal rename do not mutate the identity',linked is None and ab.payload==before)
  target=im.find_or_create('聯華電子/台灣積體電路',actor)
  try:im.rename(ab,'台灣積體電路/聯華電子',actor,{'insuredMasterVersion':ab.row_version});merge=None
  except im.MergeRequired as exc:merge=exc.data['insuredMerge']
  check('rename collision finds reversed target and requires confirmation',merge and merge['targetId']==target.pk)
  im.rename(ab,'台灣積體電路/聯華電子',actor,{'insuredMasterVersion':ab.row_version,'insuredMerge':merge});target.refresh_from_db();c2.refresh_from_db()
  check('confirmed merge keeps nested name history and cases',c2.insured_master_id==target.pk and target.payload['history'][-1]['sourceHistory']==before['history'])
  # Pre-existing duplicate rows are consolidated only with a reviewed signature.
  d1=im.find_or_create('甲公司/乙公司',actor)
  d2=MasterRecord.objects.create(entity_type='insured',name='乙公司/甲公司',payload={'aliases':[],'history':[{'action':'created','name':'乙公司/甲公司'}]},created_by='qa',updated_by='qa')
  dc=Case.objects.create(status='draft',insured_master=d2,payload={'originalInsuredCn':'乙公司/甲公司'},currency='TWD',created_by='qa',updated_by='qa');snap=copy.deepcopy(dc.payload)
  out=StringIO();call_command('consolidate_insured_combinations',stdout=out);plan=json.loads(out.getvalue());d2.refresh_from_db()
  check('consolidation preview performs no data rewrite',not plan['applied'] and d2.is_active and any(g['survivor']==d1.pk for g in plan['groups']))
  try:call_command('consolidate_insured_combinations',apply=True,expected_signature='wrong',stdout=StringIO());ok=False
  except CommandError:ok=True
  check('consolidation refuses an unreviewed/stale plan',ok)
  call_command('consolidate_insured_combinations',apply=True,expected_signature=plan['signature'],stdout=StringIO());dc.refresh_from_db();d2.refresh_from_db()
  check('consolidation retains originals and relinks policy without changing its name',dc.insured_master_id==d1.pk and dc.payload==snap and not d2.is_active and d2.payload['mergedInto']==d1.pk)
  # Public APIs enforce write permissions and list/search the full combination.
  def client(role):
   u=get_user_model().objects.create_user(username='insured.'+role,password='Insured-QA-Pass-9')
   Personnel.objects.create(name='Insured '+role,department='reinsurance',role_code=role,auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
   c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(u);c.get('/api/auth/csrf');return c
  sales=client('sales');finance=client('accounting');viewer=client('viewer')
  def post(c,body):return c.post('/api/insured-masters',json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
  res=post(sales,{'name':'測試甲/測試乙'});check('direct master creation requires Case workflow',res.status_code==403)
  search_master=im.find_or_create('測試甲/測試乙',actor)
  res=sales.get('/api/insured-masters',{'search':'測試乙/測試甲','scope':'pending'});check('pending search resolves reversed full combination',res.status_code==200 and any(r['id']==search_master.pk for r in res.json()['records']))
  Case.objects.filter(pk__in=[c1.pk,c2.pk]).update(status='posted',announced_at=timezone.now())
  res=sales.get('/api/insured-masters',{'id':target.pk});check('detail returns all linked policies with their original order',res.status_code==200 and {r['originalInsuredCn'] for r in res.json()['cases']}=={'台積電/聯電','聯電/台積電'})
  check('finance retains read-only access',finance.get('/api/insured-masters').status_code==200 and post(finance,{'name':'不允許'}).status_code==403)
  check('Case Viewer has no insured access',viewer.get('/api/insured-masters').status_code==403 and post(viewer,{'name':'不允許'}).status_code==403)
  res=post(sales,{'id':search_master.pk,'rowVersion':0,'name':'測試丙/測試乙'});check('direct rename is forbidden even with a supplied version',res.status_code==403)
  def case_request(method,body):return getattr(sales,method)('/api/cases',json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=sales.cookies['csrftoken'].value)
  api_cases=[]
  for name in ['實測甲/實測乙','實測乙/實測甲','實測甲']:
   r=case_request('post',{'incompleteDraft':True,'case':{'classOfBusiness':'Property','classCode':'PD','reinsuranceStructure':'QS','currency':'TWD','originalInsuredCn':name}})
   check('Case API creates policy '+name,r.status_code==201)
   api_cases.append(Case.objects.get(case_uid=r.json()['case']['caseUid']))
  check('Draft Case API creates no registry links for any combination',all(c.insured_master_id is None for c in api_cases))
  c=api_cases[0];joint_id=c.insured_master_id
  updated={**c.payload,'originalInsuredCn':'實測甲'};updated.pop('draftInput',None)
  r=case_request('put',{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'incompleteDraft':True,'case':updated});c.refresh_from_db();api_cases[1].refresh_from_db()
  check('Case edit API relinks member change without rewriting other policy',r.status_code==200 and c.insured_master_id==api_cases[2].insured_master_id and api_cases[1].insured_master_id==joint_id and api_cases[1].payload['originalInsuredCn']=='實測乙/實測甲')
  check('saving Draft combinations does not register them',not MasterRecord.objects.filter(entity_type='insured',name__startswith='實測').exists())

  raise Rollback()
except Rollback:pass
print(f'{sum(ok for _,ok in checks)}/{len(checks)} insured combination checks passed; database changes rolled back',flush=True);assert all(ok for _,ok in checks)
