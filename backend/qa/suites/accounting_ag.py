"""A–G business-rule regression. Synthetic records in a disposable database only."""
import os
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
from pathlib import Path
exec(Path('/app/qa/suites/property_original_suite.py').read_text().split('with transaction.atomic():\n try:')[0])
from unittest.mock import patch
from django.test import override_settings
from cases.accounting_policy import FACILITIES,VERSION as ACCOUNTING_VERSION
from cases.calc.swiss_facility import quarter
from cases.calc.payment_terms import taipei_date,add_calendar_days
from fxrates.models import FxRate
from reminders.runner import run_payment
from reminders.models import PaymentAlert
from reminders.messages import resolve_recipients,finance_emails
results=[]
def check(n,ok,d=''):
 results.append((n,bool(ok),d))
 print(('PASS ' if ok else 'FAIL ')+n+(' '+str(d)[:700] if not ok else ''),flush=True)

def apay(client,c,leg,index=0,value=None,ref='SYNTHETIC-EXTERNAL',note=''):
 c.refresh_from_db();candidates=tx_rows(c,leg)
 if leg=='Leg 1' and value is None:
  periods=list(dict.fromkeys(t.get('installmentId') for t in candidates))
  group=[t for t in candidates if t.get('installmentId')==periods[index]]
 else:group=[candidates[index]]
 details=transaction_details(c.payload)
 allocations=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'txNo':t['txNo'],
  'amount':abs(details[t['txNo']]['outstanding']) if value is None else value} for t in group]
 r=call(client,'post','/api/accounting',{'action':'record_transaction_payments','paymentDate':'2026-10-01',
  'amount':sum(a['amount'] for a in allocations),'reference':ref,'note':note,'allocations':allocations})
 c.refresh_from_db();return r

def request(client,c,action,**extra):
 c.refresh_from_db();return call(client,'post','/api/accounting',dict(action=action,caseUid=str(c.case_uid),rowVersion=c.row_version,**extra))

def newpost(name,inst=False,currency='TWD'):
 global serial
 serial+=1
 ris=[dict(name=name,sharePct=60,premium=800,riCommPct=0,taxPct=0,paymentTermsDays=30),dict(name='AG Ordinary B',sharePct=40,premium=800,riCommPct=0,taxPct=0,paymentTermsDays=45)]
 kw=dict(ae=staff.name,ownerPersonnelId=staff.pk,currency=currency,originalPremium=1000,riCommPct=0,taxPct=0,reinsurers=ris,manualTwRef='AG-AUW-'+str(serial))
 if inst:kw.update(installmentEnabled=True,performanceInstallments=[dict(id='I1',premium=400,paymentBaseDate='2026-03-01',performanceMonth=month,paymentTermsDays=30,reinsurerPaymentTerms={'r1':30,'r2':45}),dict(id='I2',premium=600,paymentBaseDate='2026-12-01',performanceMonth='2026-12',paymentTermsDays=60,reinsurerPaymentTerms={'r1':45,'r2':60})])
 return posted(sales,**kw)

def claim_action(client,c,action,**extra):
 c.refresh_from_db();r=call(client,'post','/api/claims',dict(caseUid=str(c.case_uid),rowVersion=c.row_version,action=action,**extra));c.refresh_from_db();return r

with transaction.atomic():
 try:
  serial=0;month=timezone.localtime().strftime('%Y-%m')
  staff=person('sales','reinsurance',name='AG Executive',email='ae@ag.test',supervisor_email='supervisor@ag.test',is_split_eligible=True)
  accountant=person('accounting','finance',name='AG Accountant',email='finance@ag.test')
  manager=person('accounting_manager','finance',name='AG Manager',email='manager@ag.test')
  viewer=person('viewer','business_1',name='AG Viewer')
  sales=account(staff,'ag-sales');fin=account(accountant,'ag-finance');finm=account(manager,'ag-manager');view=account(viewer,'ag-viewer')
  names=['AG Ordinary A',*FACILITIES]
  for name in names:
   c=newpost(name)
   label=name.split(' (')[0]
   check(label+' Announce creates independent T1/T2/T3 for two reinsurers',len(c.payload['transactions'])==6 and all(len(tx_rows(c,leg))==2 for leg in ('Leg 1','Leg 2','Leg 3')))
   check(label+' server owns shared rule version',c.payload.get('accountingRules')==ACCOUNTING_VERSION,c.payload.get('accountingRules'))
   check(label+' Announce creates no cash',not c.payload['paymentEntries'])
   check(label+' premature T2 payment blocked',apay(fin,c,'Leg 2').status_code>=400)
   check(label+' missing reference and note blocked',apay(fin,c,'Leg 1',ref='').status_code==400)
   check(label+' partial premium blocked',apay(fin,c,'Leg 1',value=1).status_code==400)
   check(label+' sales cannot register finance cash',apay(sales,c,'Leg 1').status_code==403)
   r=apay(fin,c,'Leg 1');check(label+' finance can collect full T1 before Production',r.status_code==200,(r.status_code,r.content[:400]))
   t1=tx_rows(c,'Leg 1')[0];details=transaction_details(c.payload)
   check(label+' T1 automatically settled and locked',t1['settlement']=='settled' and details[t1['txNo']]['amountEditLocked'] and not details[t1['txNo']]['canCancelSettlement'])
   check(label+' manual confirm endpoint disabled',request(fin,c,'confirm_facility_settlement',txNo=t1['txNo'],note='manual bypass').status_code==400)
   check(label+' cancelling settlement disabled',request(fin,c,'unconfirm_facility_settlement',txNo=t1['txNo'],note='cancel bypass').status_code>=400)
   check(label+' settled T1 money cannot change',update(sales,c,{'originalPremium':2000}).status_code==409)
   ris=copy.deepcopy(c.payload['reinsurers']);ris[0]['premium']=750
   r=update(sales,c,{'reinsurers':ris});check(label+' unhandled T2 and T3 may be corrected after T1',r.status_code==200,(r.status_code,r.content[:600]))
   check(label+' correction preserves settled T1',sum(row['amount'] for row in tx_rows(c,'Leg 1'))==1000)
   check(label+' correction history retained',bool(c.payload.get('propertyEditHistory')))
   if name==FACILITIES[-1]:
    ri=next(r for r in build_payment_schedule(c.payload)['items'] if r.get('swissFacility'))
    check('Swiss automatic Cedant confirmation uses operation day',ri.get('collectionConfirmed') and ri['collectionConfirmedAt']==taipei_date(),ri)
    check('Swiss payment still requires statement reference',apay(fin,c,'Leg 2').status_code>=400)
    r=request(fin,c,'mark_swiss_statement',scheduleKey=ri['scheduleKey'],reference='AG-SWISS-STATEMENT');check('Swiss statement accepted after automatic T1 settlement',r.status_code==200,r.content[:500])
   check(label+' first T2 payment succeeds',apay(fin,c,'Leg 2',0).status_code==200)
   check(label+' last T2 payment succeeds',apay(finm,c,'Leg 2',1).status_code==200)
   check(label+' T3 automatically settles without cash record',tx_rows(c,'Leg 3')[0]['settlement']=='settled' and len(c.payload['paymentEntries'])==4)
   check(label+' no whole Reverse after cash',wf(sales,'reverse_case',c).status_code==409)
   # Claims use their own creation date and source security; partial receipts remain editable until full.
   r=claim_action(sales,c,'create_claim',claim=dict(dateOfLoss='2026-04-01',outstandingReserve=1000,lossNo='AG LOSS'))
   check(label+' reserve creates no claim accounts',r.status_code==200 and not tx_rows(c,'Claim Leg 1'),r.content[:400])
   cid=c.payload['claims'][-1]['id']
   r=claim_action(sales,c,'record_payment',note='QA synthetic registration', claimId=cid,payment=dict(date='2026-04-02',amount=1000,note='synthetic obligation'))
   check(label+' definite claim creates four accounts immediately',r.status_code==200 and len(tx_rows(c,'Claim Leg 1'))==2 and len(tx_rows(c,'Claim Leg 2'))==2,r.content[:400])
   claims=tx_rows(c,'Claim Leg 1');no=claims[0]['txNo'];d=transaction_details(c.payload)[no]
   expected=quarter(taipei_date(claims[0]['createdAt'])) if name==FACILITIES[-1] else add_calendar_days(taipei_date(claims[0]['createdAt']),15)
   payable=tx_rows(c,'Claim Leg 2')[0]
   check(label+' claim correct due in both directions',d['contractDueDate']==expected and transaction_details(c.payload)[payable['txNo']]['contractDueDate']==expected,(d['contractDueDate'],expected))
   check(label+' no dedicated Facility followup',not any(d.get(k) for k in ('allianzClaim','greatAmericanClaim','qbeClaim')))
   r=apay(fin,c,'Claim Leg 2',value=100);check(label+' claim cannot pay before receipt',r.status_code in (400,409) and r.json().get('error')=='collection_settlement_required',r.content[:400])
   check(label+' partial claim receipt allowed',apay(fin,c,'Claim Leg 1',value=100).status_code==200)
   d=transaction_details(c.payload)[no];check(label+' partial claim keeps due and stays open',d['contractDueDate']==expected and d['settlement']=='partial' and not d['amountEditLocked'])
   entry=next(e for e in c.payload['paymentEntries'] if e.get('transactionNo')==no)
   r=request(fin,c,'edit_payment',entryId=entry['id'],amount=80,reason='Synthetic correction');check(label+' partial unclosed receipt may be corrected with history',r.status_code==200,r.content[:300]);c.refresh_from_db()
   r=apay(fin,c,'Claim Leg 2',value=100);check(label+' claim cannot pay beyond registered receipts',r.status_code in (400,409) and r.json().get('error')=='collection_settlement_required',r.content[:400])
   check(label+' partial Cedant claim payment allowed',apay(fin,c,'Claim Leg 2',value=50).status_code==200)
   r=request(fin,c,'edit_payment',entryId=entry['id'],amount=30,reason='Would break outgoing cap');check(label+' lowering receipts below paid claims rejected',r.status_code==409)
   check(label+' remaining RI claim cash completes automatically',apay(fin,c,'Claim Leg 1').status_code==200)
   d=transaction_details(c.payload)[no];check(label+' full claim locks and stops overdue',d['settlement']=='settled' and d['amountEditLocked'] and not d['trackingDue'] and not d['nextTrackingDate'])
   r=request(fin,c,'edit_payment',entryId=entry['id'],amount=90,reason='Attempt locked change');check(label+' settled claim amount modification blocked',r.status_code==409)
   check(label+' remaining Cedant claim payment auto settles',apay(fin,c,'Claim Leg 2').status_code==200 and tx_rows(c,'Claim Leg 2')[0]['settlement']=='settled')
   # Every case / period is independent; cross-case/period batches are rejected atomically.
   a=newpost(name,inst=True);first=tx_rows(a,'Leg 1')[0];second=tx_rows(a,'Leg 1')[2]
   allocations=[dict(caseUid=str(a.case_uid),rowVersion=a.row_version,txNo=t['txNo'],amount=abs(t['amount'])) for t in (first,second)]
   r=call(fin,'post','/api/accounting',dict(action='record_transaction_payments',paymentDate='2026-10-01',reference='AG-BATCH',amount=sum(x['amount'] for x in allocations),allocations=allocations))
   check(label+' cross-period cash batch rejected atomically',r.status_code==400 and not Case.objects.get(pk=a.pk).payload['paymentEntries'])
   check(label+' per-period T1 can collect independently',apay(fin,a,'Leg 1',0).status_code==200)
   check(label+' second-period T2 remains blocked',apay(fin,a,'Leg 2',2).status_code>=400)
   # Refund obligations come from an actual workflow and never require Production.
   root=newpost(name);r=wf(sales,'create_endorsement',root,manualTwRef='AG-ENDO-'+str(serial));check(label+' refund draft workflow works',r.status_code==201,r.content[:500])
   if r.status_code!=201:continue
   refund=Case.objects.get(case_uid=r.json()['case']['caseUid']);rp=copy.deepcopy(refund.payload)
   rp.update(originalPremium=-200,endoEffectiveDate='2026-03-10',endoTypes=['Premium'],endoText='Synthetic return premium adjustment',situations=[dict(address='1 Test Road',postcode='100')],interest='Return premium',riCommPct=0,taxPct=0)
   for row in rp['reinsurers']:row['premium']=-160
   r=call(sales,'put','/api/cases',dict(caseUid=str(refund.case_uid),rowVersion=refund.row_version,case=rp));refund.refresh_from_db();check(label+' refund Draft save works',r.status_code==200,r.content[:500])
   documents(refund);r=announce(sales,refund);refund.refresh_from_db();check(label+' refund Announce builds accounts',r.status_code==200 and len(tx_rows(refund,'Leg 1'))==2,r.content[:500])
   if r.status_code!=200:continue
   check(label+' Cedant refund waits for all actual RI receipts',apay(fin,refund,'Leg 1').status_code>=400)
   check(label+' first RI refund received',apay(fin,refund,'Leg 2',0).status_code==200)
   check(label+' partial collection does not release Cedant refund',apay(fin,refund,'Leg 1').status_code>=400)
   check(label+' final RI refund received',apay(fin,refund,'Leg 2',1).status_code==200)
   check(label+' full Cedant refund accepted without quarter wait',apay(fin,refund,'Leg 1').status_code==200)
   original_key=build_payment_schedule(root.payload)['items'][0]['scheduleKey'];refund_key=build_payment_schedule(refund.payload)['items'][0]['scheduleKey']
   root.refresh_from_db();refund.refresh_from_db()
   r=call(fin,'post','/api/accounting',dict(action='record_swiss_offset',originalCaseUid=str(root.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=root.row_version,refundRowVersion=refund.row_version,originalKey=original_key,refundKey=refund_key,paymentDate='2026-10-22',amount=200))
   check(label+' offsets disabled on Cedant side',r.status_code==400 and r.json().get('error')=='offset_not_allowed',r.content[:300])
   r=call(fin,'post','/api/accounting',dict(action='record_premium_offset',originalCaseUid=str(root.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=root.row_version,refundRowVersion=refund.row_version,originalKey=build_payment_schedule(root.payload)['items'][1]['scheduleKey'],refundKey=build_payment_schedule(refund.payload)['items'][1]['scheduleKey'],paymentDate='2026-10-22',amount=200))
   check(label+' offsets disabled on reinsurer side',r.status_code==400 and r.json().get('error')=='offset_not_allowed',r.content[:300])
  # Ordinary non-Property financial rules share the reviewed policy.
  generic=posted(sales,ae=staff.name,ownerPersonnelId=staff.pk,classOfBusiness='Marine',classCode='MAR',situations=[dict(address='Test',postcode='100')],riCommPct=0,taxPct=0,reinsurers=[dict(name='AG Marine RI',sharePct=100,premium=800,riCommPct=0,taxPct=0,paymentTermsDays=30)])
  check('Other ordinary classes build aggregate ledgers on Announce',len(generic.payload['transactions'])==3)
  check('Registration explanation without reference is accepted',apay(fin,generic,'Leg 1',ref='',note='Synthetic explanation only').status_code==200)
  check('Other ordinary classes automatically settle T1',tx_rows(generic,'Leg 1')[0]['settlement']=='settled')
  # Production close fixes actual recognition FX, does not rebuild settled/original cash legs.
  final=newpost('AG Production RI',inst=True,currency='USD')
  Case.objects.exclude(pk=final.pk).update(is_archived=True,archived_at=timezone.now(),archived_by='qa')
  FxRate.objects.create(year_month=month,currency='USD',rate=32,created_by='qa',updated_by='qa')
  FxRate.objects.create(year_month='2026-12',currency='USD',rate=35,created_by='qa',updated_by='qa')
  r=call(fin,'get','/api/accounting?view=list');rows_=[x for x in r.json()['transactionRows'] if x['caseUid']==str(final.case_uid)]
  check('Accounting exposes latest FX estimates before recognition',r.status_code==200 and all(x['fxEstimated'] and x['fxRate']==35 for x in rows_),rows_[:1])
  preview_=call(finm,'get','/api/production-report?month='+month).json();sig=preview_['sourceSignature']
  g=call(finm,'post','/api/production-report',dict(action='generate',month=month,sourceSignature=sig));check('Production Generate succeeds',g.status_code in (200,201),g.content[:500])
  if g.status_code in (200,201):
   report=g.json()['report'];before=copy.deepcopy(final.payload['transactions'])
   r=call(finm,'post','/api/production-report',dict(action='close',month=month,reportUid=report['reportUid'],rowVersion=report['rowVersion'],sourceSignature=sig))
   final.refresh_from_db();check('Production close succeeds',r.status_code==200,r.content[:700])
   check('Production close preserves all transaction IDs and amounts',[(t['txNo'],t['amount']) for t in final.payload['transactions']]==[(t['txNo'],t['amount']) for t in before])
   check('Only recognized period fixes posting-month FX',all((t.get('postedMonth')==month and t.get('postingFxRate')==32) if t['installmentId']=='I1' else not t.get('postedMonth') for t in final.payload['transactions']))
   rows_=call(fin,'get','/api/accounting?view=list').json()['transactionRows']
   own=[x for x in rows_ if x['caseUid']==str(final.case_uid)]
   check('Accounting separates fixed and estimated FX after partial recognition',all((not x['fxEstimated'] and x['fxRate']==32) if x['installmentId']=='I1' else x['fxEstimated'] and x['fxRate']==35 for x in own))
  # All six premium categories run due-7, due-day, weekly and suppress duplicates.
  for name in names:
   c=newpost(name)
   if name==FACILITIES[-1]:
    check('Swiss reminder fixture collected and confirmed',apay(fin,c,'Leg 1').status_code==200)
    ri=next(r for r in build_payment_schedule(c.payload)['items'] if r.get('swissFacility'))
    check('Swiss reminder fixture statement accepted',request(fin,c,'mark_swiss_statement',scheduleKey=ri['scheduleKey'],reference='AG-MAIL-SWISS').status_code==200);c.refresh_from_db()
   items=transaction_details(c.payload);no=tx_rows(c,'Leg 2')[0]['txNo'];due=items[no]['contractDueDate'];first=items[no].get('reminderDate') or items[no]['dueDate']
   with patch('reminders.runner._open_cases',side_effect=lambda:Case.objects.filter(pk=c.pk)),patch('reminders.runner._send',return_value='MOCK'),patch('reminders.runner.is_reserved_test_email',return_value=False),override_settings(PAYMENT_REMINDER_EMAIL_ENABLED=True):
    sent=run_payment(first)
    check(name+' reminder sent on Accounting reminder day',sent['sent']>=1,sent)
    alert=PaymentAlert.objects.filter(case=c,alert_kind='due_today' if first==due else 'seven_days_before',schedule_keys__contains=['transaction:'+no]).first()
    check(name+' reminder uses designated internal recipients',alert and set(alert.recipients)=={staff.email,staff.supervisor_email,accountant.email},alert.recipients if alert else None)
    check(name+' due-day first notice is not duplicated',run_payment(due)['sent']==0 if first==due else run_payment(due)['sent']>=1)
    check(name+' reminder weekly overdue',run_payment(add_calendar_days(due,7))['sent']>=1)
    check(name+' duplicate reminder blocked',run_payment(add_calendar_days(due,7))['sent']==0)
   # Partial recipient delivery is visible in the reminder page even if Audit is paused.
  missing=resolve_recipients({'ae':staff.name},[{'name':staff.name,'email':staff.email,'supervisor_email':''}],[accountant.email])
  check('Valid recipients retained when supervisor email missing',set(missing['recipients'])=={staff.email,accountant.email} and bool(missing['missing']) and 'error' not in missing)
  check('Finance managers excluded from reminder recipient role',finance_emails([{'role_code':'accounting','email':accountant.email},{'role_code':'accounting_manager','email':manager.email}])==[accountant.email])
  raise Rollback()
 except Rollback:pass
passed=sum(ok for _,ok,_ in results)
for name,ok,detail in results:
 if not ok:print('FAIL '+name+' '+str(detail)[:1000],flush=True)
print(f'{passed}/{len(results)} Accounting A-G checks passed; test writes rolled back',flush=True)
assert passed==len(results)
