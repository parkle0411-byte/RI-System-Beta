"""2026-10-20 owner review: common receipts, payment completion and claim dates."""
from pathlib import Path
exec(Path('/app/qa/suites/accounting_review_92.py').read_text().split('class Rollback(Exception):pass')[0])
from cases.manual_reference import MANUAL_TW_REF_REINSURER
from cases.allianz_accounting import NAME as AZ
from cases.great_american_accounting import NAME as GA
from cases.calc.payment_terms import build_payment_schedule, premium_installment_plan
from cases.calc.accounting import build_claim_payment_transactions
from reminders.messages import due_kind
from reminders.runner import run_payment
from audit.models import AuditLog
KINDS=[('Ordinary','AR92 RI'),('AUW',MANUAL_TW_REF_REINSURER),('Allianz',AZ),('GA',GA)]
def partyrow(name,share=100):return {'name':name,'sharePct':share,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}
def full(c,case,leg,index=0,**kwargs):
 no=tx(case,leg,index);value=abs(next(t['amount'] for t in case.payload['transactions'] if t['txNo']==no));return pay(c,case,leg,value,index,**kwargs)
def restore_payload(case,p):case.payload=copy.deepcopy(p);case.save()
class Rollback(Exception):pass
try:
 with transaction.atomic():
  fin,fp=client('alignfin','accounting','finance');sales,sp=client('alignsales','sales','reinsurance')
  for label,name in KINDS:
   c=make('ALIGN'+label,policyFrom='2026-01-10',reinsurers=[partyrow(name)])
   schedule=build_payment_schedule(c.payload,'2026-01-10T00:00:00Z')['items'];ri=next(r for r in schedule if r['partyType']=='reinsurer');cedant=next(r for r in schedule if r['partyType']=='cedant')
   expected={'Ordinary':('2026-01-30','2026-02-09'),'AUW':('2026-05-21','2026-05-31'),'Allianz':('2026-04-21','2026-05-01'),'GA':('2026-06-19','2026-06-29')}
   check(label+' premium dates preserve deadlines and use confirmed reminder lead',(ri['dueDate'],ri['contractDueDate'])==expected[label],ri)
   check(label+' Cedant uses own days without month/quarter shift',cedant['contractDueDate']=='2026-02-09')
   check(label+' partial premium outgoing rejected',pay(fin,c,'Leg 2',1).status_code==400)
   if label!='Ordinary':
    check(label+' waits for all Cedant cash',full(fin,c,'Leg 2').status_code==400)
    check(label+' full receipt accepted',full(fin,c,'Leg 1').status_code==200)
    check(label+' receipt alone does not release payment',full(fin,c,'Leg 2').status_code==400)
    check(label+' individual Cedant settlement releases payment',settle(fin,c,'Leg 1').status_code==200)
   check(label+' full outgoing accepted',full(fin,c,'Leg 2').status_code==200)
   check(label+' full outgoing stays overdue until manual completion',details(c)[tx(c,'Leg 2')]['paymentStatus']=='overdue')
   if label!='Ordinary':
    version=c.row_version;check(label+' cancelling Cedant settlement after payment is blocked',settle(fin,c,'Leg 1',undo=True).status_code==409)
    c.refresh_from_db();check(label+' rejected cancellation retains version and settlement',c.row_version==version and details(c)[tx(c,'Leg 1')]['manualSettlementConfirmed'])
   check(label+' manual outgoing settlement ends overdue',settle(fin,c,'Leg 2').status_code==200 and details(c)[tx(c,'Leg 2')]['paymentStatus']=='settled')
   ref=make('ALREF'+label,parent=c,originalPremium=-200,endoEffectiveDate='2026-10-01',announced=datetime(2026,10,20,tzinfo=dtz.utc),reinsurers=[{**partyrow(name),'premium':-160}])
   rr=next(i for i in build_payment_schedule({**ref.payload,'endorsementAnnouncedAt':ref.announced_at.isoformat()})['items'] if i['partyType']=='reinsurer')
   if label in ('Allianz','GA'):
    check(label+' refund also uses deadline minus10',rr['dueDate']=='2027-01-19' if label=='Allianz' else rr['dueDate']=='2027-03-21',rr)
   check(label+' Cedant refund blocked before RI cash',full(fin,ref,'Leg 1').status_code==400)
   check(label+' RI refund partial receipt rejected',pay(fin,ref,'Leg 2',1).status_code==400)
   check(label+' full RI refund cash accepted early',full(fin,ref,'Leg 2').status_code==200)
   check(label+' cash without RI manual settlement cannot release Cedant refund',full(fin,ref,'Leg 1').status_code==400)
   check(label+' RI refund manual settlement accepted',settle(fin,ref,'Leg 2').status_code==200)
   check(label+' full Cedant refund accepted before its original due date',full(fin,ref,'Leg 1').status_code==200)
   check(label+' refund keeps original due date',details(ref)[tx(ref,'Leg 1')]['contractDueDate']=='2026-11-19')
   check(label+' cancelling refund collection after Cedant payment blocked',settle(fin,ref,'Leg 2',undo=True).status_code==409)
  # Whole-period incoming checks include every RI share, never just the target row.
  for label,name in KINDS[1:]:
   c=make('MIX'+label,reinsurers=[partyrow(name,60),partyrow('Other RI',40)])
   check(label+' mixed fixture cash entered per T1',pay(fin,c,'Leg 1',600,0).status_code==200 and pay(fin,c,'Leg 1',400,1).status_code==200)
   check(label+' first T1 can settle without touching peer',settle(fin,c,'Leg 1',0).status_code==200)
   check(label+' peer T1 still blocks RI payment',full(fin,c,'Leg 2').status_code==400)
   check(label+' last explicit T1 settlement releases whole installment',settle(fin,c,'Leg 1',1).status_code==200 and full(fin,c,'Leg 2').status_code==200)
  # Ordinary incoming premium is not a newly introduced payment prerequisite.
  c=make('ORDINDEPENDENT');check('ordinary payment remains independent of Cedant receipt',full(fin,c,'Leg 2').status_code==200 and not Case.objects.get(pk=c.pk).payload['paymentEntries'][0].get('nonCash'))
  # Refund cash and manual confirmation are required even if an old non-cash entry cleared the RI.
  for label,name in KINDS[:2]:
   root=make('NOOFFSET'+label,reinsurers=[partyrow(name)])
   refund=make('NOOFFSETREF'+label,parent=root,originalPremium=-200,reinsurers=[{**partyrow(name),'premium':-160}])
   before=copy.deepcopy(refund.payload)
   check(label+' RI offset endpoint rejects without changing history',offset(fin,root,refund,'reinsurer').status_code==400 and Case.objects.get(pk=refund.pk).payload==before)
   schedule=build_payment_schedule(refund.payload)['items'];ri=next(r for r in schedule if r['partyType']=='reinsurer')
   refund.payload['paymentEntries']=[{'id':'legacy-offset','entryType':'payment','entryKind':'offset','nonCash':True,'scheduleKey':ri['scheduleKey'],'amount':ri['amount'],'paymentDate':'2026-10-01'}];refund.save()
   check(label+' old non-cash clearance can be manually reconciled',settle(fin,refund,'Leg 2').status_code==200)
   check(label+' offset is not a cash refund receipt',full(fin,refund,'Leg 1').status_code==400)
  # Normal Cedant-side offsets survive only after every RI cash refund is cleared.
  root=make('CEDANTOFFSET');refund=make('CEDANTOFFSETREF',parent=root,originalPremium=-200,reinsurers=[{**partyrow('AR92 RI'),'premium':-160}])
  check('ordinary Cedant offset waits for all RI refunds',offset(fin,root,refund).status_code==400)
  check('ordinary Cedant offset is preserved after full RI cash and settlement',full(fin,refund,'Leg 2').status_code==200 and settle(fin,refund,'Leg 2').status_code==200 and offset(fin,root,refund).status_code==200)
  # A refund endorsement split into T1s must be returned in one batch, not one T1 at a time.
  root=make('REFMULTI',reinsurers=[partyrow('R A',60),partyrow('R B',40)])
  refund=make('REFMULTIREF',parent=root,originalPremium=-200,reinsurers=[{**partyrow('R A',60),'premium':-160},{**partyrow('R B',40),'premium':-160}])
  for i in range(2):assert full(fin,refund,'Leg 2',i).status_code==200 and settle(fin,refund,'Leg 2',i).status_code==200
  check('cannot refund only one split Cedant T1',full(fin,refund,'Leg 1',0).status_code==400)
  allocations=[]
  for i in range(2):
   no=tx(refund,'Leg 1',i);allocations.append({'caseUid':str(refund.case_uid),'rowVersion':refund.row_version,'txNo':no,'amount':abs(next(t['amount'] for t in refund.payload['transactions'] if t['txNo']==no))})
  check('all Cedant refund T1s can be paid in one full batch',request(fin,'record_transaction_payments',paymentDate='2026-10-20',amount=200,allocations=allocations).status_code==200)
  # Claims: creation date is authoritative even when Announce or entered date differs.
  for label,name in KINDS:
   c=make('CLAIM'+label,ae=sp.name,reinsurers=[partyrow(name)])
   claim={'id':1,'dateOfLoss':'2026-01-01','payments':[]};payment={'id':1,'date':'2025-01-01','amount':1000,'createdAt':'2026-01-01T16:30:00Z','claimAnnouncedAt':'2026-01-10T00:00:00Z'}
   claim['payments']=[payment];c.payload['claims']=[claim]
   source={**c.payload};payment['splitSource']={'reinsurers':source['reinsurers'],'classOfBusiness':'Property'}
   c.payload['transactions']=[{**t,'createdAt':payment['createdAt'],'claimAnnouncedAt':payment['claimAnnouncedAt'],'dueDate':'2026-01-25','splitSource':payment['splitSource']} for t in build_claim_payment_transactions(c.payload,source,claim,payment)];c.save()
   no=tx(c,'Claim Leg 1');get=lambda day:transaction_details(c.payload,day+'T00:00:00Z')[no]
   check(label+' claim due uses Taiwan creation date not Announce/payment date',get('2026-01-02')['contractDueDate']=='2026-01-17')
   check(label+' claim first reminder is creation day8',get('2026-01-10')['trackingDue'] and not get('2026-01-09')['trackingDue'])
   check(label+' claim reminder dates are due-7/due/due+7',all(get(day)['trackingDue'] for day in ('2026-01-10','2026-01-17','2026-01-24')) and not get('2026-01-18')['trackingDue'])
   check(label+' claim is never deferred to month/quarter settlement',get('2026-01-02')['dueDate']=='2026-01-17')
   check(label+' partial claim receipt remains available',pay(fin,c,'Claim Leg 1',400).status_code==200)
   c.refresh_from_db();check(label+' partial receipt keeps original date and reminder',get('2026-01-24')['contractDueDate']=='2026-01-17' and get('2026-01-24')['trackingDue'])
   check(label+' remaining claim receipt accepted',pay(fin,c,'Claim Leg 1',600).status_code==200)
   c.refresh_from_db();d=get('2026-01-24')
   check(label+' zero claim balance stops tracking before manual settlement',not d['trackingDue'] and not d['nextTrackingDate'] and d['settlement']=='pending_confirmation' and d['paymentStatus']!='overdue')
   check(label+' claim receipt and settlement remain separate',not d['manualSettlementConfirmed'])
   # Restore an untouched receivable for the runner, isolated from all other cases.
   c.payload['paymentEntries']=[];c.payload['transactions']=[t for t in c.payload['transactions'] if t['legType']=='Claim Leg 1'];c.save()
   with patch('reminders.runner._open_cases',side_effect=lambda:Case.objects.filter(pk=c.pk)),patch('reminders.runner._send',return_value='MOCK') as sender,patch('reminders.runner.is_reserved_test_email',return_value=False),override_settings(PAYMENT_REMINDER_EMAIL_ENABLED=True):
    check(label+' no old creation-day7 reminder',run_payment('2026-01-09')['sent']==0)
    check(label+' shared claim email on day8',run_payment('2026-01-10')['sent']==1)
    check(label+' shared claim email on due day',run_payment('2026-01-17')['sent']==1)
    check(label+' shared overdue email every7 days',run_payment('2026-01-24')['sent']==1 and run_payment('2026-01-25')['sent']==0)
    check(label+' duplicate same-day email suppressed',run_payment('2026-01-24')['sent']==0)
    assert pay(fin,c,'Claim Leg 1',1000).status_code==200
    stopped=run_payment('2026-01-31')
    check(label+' full receipt stops actual runner without settlement',stopped['sent']==0 and sender.call_count==3,(stopped,sender.call_count,transaction_details(Case.objects.get(pk=c.pk).payload)))
   if label in ('Allianz','GA'):
    c.refresh_from_db();action='record_allianz_claim_followup' if label=='Allianz' else 'record_great_american_claim_followup'
    check(label+' follow-up cannot continue after full receipt',request(fin,action,caseUid=str(c.case_uid),rowVersion=c.row_version,txNo=no,note='completed').status_code==400)
  # Each period is independent; an unpaid second period must not block a cleared first one.
  for label,name in KINDS[1:]:
   periods=[{'id':'I'+str(i),'performanceMonth':'2026-0'+str(i),'paymentBaseDate':'2026-0'+str(i)+'-10','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':30}} for i in (1,2)]
   c=make('PERIOD'+label,installmentEnabled=True,performanceInstallments=periods,reinsurers=[partyrow(name)])
   c.payload['transactions']=[t for i in premium_installment_plan(c.payload) for t in build_premium_transactions(c.payload,i)];c.save()
   check(label+' first installment can be received and individually settled',full(fin,c,'Leg 1',0).status_code==200 and settle(fin,c,'Leg 1',0).status_code==200)
   check(label+' only the received installment is released',full(fin,c,'Leg 2',0).status_code==200 and full(fin,c,'Leg 2',1).status_code==400)
  legacy=make('LEGACYPARTIAL',reinsurers=[partyrow(GA)])
  no=tx(legacy,'Leg 2');old={'id':'old-partial','entryType':'payment','transactionNo':no,'scheduleKey':'case-effective-date:reinsurer:r1','amount':200,'paymentDate':'2026-01-01'}
  legacy.payload['paymentEntries']=[copy.deepcopy(old)];legacy.save()
  check('legacy partial history waits for new full Cedant prerequisite',pay(fin,legacy,'Leg 2',600).status_code==400)
  assert full(fin,legacy,'Leg 1').status_code==200 and settle(fin,legacy,'Leg 1').status_code==200
  check('legacy partial premium permits only one full remaining-balance entry',pay(fin,legacy,'Leg 2',300).status_code==400 and pay(fin,legacy,'Leg 2',600).status_code==200)
  legacy.refresh_from_db();check('legacy partial payment record remains byte-for-byte unchanged',legacy.payload['paymentEntries'][0]==old)
  # Scope isolation and frozen date/allocation history are validated separately by parity.
  # Preserve the concurrent GA release: each registration stays within one case/period/request.
  a=make('REG-A',reinsurers=[partyrow(GA)]);b=make('REG-B',reinsurers=[partyrow(GA)])
  def batch(rows,reference='SHARED-EXTERNAL'):
   alloc=[]
   for case,leg,index in rows:
    no=tx(case,leg,index);alloc.append({'caseUid':str(case.case_uid),'rowVersion':case.row_version,'txNo':no,'amount':abs(details(case)[no]['outstanding'])})
   return request(fin,'record_transaction_payments',paymentDate='2026-10-20',reference=reference,amount=sum(x['amount'] for x in alloc),allocations=alloc)
  check('GA cannot combine different cases even for same Cedant',batch([(a,'Leg 1',0),(b,'Leg 1',0)]).status_code==400)
  check('GA rejected mixed-case registration leaves both balances intact',details(a)[tx(a,'Leg 1')]['outstanding']==1000 and details(b)[tx(b,'Leg 1')]['outstanding']==1000)
  check('GA cases may reuse an external reference on separate registrations',batch([(a,'Leg 1',0)]).status_code==200 and batch([(b,'Leg 1',0)]).status_code==200)
  periods=[{'id':'P'+str(i),'performanceMonth':'2026-01','paymentBaseDate':'2026-01-10','premium':500,'paymentTermsDays':30,'reinsurerPaymentTerms':{'r1':30}} for i in (1,2)]
  c=make('REG-PERIOD',installmentEnabled=True,performanceInstallments=periods,reinsurers=[partyrow(GA)])
  c.payload['transactions']=[t for i in premium_installment_plan(c.payload) for t in build_premium_transactions(c.payload,i)];c.save()
  check('GA same-deadline installments remain separate registrations',batch([(c,'Leg 1',0),(c,'Leg 1',1)]).status_code==400)
  check('GA each same-deadline installment can be recorded separately',batch([(c,'Leg 1',0)]).status_code==200 and batch([(c,'Leg 1',1)]).status_code==200)
  c=make('REG-CLAIMS',reinsurers=[partyrow(GA)]);claim={'id':1};c.payload['transactions']=[]
  for pid in (1,2):
   payment={'id':pid,'date':'2026-01-01','amount':1000,'createdAt':'2026-01-01T00:00:00Z'}
   c.payload['transactions'] += [{**t,'createdAt':payment['createdAt']} for t in build_claim_payment_transactions(c.payload,c.payload,claim,payment)]
  c.save()
  check('GA same-date claim requests remain separate registrations',batch([(c,'Claim Leg 1',0),(c,'Claim Leg 1',1)]).status_code==400)
  check('GA claim requests reuse an external reference individually',batch([(c,'Claim Leg 1',0)]).status_code==200 and batch([(c,'Claim Leg 1',1)]).status_code==200)
  raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} accounting alignment checks passed; rolled back')
