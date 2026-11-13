"""Accounting segmented loading (2026-11-13). Synthetic data in disposable MySQL only.

`?view=list&legacy=open` (everything except settled-before-import legacy history) plus
`?view=list&legacy=history` (only that history) must together equal `?view=list` exactly, the
parameter-less responses must be unchanged, and writes must stay visible in the open segment.
"""
import copy
from pathlib import Path
exec(Path('/app/qa/suites/legacy_entries.py').read_text().replace("print(f'{len(checks)}/{len(checks)} passed')",'pass'))
from django.db import connections
import legacy.ledger as L
from legacy.models import ImportBatch

owner=copy.deepcopy(connections.databases['default'])
owner.update(USER='ri_app',PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['segments_owner']=owner
O=LegacyTransaction.objects.using('segments_owner')
batch=ImportBatch.objects.using('segments_owner').create(filename='synthetic-segments.xlsx',sha256='d'*64,
    storage_key='qa/synthetic-segments.xlsx',status='imported',created_by='isolated-qa')

def history(n,currency='TWD',receipts=True):
    """A row settled on both sides before import, with its display receipts (as the web import stores them)."""
    uid=uuid.uuid4();number=f'QA-SEG-{n}'
    data=dict(reference=f'QA-SEG-REF-{n}',currency=currency,insured=f'Segment Insured {n}',insuredCn='分段載入測試',
        cedant='Segment Cedant',party='Segment Reinsurer',ae='Entry sales',statementNo=f'SEG-ST-{n}',gross=10000,share=100,
        rule='ordinary',kind='premium',effectiveDate='2024-01-01',expiryDate='2024-12-31',receiveReminder='2024-03-15',payReminder='2024-04-15',
        amounts=dict(premium=10000+n,commission=0,tax=0,brokerage=500,claim=0,cedantNet=10000+n,reinsurerNet=9500+n))
    entries=[dict(id=str(uuid.uuid4()),entryType='payment',transactionNo=f'{number}-T{leg}',scheduleKey='single:'+key,partyType=typ,partyName=name,
        paymentDirection=side,currency=currency,amount=amount_,nonCash=False,entryKind='legacy-import',batchId=f'legacy-import:{uid}:{number}-T{leg}',
        importBatchId=str(batch.pk),paymentDate='2024-03-15',reference=f'REC-{n}-{leg}',note='Imported',createdAt=timezone.now().isoformat(),
        createdBy='qa',createdByName='QA') for leg,key,typ,name,side,amount_ in
        ((1,'cedant','cedant','Segment Cedant','receivable',10000+n),(2,'r1','reinsurer','Segment Reinsurer','payable',9500+n))] if receipts else []
    return O.create(uid=uid,number=number,original_serial=number,reference=f'QA-SEG-REF-{n}',currency=currency,revenue_month='2024-01',
        status='confirmed',historical=True,batch=batch,first_confirmed_at=timezone.now(),data=data,fx_snapshot=dict(rate=1),
        financial={'paymentEntries':entries} if entries else {})

fin=clients['accounting'];admin=clients['admin']
def get(q='?view=list',client=admin):
    r=client.get('/api/accounting'+q); assert r.status_code==200,(q,r.status_code,r.content[:300]); return r
def body(q): return get(q).json()
def finance(payload,want=200):
    r=fin.post('/api/accounting',json.dumps(payload),content_type='application/json')
    check('Finance '+payload['action']+' '+str(want),r.status_code==want,r.content[:500]); return r.json()
def by(rows,key): return {r[key]:r for r in rows}
def merged_equals_full(label):
    full,open_,hist=body('?view=list'),body('?view=list&legacy=open'),body('?view=list&legacy=history')
    f_rows,o_rows,h_rows=by(full['transactionRows'],'key'),by(open_['transactionRows'],'key'),by(hist['transactionRows'],'key')
    check(label+': no account appears in both segments',not set(o_rows)&set(h_rows) and len(o_rows)==len(open_['transactionRows']) and len(h_rows)==len(hist['transactionRows']))
    check(label+': open + history accounts equal the full list exactly',{**o_rows,**h_rows}==f_rows,(len(o_rows),len(h_rows),len(f_rows)))
    check(label+': history holds only settled-before-import rows and open holds none of them',
          all(r.get('legacyHistorical') for r in h_rows.values()) and not any(r.get('legacyHistorical') for r in o_rows.values()))
    f_b,o_b,h_b=by(full['cashBatches'],'batchId'),by(open_['cashBatches'],'batchId'),by(hist['cashBatches'],'batchId')
    check(label+': open + history registrations equal the full list exactly',not set(o_b)&set(h_b) and {**o_b,**h_b}==f_b,(len(o_b),len(h_b),len(f_b)))
    check(label+': correction histories and currencies combine to the full response',
          {**open_['caseHistories'],**hist['caseHistories']}==full['caseHistories'] and sorted(set(open_['currencies'])|set(hist['currencies']))==sorted(full['currencies']))
    for key in ('rows','warnings','scope','reviewBatches','swissRows','scheduleRows'):
        check(f'{label}: {key} is identical in the open segment',open_[key]==full[key])
    check(label+': history segment carries only its own keys',set(hist)=={'ok','transactionRows','currencies','caseHistories','cashBatches','legacyHistory'})
    check(label+': segment counters are correct',open_['legacyHistory']=={'scope':'open','pendingTransactions':len({r['legacyTransactionId'] for r in h_rows.values()})}
          and hist['legacyHistory']=={'scope':'history','transactions':len({r['legacyTransactionId'] for r in h_rows.values()})},(open_['legacyHistory'],hist['legacyHistory']))
    return full,open_,hist

saved_flag=os.environ.get('RI_LEGACY_RESULT_CACHE')
try:
    L._CACHE.clear()
    plain_before=(get('?view=list').content,get('').content)
    # No history yet: the open segment is the whole list and nothing is pending.
    # The shared fixture already holds H0 settled source rows (three legs each, no receipts).
    pol=make_source('SEG-SRC',effectiveDate='2025-01-01',expiryDate='2025-12-31')   # own source for this suite's endorsement and claim
    H0=L.historical_queryset().count()
    o=body('?view=list&legacy=open');h=body('?view=list&legacy=history')
    check('before adding history the counters match the fixture and no receipts exist',
          o['legacyHistory']=={'scope':'open','pendingTransactions':H0} and len(h['transactionRows'])==3*H0 and h['cashBatches']==[])
    O.filter(historical=True).update(status='withdrawn');L._CACHE.clear()
    o=body('?view=list&legacy=open');h=body('?view=list&legacy=history')
    check('without history the open segment reports nothing pending and history is empty',
          o['legacyHistory']=={'scope':'open','pendingTransactions':0} and h['transactionRows']==[] and h['cashBatches']==[]
          and by(o['transactionRows'],'key')==by(body('?view=list')['transactionRows'],'key'))
    O.filter(historical=True).update(status='confirmed');L._CACHE.clear()

    hist_rows=[history(1),history(2,currency='USD'),history(3,receipts=False)]
    e=create(src=pol);e=save(e,dict(gross=400,commissionRate=0,taxRate=0,brokerage=10,endorsementNo='E-SEG',effectiveDate='2025-03-01'));e=confirm(e)
    c=create('claim',src=pol);c=save(c,dict(claim=300,lossDate='2025-04-01',lossNo='L-SEG',causeOfLoss='Fire'));c=confirm(c)
    full,open_,hist=merged_equals_full('mixed data')
    check('history segment contains the settled rows (three legs each) and their four receipts',len(hist['transactionRows'])==3*(3+H0) and len(hist['cashBatches'])==4)
    check('new legacy endorsement and claim stay in the open segment',{e['uid'],c['uid']}<={r.get('legacyTransactionId') for r in open_['transactionRows']})
    check('USD appears only through the history segment',('USD' in hist['currencies'])==('USD' in full['currencies']))

    for flag in ('false','true'):
        os.environ['RI_LEGACY_RESULT_CACHE']=flag; L._CACHE.clear()
        merged_equals_full('cache '+('off' if flag=='false' else 'on'))
        if flag=='true': merged_equals_full('cache on, second read')
    if saved_flag is None: os.environ.pop('RI_LEGACY_RESULT_CACHE',None)
    else: os.environ['RI_LEGACY_RESULT_CACHE']=saved_flag

    # Parameter-less and unknown-parameter requests are unchanged.
    check('unknown legacy value behaves as the full list',get('?view=list&legacy=zzz').content==get('?view=list').content)
    check('legacy parameter is ignored without view=list',get('?legacy=open').content==get('').content and get('?legacy=history').content==get('').content)
    check('full responses carry no segment marker','legacyHistory' not in body('?view=list') and 'legacyHistory' not in body(''))

    # Writes show at once in the open segment; history is unaffected.
    obj=LegacyTransaction.objects.get(pk=e['uid'])
    member=dict(caseUid=str(obj.uid),rowVersion=obj.version,txNo=obj.number+'-T1')
    before_hist=get('?view=list&legacy=history').content
    finance(dict(action='review_accounts',date='2026-11-13',members=[member]))
    row=[r for r in body('?view=list&legacy=open')['transactionRows'] if r.get('txNo')==member['txNo']][0]
    check('a review is visible at once in the open segment',row['financeReviewed'] is True)
    obj.refresh_from_db()
    finance(dict(action='record_transaction_payments',cashSubmissionId=str(uuid.uuid4()),paymentDate='2026-11-13',reference='SEG-CASH',
        allocations=[dict(cashItemId=str(uuid.uuid4()),caseUid=str(obj.uid),txNo=member['txNo'],cashAmount=50,rowVersion=obj.version)]))
    after=body('?view=list&legacy=open')
    row=[r for r in after['transactionRows'] if r.get('txNo')==member['txNo']][0]
    check('a receipt is visible at once in the open segment',row['paid']==50 and any(b['reference']=='SEG-CASH' for b in after['cashBatches']))
    check('writes on open accounts do not change the history segment',get('?view=list&legacy=history').content==before_hist)
    merged_equals_full('after review and cash')

    # A history row leaving / entering the scope moves between segments consistently.
    O.filter(pk=hist_rows[2].pk).update(status='withdrawn'); L._CACHE.clear()
    full,open_,hist=merged_equals_full('one history row withdrawn')
    check('withdrawn history row is gone from both segments',len(hist['transactionRows'])==3*(2+H0) and open_['legacyHistory']['pendingTransactions']==2+H0)

    # Permissions are those of Accounting itself.
    for role,want in (('accounting',200),('sales',200),('viewer',403)):
        for q in ('?view=list&legacy=open','?view=list&legacy=history'):
            check(f'{role} {q} -> {want}',clients[role].get('/api/accounting'+q).status_code==want)
    check('non-Finance users cannot edit through a segment',body('?view=list&legacy=open')['scope']['canEdit'] is True
          and clients['sales'].get('/api/accounting?view=list&legacy=open').json()['scope']['canEdit'] is False)
finally:
    L._CACHE.clear()
    if saved_flag is None: os.environ.pop('RI_LEGACY_RESULT_CACHE',None)
    else: os.environ['RI_LEGACY_RESULT_CACHE']=saved_flag
print(f'{len(checks)}/{len(checks)} passed')
