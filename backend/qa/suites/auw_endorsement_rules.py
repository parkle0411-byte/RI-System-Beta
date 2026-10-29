"""Real API, calendar arithmetic, accounting and atomic legacy deferral coverage."""
import copy,json,os,uuid
from datetime import date,datetime,timedelta,timezone as tz
from unittest.mock import patch
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import Client
from audit.models import EntitySnapshot
from cases.calc.payment_terms import build_payment_schedule,endorsement_base_date,reminder_kind
from cases.draft import normalize_draft
from cases.endorsement_terms import consolidate_existing_endorsement
from cases.manual_reference import MANUAL_TW_REF_REINSURER as TARGET
from cases.models import Case,CaseDocument
from personnel.models import Personnel
from production.models import ProductionReport,ProductionExclusion
from production.views import case_source,exclusion_row
from production.calc import build_production_preview
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,value):
 assert value,name
 checks.append(name);print('PASS '+name,flush=True)
def plus(value,days):return (date.fromisoformat(value)+timedelta(days=days)).isoformat()
raw=dict(parentTwRef='TWPF2601001',policyFrom='2026-01-01',endoEffectiveDate='2026-03-15',originalPremium=1000,
 paymentTermsDays=120,riCommPct=10,taxPct=1,cedantTermsBasis='case',currency='TWD',
 reinsurers=[dict(name=TARGET,sharePct=100,premium=800,riCommPct=12.5,taxPct=0,foreignBroker='Howden Specialty Limited')])
for stamp,effective,expected,month_end in [
 ('2026-03-01T00:00:00+00:00','2026-03-15','2026-03-15','2026-03-31'),
 ('2026-04-02T01:00:00+00:00','2026-03-15','2026-04-02','2026-04-30'),
 ('2026-03-15T00:00:00Z','2026-03-15','2026-03-15','2026-03-31'),
 ('2026-01-31T17:00:00Z','2026-01-15','2026-02-01','2026-02-28'),
 ('2028-02-28T16:00:00Z','2028-02-01','2028-02-29','2028-02-29'),
 ('2026-12-31T16:00:00Z','2026-12-15','2027-01-01','2027-01-31')]:
 for premium in [1000,-1000,0]:
  p=copy.deepcopy(raw);p.update(endoEffectiveDate=effective,endorsementAnnouncedAt=stamp,originalPremium=premium)
  p['reinsurers'][0]['premium']=premium*.8
  items=build_payment_schedule(p)['items'];c,r=items
  assert endorsement_base_date(p)==expected and c['baseDate']==expected
  assert c['termsDays']==90 and c['contractDueDate']==plus(expected,90) and c['dueDate']==plus(expected,75)
  assert r['sourceBaseDate']==expected and r['baseDate']==month_end and r['contractDueDate']==plus(month_end,120) and r['dueDate']==plus(month_end,110)
 check('later-date calendar arithmetic, signed/zero premiums and Taiwan date '+stamp,True)
for missing in ['',None,'2026-01-01','invalid','2026-01-01T00:00:00']:
 p={**raw,'endorsementAnnouncedAt':missing,'createdAt':'2099-01-01','postedAt':'2099-01-01'}
 schedule=build_payment_schedule(p)
 check('missing/invalid actual Announce never uses created/posted/today '+repr(missing),all(i['dueDate']=='' for i in schedule['items']) and schedule['reviewRequired'])
p={**raw,'endorsementAnnouncedAt':'2026-03-01T00:00:00Z','endoEffectiveDate':'2026-02-30'}
check('invalid real endorsement date is pending review',all(i['dueDate']=='' for i in build_payment_schedule(p)['items']))
p=copy.deepcopy(raw);p['reinsurers'][0]['sharePct']=90;p['reinsurers'].append(dict(name='Ordinary RI',sharePct=10,premium=800,riCommPct=5,taxPct=1,paymentTermsDays=45));p['endorsementAnnouncedAt']='2026-04-02T00:00:00Z'
items=build_payment_schedule(p)['items']
check('mixed case ordinary RI payable starts at later Announce/effective date and retains its term',items[2]['baseDate']=='2026-04-02' and items[2]['dueDate']==plus('2026-04-02',35) and items[1]['baseDate']=='2026-04-30')
p=copy.deepcopy(raw);p.update(originalPremium=-1000,endoEffectiveDate='2026-03-15',endorsementAnnouncedAt='2026-04-02T00:00:00Z');p['reinsurers']=[dict(name='Ordinary RI',sharePct=100,premium=-800,riCommPct=5,taxPct=1,paymentTermsDays=45)]
items=build_payment_schedule(p)['items']
check('ordinary RI recovery uses the later endorsement Announce date',items[1]['baseDate']=='2026-04-02' and items[1]['dueDate']==plus('2026-04-02',35) and items[0]['baseDate']=='2026-04-02')
p=copy.deepcopy(raw);p.update(originalPremium=500,endoEffectiveDate='2026-03-15',endorsementAnnouncedAt='2026-04-02T00:00:00Z');p['reinsurers']=[dict(name='Payable RI',sharePct=50,premium=800,riCommPct=5,taxPct=1,paymentTermsDays=45),dict(name='Recovery RI',sharePct=50,premium=-200,riCommPct=5,taxPct=1,paymentTermsDays=45)]
items=build_payment_schedule(p)['items']
check('mixed RI payable and recovery each follow their cash direction',items[1]['baseDate']=='2026-04-02' and items[2]['baseDate']=='2026-04-02')
p['endorsementAnnouncedAt']=''
draft_schedule=build_payment_schedule(p)
check('ordinary RI payable has no premature due date before actual Announce',draft_schedule['items'][1]['baseDate']=='' and draft_schedule['items'][1]['dueDate']=='' and draft_schedule['reviewRequired'])
user=get_user_model().objects.create_user(username='zz.auw.endo',password='AUW-Endo-Password-9!')
person=Personnel.objects.create(name='QA AUW Endorsement AE',department='admin',role_code='admin',auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
def call(method,url,body=None):
 client.get('/api/auth/csrf');kw={'HTTP_X_CSRFTOKEN':client.cookies['csrftoken'].value}
 if body is not None:kw.update(data=json.dumps(body),content_type='application/json')
 return getattr(client,method)(url,**kw)
assert call('post','/api/auth/login',dict(username=user.username,password='AUW-Endo-Password-9!')).status_code==200
ready=dict(reinsuranceStructure='QS',ae=person.name,currency='TWD',classOfBusiness='Property',classCode='AER',reinsuredRetention='Synthetic retention',newOrRenew='New',typePrefix='Fire',reinsured='QA Endorsement Cedant',originalInsured='QA Endorsement Root', originalInsuredCn='合成測試被保險人',policyFrom='2050-01-01',policyTo='2051-01-01',interest='Buildings',situations=[dict(address='QA Road',postcode='100')],reinsurers=[dict(name=TARGET,sharePct=100,premium=8000,riCommPct=12.5,taxPct=0)],limitOfLiability=1000000,deductibles='As original',basisOfValuation='Replacement Value',originalConditions='As original',occupation='Office',construction='Concrete', constructionSelections=['A2 Class'],sumInsured=[dict(category='Building',amount=1000000)],lossAdvisedDate='2049-12-01',lossRecordYears=5,originalPremium=10000,paymentTermsDays=120,riCommPct=17,taxPct=1,manualTwRef='TW50SM-ROOT',installmentEnabled=True,performanceInstallments=[dict(id='root1',performanceMonth='2050-01',paymentBaseDate='2050-01-01',premium=4000),dict(id='root2',performanceMonth='2050-02',paymentBaseDate='2050-02-01',premium=6000)])
r=call('post','/api/cases',{'case':ready});assert r.status_code==201,r.content
root=Case.objects.get(case_uid=r.json()['case']['caseUid']);root.status='posted';root.tw_ref='TWAER5001001';root.save()
root_before=Case.objects.filter(pk=root.pk).values().get()
def create_child(source,manual='TW50SM-END'):
 r=call('post','/api/case-workflow',dict(action='create_endorsement',caseUid=str(source.case_uid),rowVersion=source.row_version,manualTwRef=manual))
 assert r.status_code==201,r.content
 return Case.objects.get(case_uid=r.json()['case']['caseUid'])
child=create_child(root)
# 2026-10-21 使用者決定（取代 92 項規則第 35 條）：新批單的 Cedant 與再保人付款天數一律沿用來源保單，Draft 仍可修改。
check('AUW endorsement starts single settlement, keeps fixed Cedant 90 days and editable deductions',child.payload['installmentEnabled'] is False and child.payload['performanceInstallments']==[] and child.payload['paymentTermsDays']==90 and child.payload['reinsurers'][0]['riCommPct']==12.5)
check('fixed Cedant 90 days remains effective when an old raw value is blank',build_payment_schedule({**child.payload,'paymentTermsDays':None,'endoEffectiveDate':'2050-01-15','endorsementAnnouncedAt':'2050-02-01T00:00:00Z','originalPremium':1000})['items'][0]['termsDays']==90)
check('new endorsement clears old actual Announce date and defers automatic AUW reference until Announce',child.payload['endorsementAnnouncedAt']=='' and not child.payload.get('manualTwRef'))
def save(row,payload,reason='QA current financial correction'):return call('put','/api/cases',dict(caseUid=str(row.case_uid),rowVersion=row.row_version,case=payload,reason=reason))
for flag,rows in [(True,[]),(False,[dict(id='bad',premium=1)]),(True,ready['performanceInstallments'])]:
 p=copy.deepcopy(child.payload);p.update(parentTwRef='',installmentEnabled=flag,performanceInstallments=rows)
 before=child.row_version
 r=save(child,p);child.refresh_from_db()
 check('API cannot add endorsement installments even with spoofed identity '+str(flag)+str(len(rows)),r.status_code==400 and child.row_version==before)
# 2026-10-16／10-20：批單 Cedant 天數由該批單自行填寫（取代 10/07「繼承原保單、批單不可改」），Draft 可填入並保存。
p=copy.deepcopy(child.payload);p['paymentTermsDays']=90
r=save(child,p);child.refresh_from_db()
check('endorsement Draft accepts its own Cedant days',r.status_code==200 and child.payload['paymentTermsDays']==90)
p=copy.deepcopy(child.payload);p['paymentTermsDays']=120   # 本批單自行填 120，以下會計日期沿用原斷言
p.update(originalPremium=1000,endoEffectiveDate='2050-01-15',endoTypes=['Premium'],endoText='Additional premium',endorsementAnnouncedAt='2099-12-01T00:00:00Z',endorsementPerformanceMonth='2099-12');p['reinsurers'][0]['premium']=800
r=save(child,p);assert r.status_code==200,r.content;child.refresh_from_db()
check('Draft cannot supply Announce date or special historical performance month',child.payload['endorsementAnnouncedAt']=='' and not child.payload.get('endorsementPerformanceMonth'))
stamp=datetime(2050,1,31,17,tzinfo=tz.utc)
with patch('cases.workflow_views.timezone',SimpleNamespace(now=lambda:stamp)):
 r=call('post','/api/case-announce',dict(caseUid=str(child.case_uid),rowVersion=child.row_version,confirmed=True,documentIds=[]))
check('missing documents still block Announce: '+r.content.decode(),r.status_code==400 and r.json()['error']=='documents_not_ready')
child.refresh_from_db();check('failed Announce does not persist a candidate payment date',child.payload['endorsementAnnouncedAt']=='' and child.announced_at is None)
docs=[CaseDocument.objects.create(case=child,kind=k,reinsurers=[TARGET] if k!='offer' else [],filename=k+'.pdf',content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='qa-'+str(uuid.uuid4()),is_selected=True,uploaded_by='qa') for k in ['offer','signed']]
with patch('cases.workflow_views.timezone',SimpleNamespace(now=lambda:stamp)):
 r=call('post','/api/case-announce',dict(caseUid=str(child.case_uid),rowVersion=child.row_version,confirmed=True,documentIds=[str(d.pk) for d in docs]))
assert r.status_code==200,r.content;child.refresh_from_db()
check('successful Announce stores the exact authoritative time once',child.announced_at==stamp and child.payload['endorsementAnnouncedAt']==stamp.isoformat())
rows=[row for row in call('get','/api/accounting').json()['rows'] if row['caseUid']==str(child.case_uid)]
c=next(row for row in rows if row['partyType']=='cedant');r=next(row for row in rows if row['partyType']=='reinsurer')
check('Accounting uses Feb 1 for Cedant and Feb month end for AUW',c['baseDate']=='2050-02-01' and c['termsDays']==90 and c['dueDate']==plus('2050-02-01',75) and r['baseDate']=='2050-02-28' and r['dueDate']==plus('2050-02-28',110))
check('AUW reminder uses internal date, not contract date',reminder_kind(r,r['dueDate'])=='due_today' and reminder_kind(r,r['contractDueDate'])!='due_today')
p=copy.deepcopy(child.payload);p.update(endorsementAnnouncedAt='2099-01-01T00:00:00Z',endorsementPerformanceMonth='2099-01');p['reinsurers'][0]['riCommPct']=7
r=save(child,p);assert r.status_code==200,r.content;child.refresh_from_db()
check('posted edit preserves server Announce date and locked source deduction',child.payload['endorsementAnnouncedAt']==stamp.isoformat() and child.payload['reinsurers'][0]['riCommPct']==root.payload['reinsurers'][0]['riCommPct'] and not child.payload.get('endorsementPerformanceMonth'))
p=copy.deepcopy(child.payload);p['endoEffectiveDate']='2050-04-01'
r=save(child,p,reason='')
check('unprocessed payment base cannot change without a reason',r.status_code==409 and r.json()['error']=='property_edit_locked')
# 2026-10-16：已有效的天數不可修改；批單自己的 Cedant 天數在 Announce 後同樣鎖定（保留原「批單 Cedant 天數不可任意改」的意旨）
p=copy.deepcopy(child.payload);p['paymentTermsDays']=90
r=save(child,p)
child.refresh_from_db();check('fixed Cedant 90 canonicalizes on posted save',r.status_code==200 and child.payload['paymentTermsDays']==90)
# 2026-10-21 使用者決定（取代 92 項規則第 35 條）：新批單的 Cedant 與再保人付款天數一律沿用來源保單，Draft 仍可修改。
child.payload['paymentTermsDays']=90;child.save(update_fields=['payload'])
chained=create_child(child,'TW50SM-END2')
check('chained endorsement inherits the days of the case it is created from (intermediate 90)',chained.payload['paymentTermsDays']==90)
normal=copy.deepcopy(ready);normal['reinsurers'][0]['name']='QA Ordinary Endorsement RI';normal['reinsurers'][0]['paymentTermsDays']=120;normal.pop('manualTwRef')
r=call('post','/api/cases',{'case':normal});assert r.status_code==201,r.content
ordinary=Case.objects.get(case_uid=r.json()['case']['caseUid']);ordinary.status='posted';ordinary.tw_ref='TWAER5001002';ordinary.save()
normal_child=create_child(ordinary)
# 2026-10-21 使用者決定（取代 92 項規則第 35 條）：新批單的 Cedant 與再保人付款天數一律沿用來源保單，Draft 仍可修改。
check('non-AUW endorsement also has no installments and inherits the Cedant and reinsurer days',normal_child.payload['installmentEnabled'] is False and normal_child.payload['performanceInstallments']==[] and normal_child.payload['paymentTermsDays']==ordinary.payload['paymentTermsDays'] and normal_child.payload['reinsurers'][0].get('paymentTermsDays')==ordinary.payload['reinsurers'][0].get('paymentTermsDays'))
normal_p=copy.deepcopy(normal_child.payload);normal_p['paymentTermsDays']=120;normal_p.update(originalPremium=1000,endoEffectiveDate='2050-01-15',endoTypes=['Premium'],endoText='Additional premium');normal_p['reinsurers'][0].update(premium=800,paymentTermsDays=120)
# 2026-10-16 92 項規則：普通再保人天數亦須明確填寫（沒有預設值，缺漏即待確認），故批單自行填入 Cedant 及再保人各 120 天
r=save(normal_child,normal_p);assert r.status_code==200,r.content;normal_child.refresh_from_db()
normal_docs=[CaseDocument.objects.create(case=normal_child,kind=k,reinsurers=['QA Ordinary Endorsement RI'] if k!='offer' else [],filename=k+'.pdf',content_type='application/pdf',byte_size=5,sha256='0'*64,storage_key='qa-'+str(uuid.uuid4()),is_selected=True,uploaded_by='qa') for k in ['offer','signed']]
with patch('cases.workflow_views.timezone',SimpleNamespace(now=lambda:stamp)):
 r=call('post','/api/case-announce',dict(caseUid=str(normal_child.case_uid),rowVersion=normal_child.row_version,confirmed=True,documentIds=[str(d.pk) for d in normal_docs]))
assert r.status_code==200,r.content;normal_child.refresh_from_db()
normal_rows=[row for row in call('get','/api/accounting').json()['rows'] if row['caseUid']==str(normal_child.case_uid)]
normal_ri=next(row for row in normal_rows if row['partyType']=='reinsurer')
check('Announce API and Accounting use actual later date for ordinary RI payable',normal_ri['baseDate']=='2050-02-01' and normal_ri['dueDate']==plus('2050-02-01',110))
# User-authorized legacy shape: an unbooked, already Announced endorsement, with 2
# performance installments, original September attribution and September closed.
legacy_p=copy.deepcopy(child.payload);legacy_p.update(installmentEnabled=True,performanceInstallments=[dict(id='old1',performanceMonth='2052-09',premium=400,paymentBaseDate='2052-09-30'),dict(id='old2',performanceMonth='2052-12',premium=600,paymentBaseDate='2052-12-30')],manualTwRef='',paymentEntries=[],transactions=[],confirmedProductionKeys=[],endorsementAnnouncedAt='',endoEffectiveDate='2052-10-30')
legacy_p['reinsurers'][0]['taxPct']=1
legacy=Case.objects.create(case_kind='endorsement',parent_case=root,tw_ref='TWAER5001001-E90',status='posted',payload=legacy_p,announced_at=datetime(2052,9,29,tzinfo=tz.utc),created_by='qa',updated_by='qa')
report=ProductionReport.objects.create(year_month='2052-09',version=1,status='closed',rows=[dict(unchanged=True)],excluded_rows=[],source_signature='closed-original',created_by='qa',closed_by='qa',closed_at=datetime(2052,10,1,tzinfo=tz.utc),close_token=uuid.uuid4())
closed_before=ProductionReport.objects.filter(pk=report.pk).values().get();legacy_before=copy.deepcopy(legacy.payload)
result=consolidate_existing_endorsement(str(legacy.case_uid),'2052-09',expected_version=legacy.row_version);legacy.refresh_from_db()
check('legacy repair converts to one full settlement, retains September origin',result['changedCaseCount']==1 and not legacy.payload['installmentEnabled'] and legacy.payload['performanceInstallments']==[] and legacy.payload['endorsementPerformanceMonth']=='2052-09')
# 2026-10-16／10-20：批單 Cedant 天數屬於該批單本身（沒有預設繼承），修復時保留批單自己的 90 天，不改回原保單 120 天
check('legacy repair reads actual old Announce and keeps the endorsement own Cedant days',legacy.payload['endorsementAnnouncedAt']==legacy.announced_at.isoformat() and legacy_before['paymentTermsDays']==90 and legacy.payload['paymentTermsDays']==90)
check('legacy repair preserves missing AUW Ref, tax, customized deductions, premiums and all other fields',all(legacy.payload[k]==v for k,v in legacy_before.items() if k not in ['installmentEnabled','performanceInstallments','paymentTermsDays','cedantTermsBasis','endorsementAnnouncedAt','endorsementPerformanceMonth']))
check('closed September receives an October deferral',len(result['productionDeferrals'])==1 and result['productionDeferrals'][0]['fromMonth']=='2052-09' and result['productionDeferrals'][0]['toMonth']=='2052-10')
check('closed report is byte-for-byte untouched',closed_before==ProductionReport.objects.filter(pk=report.pk).values().get())
exclusions=[exclusion_row(e) for e in ProductionExclusion.objects.filter(case=legacy)]
preview=build_production_preview([case_source(legacy)],'2052-10',{},exclusions)
check('October production receives full consolidated endorsement income',len(preview['rows'])==1 and preview['rows'][0]['caseUid']==str(legacy.case_uid))
version=legacy.row_version;snapshots=EntitySnapshot.objects.count();count=ProductionExclusion.objects.count()
result=consolidate_existing_endorsement(str(legacy.case_uid),'2052-09',expected_version=1);legacy.refresh_from_db()
check('repeat repair is idempotent without snapshots or exclusions',result['changedCaseCount']==0 and legacy.row_version==version and EntitySnapshot.objects.count()==snapshots and ProductionExclusion.objects.count()==count)
for field in ['paymentEntries','transactions','confirmedProductionKeys']:
 guarded_p=copy.deepcopy(legacy_before);guarded_p[field]=[dict(id='booked')] if field!='confirmedProductionKeys' else ['confirmed']
 guarded=Case.objects.create(case_kind='endorsement',parent_case=root,status='posted',payload=guarded_p,announced_at=stamp,created_by='qa',updated_by='qa')
 try:consolidate_existing_endorsement(str(guarded.case_uid),'2052-09')
 except ValueError:pass
 else:raise AssertionError('booked repair must fail')
 guarded.refresh_from_db();check('repair blocks existing '+field,guarded.payload==guarded_p and guarded.row_version==1)
check('original policy and its installment plan are untouched',root_before==Case.objects.filter(pk=root.pk).values().get())
print(f'{len(checks)}/{len(checks)} AUW endorsement rule API checks passed',flush=True)
