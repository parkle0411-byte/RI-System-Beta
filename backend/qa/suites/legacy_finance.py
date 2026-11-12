"""Real shared Finance workflow on new standalone obligations, no dummy Cases."""
from pathlib import Path
exec(Path('/app/qa/suites/legacy_entries.py').read_text().replace("print(f'{len(checks)}/{len(checks)} passed')",'pass'))
fin=clients['accounting'];admin=clients['admin']
def finance(body,want=200):
    r=fin.post('/api/accounting',json.dumps(body),content_type='application/json')
    check('Finance '+body['action']+' '+str(want),r.status_code==want,r.content[:1200]);return r.json()
def member(t,leg):
    obj=LegacyTransaction.objects.get(pk=t['uid'])
    return dict(caseUid=str(obj.uid),rowVersion=obj.version,txNo=obj.number+('-C1-T' if obj.data['kind']=='claim' else '-T')+str(leg))
def review(t,leg):return finance(dict(action='review_accounts',date='2026-11-09',members=[member(t,leg)]))
def pay(t,leg,cash,net,want=200,**extra):
    return finance(dict(action='record_transaction_payments',paymentDate='2026-11-09',reference='QA-LEG-CASH',amount=net,
                        allocations=[dict(**member(t,leg),cashAmount=cash,offsetAmount=0)],**extra),want)
def reverse(t,bid,want=200):
    m=member(t,1)
    return finance(dict(action='reverse_batch_payment',batchId=bid,paymentDate='2026-11-09',note='QA correction',cases=[dict(caseUid=m['caseUid'],rowVersion=m['rowVersion'])]),want)
def claim(value):
    t=create('claim');t=save(t,dict(claim=value,lossDate='2020-04-01',lossNo='LOSS-FIN',claimReason='Overpayment refund' if value<0 else ''));return confirm(t)
t=claim(1000)
pay(t,1,100,100,409)
review(t,1);review(t,2)
pay(t,2,50,-50,409)
r=pay(t,1,100,100)
p=pay(t,2,60,-60)
reverse(t,r['batchId'],409)
reverse(t,p['batchId']);reverse(t,r['batchId'])
pay(t,1,100,100,replacementOfBatchId=r['batchId'])
negative=claim(-500)
review(negative,1);review(negative,2)
pay(negative,1,20,-20,409)
pay(negative,2,200,200)
pay(negative,1,200,-200)
record=LegacyTransaction.objects.get(pk=negative['uid'])
check('negative claim persists signed receipts/payments',all(e['amount']<0 for e in record.financial['paymentEntries']))
# Refund/premium dependency and full-amount restrictions use the original-currency ledger.
e=create();e=save(e,dict(gross=400,commissionRate=0,taxRate=0,brokerage=10,effectiveDate='2020-07-01',endorsementNo='E-FIN',oldReason='late_entry'));e=confirm(e)
review(e,1);review(e,2)
pay(e,2,90,-90,409)
pay(e,1,50,50)
pay(e,2,1,-1,409)
pay(e,1,50,50)
pay(e,2,90,-90)
rows=admin.get('/api/accounting?view=list').json()['transactionRows']
ours=[r for r in rows if r.get('caseUid')==e['uid']]
check('premium and brokerage automatically settle',len(ours)==3 and all(r['settlement']=='settled' and r['outstanding']==0 for r in ours),ours)
check('historical source remains settled with no bank events',LegacyTransaction.objects.get(pk=source.pk).financial=={})
check('Finance adapter never creates dummy Cases',Case.objects.count()==cases)

# A brokerage-only adjustment needs no fabricated zero-value cash receipt.
zero=create();zero=save(zero,dict(gross=0,commissionRate=0,taxRate=0,brokerage=-10,brokerageNote='Commission expense',
    effectiveDate='2020-07-01',endorsementNo='E-ZERO',oldReason='late_entry'));zero=confirm(zero)
review(zero,2);pay(zero,2,10,-10)
check('brokerage-only expense creates no Cedant bank receipt',len(LegacyTransaction.objects.get(pk=zero['uid']).financial['paymentEntries'])==1)
# Swiss also needs its independent statement; its zero Cedant leg is automatically complete.
swiss_name='Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
# 2026-11-12: the settlement party and payment rule follow the source, so Swiss scenarios use a Swiss source.
swsrc=make_source('SW-REF',party=swiss_name,rule='swiss')
sw=create(src=swsrc);check('Swiss rule detected from the source party',sw['data']['rule']=='swiss' and sw['data']['cedantDays']==90,sw['data'])
sw=save(sw,dict(gross=0,commissionRate=0,taxRate=0,brokerage=-10,
    brokerageNote='Swiss commission expense',effectiveDate='2020-07-01',endorsementNo='E-SW-ZERO',oldReason='late_entry'));sw=confirm(sw)
review(sw,2);pay(sw,2,10,-10,409)
obj=LegacyTransaction.objects.get(pk=sw['uid'])
finance(dict(action='mark_swiss_statement',caseUid=sw['uid'],rowVersion=obj.version,scheduleKey='single:r1',reference='SWRPA-QA-ZERO'))
pay(sw,2,10,-10)
check('zero-premium Swiss records only the actual payment',len(LegacyTransaction.objects.get(pk=sw['uid']).financial['paymentEntries'])==1)
# One remittance may offset a native receivable against a recovered Legacy claim.
import ast
from cases.property_original import transactions
native_test=ast.parse(Path('/app/qa/suites/finance_workflow.py').read_text())
fixture_node=next(n for n in native_test.body if isinstance(n,ast.FunctionDef) and n.name=='fixture')
exec(compile(ast.Module(body=[fixture_node],type_ignores=[]),'<native-fixture>','exec'))
native=fixture('NATIVE-MIXED',value=100,currency='TWD',party='Test cedant')
native_no=next(tx['txNo'] for tx in native.payload['transactions'] if tx['legType']=='Leg 1')
def nm():
    native.refresh_from_db();return dict(caseUid=str(native.case_uid),txNo=native_no,rowVersion=native.row_version)
mixed=claim(300);review(mixed,1);pay(mixed,1,300,300);review(mixed,2)
finance(dict(action='review_accounts',date='2026-11-09',members=[nm()]))
# Offsets are retired across native and Legacy accounts as well.
finance(dict(action='record_transaction_payments',paymentDate='2026-11-09',reference='MIXED-NET',amount=-200,
    allocations=[dict(**nm(),cashAmount=0,offsetAmount=100),dict(**member(mixed,2),cashAmount=200,offsetAmount=100)]),400)
cash_request=dict(action='record_transaction_payments',cashSubmissionId=str(uuid.uuid4()),paymentDate='2026-11-09',reference='MIXED-ACTUAL',
    allocations=[dict(**nm(),cashAmount=100,cashItemId=str(uuid.uuid4())),dict(**member(mixed,2),cashAmount=300,cashItemId=str(uuid.uuid4()))])
combined=finance(cash_request)
replayed=finance(cash_request)
check('native and Legacy retry keys replay without a second bank entry',replayed['newlyRecorded']==0 and all(r.get('replayed') for r in replayed['results']),replayed)
check('native and Legacy opposite directions create independent real registrations',combined['succeeded']==2 and len({r['batchId'] for r in combined['results']})==2,combined)
reverse(mixed,combined['results'][1]['batchId'])
native.refresh_from_db()
finance(dict(action='reverse_batch_payment',batchId=combined['results'][0]['batchId'],paymentDate='2026-11-09',note='Native correction',
    cases=[dict(caseUid=str(native.case_uid),rowVersion=native.row_version)]))
check('only the explicitly seeded native fixture exists',Case.objects.count()==cases+1)
# A normal Case JSON body must never impersonate the internal Legacy adapter.
import copy
from legacy.ledger import payload_for
from legacy.protocol import is_legacy_payload
from cases.cash_ledger import transaction_details
fresh=claim(123);internal=payload_for(LegacyTransaction.objects.get(pk=fresh['uid']))
forged=json.loads(json.dumps(internal));forged['legacyHistorical']=True
check('deep-copy retains trusted protocol',is_legacy_payload(copy.deepcopy(internal)))
check('JSON cannot manufacture trusted protocol',not is_legacy_payload(forged))
raw_details=transaction_details(forged)
check('forged historical marker does not settle native accounts',any(abs(d['outstanding'])==123 for d in raw_details.values()),raw_details)
# Native and new Legacy Swiss obligations use the same settlement identity.
swr_native=fixture('NATIVE-SWISS-MIX',value=100,currency='TWD',party='Test cedant')
p=swr_native.payload;p['reinsurers'][0]['name']=swiss_name
p['transactions']=transactions(p,p['announcedAt']);Case.objects.filter(pk=swr_native.pk).update(payload=p)
def swr_member(leg):
    swr_native.refresh_from_db()
    no=next(tx['txNo'] for tx in swr_native.payload['transactions'] if tx['legType']=='Leg '+str(leg))
    return dict(caseUid=str(swr_native.case_uid),rowVersion=swr_native.row_version,txNo=no)
finance(dict(action='review_accounts',date='2026-11-09',members=[swr_member(1)]))
finance(dict(action='record_transaction_payments',paymentDate='2026-11-09',reference='NATIVE-SW-CEDANT',amount=100,
    allocations=[dict(**swr_member(1),cashAmount=100,offsetAmount=0)]))
from cases.calc.payment_terms import build_payment_schedule
swr_native.refresh_from_db();native_ri_key=next(row['scheduleKey'] for row in build_payment_schedule(swr_native.payload)['items'] if row['partyType']=='reinsurer')
finance(dict(action='mark_swiss_statement',**{k:v for k,v in swr_member(2).items() if k!='txNo'},scheduleKey=native_ri_key,reference='SWRPA-MIXED-NATIVE'))
finance(dict(action='review_accounts',date='2026-11-09',members=[swr_member(2)]))
swc=create('claim',src=swsrc);swc=save(swc,dict(claim=80,lossDate='2020-04-01',lossNo='LOSS-SW',reinsurerRef='SWISS-CLAIM-REF'));swc=confirm(swc)
review(swc,1)
finance(dict(action='record_transaction_payments',paymentDate='2026-11-09',reference='NATIVE-LEGACY-SWISS-OFFSET',amount=0,
    allocations=[dict(**swr_member(2),cashAmount=0,offsetAmount=80),dict(**member(swc,1),cashAmount=0,offsetAmount=80)]),400)
response=finance(dict(action='record_transaction_payments',cashSubmissionId=str(uuid.uuid4()),paymentDate='2026-11-09',reference='NATIVE-LEGACY-SWISS-CASH',
    allocations=[dict(**swr_member(2),cashAmount=80,cashItemId=str(uuid.uuid4())),dict(**member(swc,1),cashAmount=80,cashItemId=str(uuid.uuid4()))]))
check('same Swiss counterparty supports native/Legacy separate actual cash',response['succeeded']==2,response)
account_rows=admin.get('/api/accounting?view=list').json()['transactionRows']
claim_ri=next(row for row in account_rows if row.get('caseUid')==swc['uid'] and row['legType']=='Claim Leg 1')
check('same Swiss counterparty preserves settlement identity',claim_ri['partyName']=='Swiss Re Asia Pte. Ltd., Hong Kong Branch' and claim_ri['settlement']=='settled',claim_ri)
check('new RI statement references reach Accounting',claim_ri['reconciliationRef']=='SWISS-CLAIM-REF')
check('original MDM Facility name is retained',LegacyTransaction.objects.get(pk=swc['uid']).data['party']==swiss_name)
# A broker in MDM may settle a Facility; its name does not imply ordinary terms.
from masterdata.models import MasterRecord
MasterRecord.objects.create(entity_type='foreign_broker',name='QA Facility Broker',created_by='qa',updated_by='qa')
bsrc=make_source('BROKER-REF',party='QA Facility Broker')
broker=create(src=bsrc)
code,r=send(clients['sales'],dict(id=broker['uid'],version=broker['version'],action='save',data={'rule':'auw'}))
check('payment rule cannot be chosen by hand (2026-11-12)',code==400,r)
broker=save(broker,dict(gross=400,commissionRate=0,taxRate=0,brokerage=10,effectiveDate='2020-07-01',endorsementNo='E-BROKER',oldReason='late_entry'));broker=confirm(broker)
check('a broker name that is not a Facility uses the ordinary rule',broker['data']['rule']=='ordinary')
print(f'{len(checks)}/{len(checks)} passed')
