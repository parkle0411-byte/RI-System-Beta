"""Each Facility accepts partial actual cash without losing date/statement gates."""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.accounting_policy import FACILITIES
from cases.calc.payment_terms import build_payment_schedule
from cases.property_original import refresh_transactions

def set_reinsurer(c,name,refund=False):
 c.refresh_from_db();p=copy.deepcopy(c.payload);p['reinsurers'][0]['name']=name
 if '0609 AUW' in name:p['reinsurers'][0]['foreignBroker']='Howden Specialty Limited'
 if refund:
  p.update(parentTwRef='QA-FAC-ROOT',endoEffectiveDate='2026-09-01',endorsementAnnouncedAt='2026-09-01T00:00:00Z',originalPremium=-200)
  p['reinsurers'][0].update(premium=-200,riCommPct=20)
 p['transactions']=transactions(p,'2026-09-01T00:00:00Z');c.payload=p;c.save();return c
class Done(Exception):pass
try:
 with transaction.atomic():
  fin=client('facility-fin','accounting');sales=client('facility-sales','sales')
  for index,name in enumerate(FACILITIES):
   a=set_reinsurer(fixture('QA-NEWFAC-'+str(index)),name);refund=set_reinsurer(fixture('QA-NEWFAC-REF-'+str(index)),name,True)
   t1=leg(a,'Leg 1');t2=leg(a,'Leg 2');rt1=leg(refund,'Leg 1');rt2=leg(refund,'Leg 2')
   review([(a,t1)]);r=register([(a,t1,1000,0)],1000);check(name+' full T1 setup',r.status_code==200,r.content)
   if 'Swiss' in name:
    review([(a,t2)]);r=register([(a,t2,800,0)],-800)
    check('Swiss positive payment still requires independent statement',r.status_code==409 and 'statement' in r.json()['message'].lower(),r.content)
    a.refresh_from_db();item=next(i for i in build_payment_schedule(a.payload)['items'] if i.get('swissFacility'))
    r=api(fin,{'action':'mark_swiss_statement','caseUid':str(a.case_uid),'rowVersion':a.row_version,'scheduleKey':item['scheduleKey'],'reference':'SWRPA-1234567-12345678'})
    check('Swiss statement reference accepted without extra regex restrictions',r.status_code==200,r.content)
   else:review([(a,t2)])
   review([(refund,rt2)])
   due_a=transaction_details(Case.objects.get(pk=a.pk).payload)[t2]['contractDueDate'];due_ref=transaction_details(refund.payload)[rt2]['contractDueDate']
   r=register([(a,t2,640,0)],-640)
   check(name+' partial premium payment accepted',r.status_code==200,r.content)
   r=register([(refund,rt2,80,0)],80);check(name+' partial refund receipt accepted',r.status_code==200,r.content)
   refund.refresh_from_db();dr=transaction_details(refund.payload)
   check(name+' partial refund still blocks Cedant refund',dr[rt2]['settlement']=='partial' and not dr[rt1]['paymentAllowed'],dr[rt1])
   r=register([(refund,rt2,80,0)],80);check(name+' remaining refund receipt accepted',r.status_code==200,r.content)
   a.refresh_from_db();refund.refresh_from_db();da=transaction_details(a.payload);dr=transaction_details(refund.payload)
   check(name+' full refund collection releases Cedant refund',dr[rt2]['settlement']=='settled' and dr[rt1]['paymentAllowed'],dr[rt1])
   check(name+' partial cash retains original due dates',da[t2]['contractDueDate']==due_a and dr[rt2]['contractDueDate']==due_ref)
   review([(refund,rt1)]);r=register([(refund,rt1,200,0)],-200)
   check(name+' Cedant refund after actual receipt accepted',r.status_code==200,r.content)
   history=fin.get('/api/accounting?view=list').json()['cashBatches'];batch=next(b for b in history if b['batchId']==r.json()['batchId'])
   check(name+' bank history shows actual signed payment',batch['netCash']==-200 and batch['payableSettled']==200)
   # Whole reversal must not undo the RI recovery once Cedant refund relies on it.
   prior=next(e['batchId'] for e in refund.payload['paymentEntries'] if e.get('transactionNo')==rt2)
   r=reverse(prior,[refund]);check(name+' refund receipt reversal blocked by downstream refund',r.status_code==409 and r.json()['error']=='downstream_payment_locked',r.content)
  print(str(len(checks))+' passed cross-Facility cash settlement checks',flush=True)
  raise Done()
except Done:pass
