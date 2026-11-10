"""Owner-approved inception-month credit; disposable API/lifecycle regression."""
import copy,json,os,uuid
from pathlib import Path
from datetime import datetime,timezone as dtz
from types import SimpleNamespace
from unittest.mock import patch
from django.db import transaction
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory,force_authenticate
from cases.models import Case,CaseDocument
from cases.views import CasesView
from cases.workflow_views import AnnounceView
from personnel.models import Personnel
from fxrates.models import FxRate
from production.calc import base_month,installment_allocations,normalize_source,build_production_preview
from production.models import ProductionReport,ProductionExclusion
from production.views import ProductionReportView,case_source,load_month
from cases.accounting_policy import FACILITIES
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
ns={};exec(Path('/app/qa/suites/cgl_qs.py').read_text().split('class Rollback')[0],ns)
checks=[]
def check(label,ok,detail=''):
 assert ok,(label,detail)
 checks.append(label)
class Rollback(Exception):pass
try:
 with transaction.atomic():
  users={}
  for role,dept in [('sales','reinsurance'),('accounting_manager','finance')]:
   u=get_user_model().objects.create_user(username='qa.effective.'+role,password='Synthetic-Only-9!')
   p=Personnel.objects.create(name='QA Effective '+role,department=dept,role_code=role,auth_user_id=str(u.pk),account_status='active',is_split_eligible=True,created_by='qa',updated_by='qa')
   users[role]=(u,p)
  factory=APIRequestFactory()
  def api(view,method,body,role='sales'):
   req=getattr(factory,method)('/',body,format='json');force_authenticate(req,user=users[role][0]);return view.as_view()(req)
  stamp=datetime(2050,11,4,3,19,44,tzinfo=dtz.utc)
  def new_case(**changes):
   payload=ns['ready'](users['sales'][1]);payload.update(policyFrom='2050-10-01',policyTo='2051-10-01',originalInsuredCn='合成業績歸月',**changes)
   r=api(CasesView,'post',dict(case=payload,incompleteDraft=True));check('save complete CGL draft',r.status_code==201,r.data)
   c=Case.objects.get(case_uid=r.data['case']['caseUid'])
   for kind in ['offer','signed']:
    CaseDocument.objects.create(case=c,kind=kind,reinsurers=[r['name'] for r in c.payload['reinsurers']],filename='qa-'+kind+'.pdf',content_type='application/pdf',byte_size=1,sha256='a'*64,storage_key=uuid.uuid4().hex,is_selected=True,uploaded_by='qa')
   return c
  def announce(c,when=stamp):
   ids=[str(d.pk) for d in CaseDocument.objects.filter(case=c)]
   with patch('cases.workflow_views.timezone',SimpleNamespace(now=lambda:when)):
    r=api(AnnounceView,'post',dict(caseUid=str(c.case_uid),rowVersion=c.row_version,confirmed=True,documentIds=ids))
   c.refresh_from_db();check('Announce succeeds',r.status_code==200,r.data);return r
  def preview(month):
   r=api(ProductionReportView,'get',dict(month=month),'accounting_manager');check('read Production preview',r.status_code==200,r.data);return r.data
  def production(action,month,**extra):return api(ProductionReportView,'post',dict(action=action,month=month,**extra),'accounting_manager')
  FxRate.objects.create(year_month='2050-10',currency='USD',rate=31,created_by='qa',updated_by='qa')
  FxRate.objects.create(year_month='2050-11',currency='USD',rate=35,created_by='qa',updated_by='qa')
  c=new_case();announce(c);source=normalize_source(case_source(c))
  check('late original belongs to inception month',base_month(source)=='2050-10')
  for status in ['New','Renew']:
   for name in ['QA ordinary',*FACILITIES]:
    p={**source,'newOrRenew':status,'reinsurers':[{**source['reinsurers'][0],'name':name}]}
    check('all six categories original/renewal use effective month '+status+name,base_month(p)=='2050-10')
  check('earlier announcement does not pull future effective policy forward',base_month({**source,'policyFrom':'2051-01-01'})=='2051-01')
  check('actual Announce remains unchanged',c.announced_at==stamp and c.payload['announcedAt']==stamp.isoformat())
  check('Announce accounts retain actual creation date',all(t['createdAt']==stamp.isoformat() for t in c.payload['transactions']))
  check('no Production confirmation or cash was fabricated',not c.payload.get('confirmedProductionKeys') and not c.payload.get('paymentEntries'))
  oct=preview('2050-10');nov=preview('2050-11');own=lambda body:[r for r in body['rows'] if r['caseUid']==str(c.case_uid)]
  check('October preview includes late original exactly once',len(own(oct))==1)
  check('November preview excludes same original',not own(nov))
  check('recognition uses October official FX, not November FX',own(oct)[0]['rate']==31)
  check('preview has not generated or closed a report',not ProductionReport.objects.exists())
  from dashboard.calc import build_dashboard
  from zoneinfo import ZoneInfo
  dashboard=build_dashboard([case_source(c)],[],[dict(year_month='2050-11',currency='USD',rate=35)],datetime(2050,11,4,tzinfo=dtz.utc),tz=ZoneInfo('Asia/Taipei'),production_rules=True)
  check('Dashboard estimated brokerage uses October, not Announce month',dashboard['brokerage']['current'][9]>0 and dashboard['brokerage']['current'][10]==0)

  inst={**source,'installmentEnabled':True,'performanceInstallments':[dict(id='I1',premium=500,performanceMonth='2050-09',paymentBaseDate='2050-09-01'),dict(id='I2',premium=500,performanceMonth='2051-01',paymentBaseDate='2051-01-01')]}
  check('installment performance months remain explicit',[r['performanceMonth'] for r in installment_allocations(inst)]==['2050-09','2051-01'])
  endo={**source,'parentTwRef':c.tw_ref,'endoEffectiveDate':'2050-10-15'}
  check('endorsement keeps later effective/Announce month',base_month(endo)=='2050-11')
  check('endorsement override remains intact',base_month({**endo,'endorsementPerformanceMonth':'2050-09'})=='2050-09')
  r=production('generate','2050-10',sourceSignature=oct['sourceSignature']);check('generate October report',r.status_code==201,r.data);old=r.data['report']
  second=new_case(originalInsured='QA second original');announce(second)
  oct=preview('2050-10');check('late source still joins generated but unclosed month',any(r['caseUid']==str(second.case_uid) for r in oct['rows']))
  r=production('close','2050-10',reportUid=old['reportUid'],rowVersion=old['rowVersion'],sourceSignature=old['sourceSignature'])
  check('stale generated report cannot close over newly announced source',r.status_code==409 and r.data['error']=='source_changed',r.data)
  r=production('generate','2050-10',sourceSignature=oct['sourceSignature']);check('regenerate including late source',r.status_code==201,r.data);report=r.data['report']
  before_tx=copy.deepcopy(c.payload['transactions'])
  r=production('close','2050-10',reportUid=report['reportUid'],rowVersion=report['rowVersion'],sourceSignature=report['sourceSignature'])
  check('October report closes successfully',r.status_code==200,r.data);c.refresh_from_db()
  check('closing keeps Announce unchanged',c.announced_at==stamp and c.payload['announcedAt']==stamp.isoformat())
  check('closing fixes October recognition FX without new accounts',[(r['txNo'],r['amount']) for r in c.payload['transactions']]==[(r['txNo'],r['amount']) for r in before_tx] and all(r['postedMonth']=='2050-10' and r.get('postingFxRate')==31 for r in c.payload['transactions']))
  nov_closed=ProductionReport.objects.create(year_month='2050-11',version=1,status='closed',rows=[{'historical':'retain'}],source_signature='immutable',created_by='qa',closed_by='qa',closed_at=stamp,close_token=uuid.uuid4())
  saved=list(ProductionReport.objects.order_by('id').values())
  late=new_case(originalInsured='QA closed-month original');when=datetime(2051,1,4,tzinfo=dtz.utc);r=announce(late,when)
  check('closed October and November route to first open December',r.data['productionDeferrals'][0]['fromMonth']=='2050-10' and r.data['productionDeferrals'][0]['toMonth']=='2050-12')
  check('routing does not change actual January announcement',late.announced_at==when and late.payload['policyFrom']=='2050-10-01')
  check('closed report records remain exactly intact',list(ProductionReport.objects.order_by('id').values())==saved)
  dec=preview('2050-12');jan=preview('2051-01')
  check('deferred row appears exactly once in December',len([r for r in dec['rows'] if r['caseUid']==str(late.case_uid)])==1)
  check('deferred row does not duplicate into Announce month',not [r for r in jan['rows'] if r['caseUid']==str(late.case_uid)])
  check('confirmed original is not reintroduced into another month',not [r for r in dec['rows'] if r['caseUid']==str(c.case_uid)])
  raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} effective-month Production checks passed; synthetic database changes rolled back')
