"""Exercise owner-approved business outcomes through API and production calculations."""
from pathlib import Path
exec(Path('/app/qa/suites/case_workflow.py').read_text().split('try:\n    with transaction.atomic():')[0])
from datetime import datetime, timezone as dtz
from django.utils import timezone
from masterdata.models import MasterRecord
from cases.draft import normalize_draft, validate_announce_ready, loss_record_save_errors
from cases.property_original import VERSION, VERSION_KEY, enabled, totals, allocate, periods, report_values, refresh_transactions, persist_settlements
from cases.cash_ledger import transaction_details
from cases.calc.payment_terms import build_payment_schedule
from cases.calc.signed_slip import reminder_due
from cases.calc.accounting import build_premium_transactions
from production.calc import build_production_preview
from production.closing import confirm_case
from production.views import case_source
from reminders.messages import contact_for
wf_ready=ready

def p_ready(**over):
    base=wf_ready(classOfBusiness='Property',classCode='PD',originalInsuredCn='測試保戶',
        reinsuredRetention="Advice of Reinsured's retention waived.",currency='TWD',originalPremium=1001,riCommPct=12.5,taxPct=1.5,
        situations=[dict(address='1 Test Road',postcode='SW1A 1AA')],
        reinsurers=[dict(name='Property RI A',sharePct=33.33,premium=800,riCommPct=10,taxPct=1,paymentTermsDays=90),dict(name='Property RI B',sharePct=33.33,premium=800,riCommPct=10,taxPct=1,paymentTermsDays=60)])
    base.setdefault('basisOfValuation','Replacement Value')
    base.update(over);return base

def new_case(client,**over):
    r=call(client,'post','/api/cases',{'case':p_ready(**over)})
    assert r.status_code==201,(r.status_code,r.content)
    return Case.objects.get(case_uid=r.json()['case']['caseUid'])

def documents(c):
    return [doc(c,'offer'),doc(c,'confirmation',[r['name'] for r in c.payload['reinsurers']])]

def posted(client,**over):
    c=new_case(client,**over);documents(c);r=announce(client,c)
    assert r.status_code==200,(r.status_code,r.content)
    c.refresh_from_db();return c

def update(client,c,changes,reason='Approved test change'):
    c.refresh_from_db();payload=copy.deepcopy(c.payload);payload.update(changes)
    r=call(client,'put','/api/cases',{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'case':payload,'reason':reason,'reverseCorrectionConfirmed':True})
    c.refresh_from_db();return r

def tx_rows(c,leg):
    c.refresh_from_db();return [t for t in c.payload.get('transactions',[]) if t.get('legType')==leg and not t.get('reversed') and not t.get('isReversalEntry')]

def pay(client,c,leg,index=0,value=None):
    candidates=tx_rows(c,leg)
    if leg=='Leg 1' and value is None:
        periods=list(dict.fromkeys(t.get('installmentId') for t in candidates))
        group=[t for t in candidates if t.get('installmentId')==periods[index]]
    else:group=[candidates[index]]
    details=transaction_details(c.payload)
    allocations=[{'caseUid':str(c.case_uid),'rowVersion':c.row_version,'txNo':row['txNo'],
                  'amount':abs(details[row['txNo']]['outstanding']) if value is None else value} for row in group]
    response=call(client,'post','/api/accounting',{'action':'record_transaction_payments','paymentDate':'2026-10-22',
        'note':'QA synthetic registration','amount':sum(a['amount'] for a in allocations),'allocations':allocations})
    if response.status_code>=400 and value is None:print('PAY CHECK',leg,index,response.status_code,response.content[:1200],flush=True)
    return response

def preview(c,month=None,rate=30):
    c.refresh_from_db();month=month or timezone.localtime(c.announced_at).strftime('%Y-%m')
    return build_production_preview([case_source(c)],month,{month:{'USD':rate}},[])

from io import StringIO
from decimal import Decimal, ROUND_HALF_UP
from django.core.management import call_command
from cases.models import MAX_DOCUMENT_BYTES
from cases.calc.premium_money import premium_input_errors
from cases.property_original import confirm_production, report_amounts
from production.calc import next_production_month
from unittest.mock import patch
import base64

with transaction.atomic():
 try:
    staff=person('sales','reinsurance',name='Edge Executive',email='edge-ae@property.test',is_split_eligible=True)
    owner=person('sales','reinsurance',name='Edge Owner',email='edge-owner@property.test',is_split_eligible=True)
    other=person('viewer','business_1',name='Edge Other',email='edge-other@property.test',is_split_eligible=True)
    finance=person('accounting_manager','finance',name='Edge Finance')
    sales=account(staff,'edge-sales');fin=account(finance,'edge-finance')
    shared=dict(ownerPersonnelId=owner.pk,ae=staff.name)
    split=[dict(personnelId=staff.pk,name=staff.name,pct=40),dict(personnelId=other.pk,name=other.name,pct=60)]
    rr=call(sales,'post','/api/cases',{'case':p_ready(parentTwRef='FAKE-ENDORSEMENT',originalPremium=0)})
    check('Original cannot forge Endorsement identity to bypass rules',rr.status_code==400)
    check('Property cannot select Treaty',bool(normalize_draft(p_ready(reinsuranceStructure='TREATY'))['errors']))
    inst=[dict(id='P1',paymentBaseDate='2026-03-01',performanceMonth='2026-03',premium=400,paymentTermsDays=30,reinsurerPaymentTerms={'r1':45,'r2':60}),dict(id='P2',paymentBaseDate='2026-04-01',performanceMonth='2026-04',premium=601,paymentTermsDays=45,reinsurerPaymentTerms={'r1':60,'r2':75})]
    c=posted(sales,**shared,installmentEnabled=True,performanceInstallments=inst)
    check('two installments create per-reinsurer T1/T2/T3',len(c.payload['transactions'])==12)
    check('period T1 allocations reconcile to Case aggregate',sum(t['amount'] for t in tx_rows(c,'Leg 1'))==574)
    check('period T2 allocations retain each RI total',sum(t['amount'] for t in tx_rows(c,'Leg 2') if t['reinsurerIdx']==0)==237 and sum(t['amount'] for t in tx_rows(c,'Leg 2') if t['reinsurerIdx']==1)==237)
    check('period T3 is each period T1 minus its T2',all(t['amount']==next(x['amount'] for x in c.payload['transactions'] if x['legType']=='Leg 1' and x['installmentId']==t['installmentId'] and x.get('reinsurerIdx')==t.get('reinsurerIdx'))-sum(x['amount'] for x in c.payload['transactions'] if x['legType']=='Leg 2' and x['installmentId']==t['installmentId'] and x.get('reinsurerIdx')==t.get('reinsurerIdx')) for t in tx_rows(c,'Leg 3')))
    check('first period T1 is received and auto settles',pay(fin,c,'Leg 1',0).status_code==200)
    changed=copy.deepcopy(c.payload['performanceInstallments']);changed[0]['paymentBaseDate']='2026-03-02'
    check('settled period T1 locks that period base date',update(sales,c,{'performanceInstallments':changed}).status_code==409)
    changed=copy.deepcopy(c.payload['performanceInstallments']);changed[1]['paymentBaseDate']='2026-05-02'
    response=update(sales,c,{'performanceInstallments':changed})
    check('an untouched peer period remains editable',response.status_code==200,response.content[:700])
    check('unmodified Performance Month follows new base date',c.payload['performanceInstallments'][1]['performanceMonth']=='2026-05')
    changed=copy.deepcopy(c.payload['performanceInstallments']);changed[1].update(performanceMonth='2026-06',performanceMonthManual=True)
    check('Performance Month may be manually overridden',update(sales,c,{'performanceInstallments':changed}).status_code==200)
    changed=copy.deepcopy(c.payload['performanceInstallments']);changed[1]['paymentBaseDate']='2026-07-03'
    check('subsequent base date edit accepted',update(sales,c,{'performanceInstallments':changed}).status_code==200)
    check('manually overridden Performance Month is retained',c.payload['performanceInstallments'][1]['performanceMonth']=='2026-06')
    changed=copy.deepcopy(c.payload['performanceInstallments']);changed[1]['performanceMonthManual']=False
    check('manual flag cannot be reset by an API client',update(sales,c,{'performanceInstallments':changed}).status_code==200 and c.payload['performanceInstallments'][1]['performanceMonthManual'])
    check('first period payout does not wait for second T1',pay(fin,c,'Leg 2',0).status_code==200)
    check('second period payout waits for its own T1',pay(fin,c,'Leg 2',2).status_code>=400)
    # An already-confirmed performance month stays fixed while unsettled due dates can change.
    d=posted(sales,**shared,installmentEnabled=True,performanceInstallments=inst)
    source=preview(d,month='2026-03')['rows'];first=[r for r in source if r['reinsurer']=='Property RI A']
    state=confirm_case(case_source(d),first,posting_month='2026-03');d.payload=state['payload'];d.status=state['nextStatus'];d.save()
    changed=copy.deepcopy(d.payload['performanceInstallments']);changed[0]['paymentBaseDate']='2026-05-15'
    response=update(sales,d,{'performanceInstallments':changed})
    check('unsettled base date editable after partial period Production',response.status_code==200,response.content[:700])
    check('confirmed period Performance Month remains original',d.payload['performanceInstallments'][0]['performanceMonth']=='2026-03')
    changed=copy.deepcopy(d.payload['performanceInstallments']);changed[0].update(performanceMonth='2026-05',performanceMonthManual=True)
    check('confirmed Performance Month rejects manual changes',update(sales,d,{'performanceInstallments':changed}).status_code==409)
    # Existing valid terms can change with a reason before Settlement, through the Accounting API too.
    e=posted(sales,**shared)
    response=call(sales,'post','/api/accounting',{'action':'complete_payment_terms','caseUid':str(e.case_uid),'rowVersion':e.row_version,'partyKey':'r1','days':100,'reason':'Revised contract days'})
    e.refresh_from_db();check('existing RI days can change through guarded editor',response.status_code==200,response.content[:700])
    if response.status_code==200:
        check('updated terms retained in history',e.payload['reinsurers'][0]['paymentTermsDays']==100 and bool(e.payload.get('paymentTermsHistory')))
    # Account Executive and Split may change only before any Production / affected T3 lock.
    response=update(sales,e,{'ae':owner.name});check('AE change allowed before Production / T3 lock',response.status_code==200,response.content[:700])
    check('un-split report moves premium and T3 to new AE',all(r['ae']==owner.name for r in preview(e)['rows']))
    check('Split can be enabled after Announce with reason',update(sales,e,{'splitEnabled':True,'splitParties':split}).status_code==200)
    changed=[{**split[0],'pct':70},{**split[1],'pct':30}]
    check('Split can change to70/30 before Production',update(sales,e,{'splitParties':changed}).status_code==200)
    rows_=preview(e)['rows'];check('Other Staff30% receives rounded premium and T3',sum(r['premium'] for r in rows_ if r['ae']==other.name)==200 and sum(r['income'] for r in rows_ if r['ae']==other.name)==30)
    # Source amounts and staff allocation remain balanced with multiple RI and foreign exchange.
    fx=posted(sales,**shared,currency='USD',splitEnabled=True,splitParties=split,reinsurers=[dict(name='FX RI A',sharePct=12.5,premium=710.34,riCommPct=12,taxPct=1,paymentTermsDays=90),dict(name='FX RI B',sharePct=25,premium=720.34,riCommPct=14,taxPct=1,paymentTermsDays=90),dict(name='FX RI C',sharePct=37.5,premium=730.34,riCommPct=15,taxPct=1,paymentTermsDays=90)])
    raw=preview(fx,rate=30.123)['rows'];full=totals(fx.payload)
    expected_premium=float(Decimal(str(full['cedantPremium']))*Decimal('30.123'));expected_income=float(Decimal(str(full['leg3']))*Decimal('30.123'))
    ntd=lambda v:float(Decimal(str(v)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    check('foreign premium NTD rows conserve aggregate',sum(r['premium'] for r in raw)==ntd(expected_premium))
    check('foreign income NTD rows conserve aggregate',sum(r['income'] for r in raw)==ntd(expected_income))
    check('foreign Other Staff allocation conserves aggregate ratio',sum(r['income'] for r in raw if r['ae']==other.name)==ntd(ntd(expected_income)*.6))
    state=confirm_case(case_source(fx),raw,posting_month=raw[0]['month']);fx.payload=state['payload'];fx.status=state['nextStatus'];fx.save()
    reverse=wf(sales,'reverse_case',fx);fx.refresh_from_db();negative=preview(fx,rate=99)['rows']
    check('FX Reverse succeeds before any Settlement',reverse.status_code==200,reverse.content[:700])
    check('FX reversal keeps original NTD instead of new month rate',sum(r['premium'] for r in negative)==-sum(r['premium'] for r in raw) and sum(r['income'] for r in negative)==-sum(r['income'] for r in raw))
    # Class / RI fixed clauses and canonical Title remain current without reformatting.
    cls=MasterRecord.objects.create(entity_type='class',code='PD',name='Property',payload={'fixedClauses':[{'code':'LMA9000','title':'Class fallback title'}]},created_by='test',updated_by='test')
    MasterRecord.objects.create(entity_type='reinsurer',code='TEST-RIA',name='Property RI A',payload={'fixedClauses':[{'code':'NMA9001','title':'RI fixed title','classIds':[cls.pk]}]},created_by='test',updated_by='test')
    clause=MasterRecord.objects.create(entity_type='clause',code='LMA9000',name='Canonical title without prefixed code',created_by='test',updated_by='test')
    mdm=new_case(sales,**shared)
    titles={r['code']:r['title'] for r in mdm.payload['clauseDetails']}
    check('server auto-adds Class fixed clause',titles.get('LMA9000')=='Canonical title without prefixed code')
    check('server auto-adds applicable RI fixed clause',titles.get('NMA9001')=='RI fixed title')
    clause.name='Newest literal Title';clause.save()
    response=call(sales,'get','/api/cases?caseUid='+str(mdm.case_uid))
    titles={r['code']:r['title'] for r in response.json()['case']['payload']['clauseDetails']}
    check('changed MDM Title is used immediately verbatim',titles.get('LMA9000')=='Newest literal Title')
    # Boundary of actual PDF upload and real DB CHECK is30MB for this scope.
    pdf=b'%PDF-'+b'0'*(MAX_DOCUMENT_BYTES-5)
    body={'caseUid':str(mdm.case_uid),'kind':'offer','filename':'property-boundary.pdf','base64':base64.b64encode(pdf).decode()}
    response=call(sales,'post','/api/case-documents',body)
    check('exactly30MB upload accepted by API and DB',response.status_code==201,response.content[:700])
    if response.status_code==201:
        uploaded=CaseDocument.objects.get(pk=response.json()['file']['id'])
        from cases.storage import delete
        delete(uploaded.storage_key)
    body['base64']=base64.b64encode(pdf+b'0').decode();response=call(sales,'post','/api/case-documents',body)
    check('30MB plus1 byte rejected',response.status_code==413,response.content[:700])
    del pdf,body
    claim_cash=posted(sales,**shared)
    claim_cash.payload['transactions'].append(dict(txNo=claim_cash.tw_ref+'-C1-P1-R1-T1',source='claim',legType='Claim Leg 1',claimId=1,paymentId=1,reinsurerIdx=0,reinsurer='Property RI A',amount=100,settlement='open'))
    claim_cash.payload['paymentEntries']=[dict(id='claim-receipt',entryType='payment',transactionNo=claim_cash.tw_ref+'-C1-P1-R1-T1',scheduleKey='claim-1-1:r1',amount=100,paymentDate='2026-10-22')]
    claim_cash.save()
    check('currency cannot relabel existing claim cash history',update(sales,claim_cash,{'currency':'USD'}).status_code==409)
    # New workflows must not inherit the parent's accounting version or Production snapshots.
    for action in ('create_endorsement','create_renewal'):
        parent=posted(sales,**shared)
        parent.status='closed';parent.payload['productionHistory']=[{'id':'parent-snapshot'}];parent.payload['propertyEditHistory']=[{'reason':'parent-only'}];parent.save()
        response=wf(sales,action,parent)
        check(action+' succeeds from confirmed Property Original',response.status_code==201,response.content[:600])
        if response.status_code==201:
            child=Case.objects.get(case_uid=response.json()['case']['caseUid'])
            check(action+' starts without parent financial history',not child.payload.get('productionHistory') and not child.payload.get('propertyEditHistory') and not child.payload.get('confirmedProductionKeys') and not child.payload.get('transactions') and not child.payload.get('paymentEntries'))
            check(action+' uses the proper accounting policy',enabled(child.payload))
    # Conversion is explicit, idempotent, and leaves historical ledger/cash unchanged.
    old=normalize_draft(p_ready(**shared))['value'];old['twRef']='LEGACY-ELIGIBLE';old['transactions']=[]
    untouched=Case.objects.create(tw_ref='LEGACY-ELIGIBLE',status='posted',payload=old,currency='TWD',owner_personnel=owner,announced_at=timezone.now(),created_by='test',updated_by='test')
    old_hist=copy.deepcopy(old);old_hist['twRef']='LEGACY-HISTORY';old_hist['transactions']=build_premium_transactions(old_hist)
    t=next(t for t in old_hist['transactions'] if t['legType']=='Leg 1')
    old_hist['paymentEntries']=[{'id':'old-cash','entryType':'payment','transactionNo':t['txNo'],'scheduleKey':'case-effective-date:cedant','amount':t['amount'],'paymentDate':'2026-01-01'}]
    historical=Case.objects.create(tw_ref='LEGACY-HISTORY',status='posted',payload=old_hist,currency='TWD',owner_personnel=owner,announced_at=timezone.now(),created_by='test',updated_by='test')
    before=copy.deepcopy(historical.payload);out=StringIO();call_command('apply_property_original',stdout=out)
    untouched.refresh_from_db();check('conversion dry run does not change Case',not untouched.payload.get(VERSION_KEY) and not untouched.payload['transactions'])
    out=StringIO();call_command('apply_property_original',apply=True,stdout=out)
    untouched.refresh_from_db();historical.refresh_from_db()
    check('eligible legacy Case adopts per-reinsurer ledger',untouched.payload.get(VERSION_KEY)==VERSION and len(untouched.payload['transactions'])==6)
    check('historical Case retains old accounting version',historical.payload.get(VERSION_KEY)=='historical')
    check('historical transactions/cash preserved exactly',historical.payload['transactions']==before['transactions'] and historical.payload['paymentEntries']==before['paymentEntries'])
    version=untouched.row_version;out=StringIO();call_command('apply_property_original',apply=True,stdout=out);untouched.refresh_from_db()
    check('conversion is idempotent',untouched.row_version==version)
 finally:
    transaction.set_rollback(True)
for label,ok,detail in results:print(('PASS ' if ok else 'FAIL ')+label+(' '+str(detail)[:700] if not ok else ''))
passed=sum(ok for _,ok,_ in results);print(f'{passed}/{len(results)} Property edge checks passed');assert passed==len(results),[r for r in results if not r[1]]
