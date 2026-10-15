"""Accounting 列表「同一件案件的付款排程與交易明細只算一次、三處共用」(CaseCompute) 必須和「各自重算」的結果完全相同。
2026-10-15 壓力測試後加入。只在拋棄式 QA 資料庫執行；所有變更在交易內回滾。"""
import copy, json, os
from datetime import datetime, timezone
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.accounting_views import _case_view, LEDGER_STATUSES
from cases.calc.accounting import build_premium_transactions
from cases.calc.jsnum import json_roundtrip, js_locale_key, js_locale_key_cached
from cases.ledger import ledger_rows
from cases.models import Case
from cases.shared_compute import CaseCompute
from cases.transaction_ledger import transaction_rows
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name); print('PASS ' + name)
def client(tag, role='accounting', dept='finance'):
    u = get_user_model().objects.create_user(username='zz.shared.' + tag, password='Shared-QA-Password-9!')
    Personnel.objects.create(name='ZZ Shared ' + tag, department=dept, role_code=role, auth_user_id=str(u.pk), account_status='active', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost'); c.force_login(u); return c
def make(ref, status='closed', n=1, drop=(), **over):
    shares = [round(100 / n, 2)] * (n - 1) + [round(100 - round(100 / n, 2) * (n - 1), 2)]
    p = {'twRef': ref, 'currency': 'TWD', 'statementNo': 'SOA-' + ref, 'reinsured': 'QA Cedant', 'policyFrom': '2026-09-01', 'policyTo': '2027-09-01',
         'paymentTermsDays': 30, 'originalPremium': 1000, 'riCommPct': 5, 'taxPct': 0, 'paymentEntries': [],
         'reinsurers': [{'name': f'QA RI {i + 1}', 'sharePct': shares[i], 'premium': 800, 'riCommPct': 0, 'taxPct': 0} for i in range(n)]}
    p.update(over)
    p['transactions'] = build_premium_transactions(p) if status in ('closed', 'reversed') else []
    for key in drop:
        p.pop(key, None)
    return Case.objects.create(tw_ref=ref, status=status, payload=p, currency='USD', reinsured_name_snapshot='Column Cedant',
                               created_by='qa', updated_by='qa')
def tx_no(case, leg, nth=0):
    return [t['txNo'] for t in case.payload['transactions'] if t['legType'] == leg][nth]
class Rollback(Exception): pass
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
try:
    with transaction.atomic():
        fin = client('fin')
        single, triple, posted, reversed_, paid = make('SC-1'), make('SC-3', n=3), make('SC-P', 'posted'), make('SC-R', 'reversed'), make('SC-PAID', n=2)
        no_keys = make('SC-NOKEYS', drop=('currency', 'reinsured'))       # payload 沒有 currency／reinsured：改用資料表欄位，兩種呼叫的輸入不同
        empty_ccy = make('SC-EMPTY', currency='', reinsured='')
        # 對其中一件記收款（走真正的 API）
        pay = fin.post('/api/accounting', data=json.dumps({'action': 'record_transaction_payments', 'paymentDate': '2026-10-07', 'amount': 400, 'reference': 'SC',
              'allocations': [{'caseUid': str(paid.case_uid), 'txNo': tx_no(paid, 'Leg 1'), 'rowVersion': Case.objects.get(pk=paid.pk).row_version, 'amount': 400}]}), content_type='application/json')
        check('fixture payment recorded through the API', pay.status_code == 200)
        # 一件有理賠交易的案件（理賠列在付款排程列裡會再讀一次交易明細）
        claim = make('SC-CLAIM')
        claim.payload['transactions'].append({'txNo': 'C1-SC', 'source': 'claim', 'legType': 'Claim Leg 1', 'reinsurer': 'QA RI 1', 'label': 'Claim', 'amount': 250, 'settlement': 'open'})
        claim.payload['paymentEntries'].append({'id': 'e1', 'entryType': 'payment', 'transactionNo': 'C1-SC', 'amount': 100, 'paymentDate': '2026-10-07', 'currency': 'TWD',
                                                'paymentDirection': 'receivable', 'partyName': 'QA Cedant', 'batchId': 'b1', 'batchAmount': 100})
        claim.save()
        cases = [single, triple, posted, reversed_, no_keys, empty_ccy, claim, Case.objects.get(pk=paid.pk)]

        shared_mismatch, same_flags = [], {}
        for case in cases:
            c = _case_view(Case.objects.get(pk=case.pk))
            memo = CaseCompute(c, NOW)
            same_flags[case.tw_ref] = memo.same
            shared = {c['caseUid']: memo}
            legacy_ledger = json_roundtrip(ledger_rows([c], NOW)) if c['status'] in LEDGER_STATUSES else None
            new_ledger = json_roundtrip(ledger_rows([c], NOW, shared)) if c['status'] in LEDGER_STATUSES else None
            legacy_tx = json_roundtrip(transaction_rows([c]))
            new_tx = json_roundtrip(transaction_rows([c], shared))
            if legacy_ledger != new_ledger or legacy_tx != new_tx:
                shared_mismatch.append(case.tw_ref)
        check('sharing is used when currency/reinsured are in the payload, and not when they are missing',
              same_flags['SC-1'] and same_flags['SC-3'] and same_flags['SC-PAID'] and not same_flags['SC-NOKEYS'] and not same_flags['SC-EMPTY'])
        check('shared computation gives exactly the same ledger and transaction rows as recomputing', not shared_mismatch)

        # 整個 API 回應 = 逐案用「不共用」的函式組出來的結果
        response = fin.get('/api/accounting').json()
        mine = {str(c.case_uid) for c in cases}
        expected_rows, expected_tx = [], []
        for case in sorted(cases, key=lambda x: x.tw_ref):
            c = _case_view(Case.objects.get(pk=case.pk))
            if c['status'] in LEDGER_STATUSES:
                expected_rows += ledger_rows([c])[0]
            expected_tx += transaction_rows([c])
        key = lambda r: (r['caseUid'], r['key'])
        got_tx = [r for r in response['transactionRows'] if r['caseUid'] in mine]
        got_rows = [r for r in response['rows'] if r['caseUid'] in mine]
        # 付款排程列另外補了對帳編號欄位；只比較原本就有的欄位
        slim = lambda rs: sorted(({k: v for k, v in r.items() if k not in ('statementNo', 'reconciliationRef', 'originalInsured', 'originalInsuredCn')} for r in json_roundtrip(rs)), key=key)
        check('GET /api/accounting transaction rows equal the unshared computation', sorted(json_roundtrip(expected_tx), key=key) == sorted(got_tx, key=key))
        check('GET /api/accounting schedule rows equal the unshared computation', slim(expected_rows) == slim([{k: v for k, v in r.items()} for r in got_rows]))
        check('every fixture case that has transactions is present in the response', {r['caseUid'] for r in got_tx} == {str(c.case_uid) for c in cases if Case.objects.get(pk=c.pk).payload['transactions']} and len(got_tx) == len(expected_tx))

        # 只讀路徑不得改到資料庫裡的案件內容
        fresh = {c.pk: copy.deepcopy(Case.objects.get(pk=c.pk).payload) for c in cases}
        fin.get('/api/accounting')
        check('reading Accounting does not change any stored case', all(Case.objects.get(pk=pk).payload == p for pk, p in fresh.items()))

        # 排序鍵快取：與未快取的排序鍵一致
        samples = ['', 'TWPAR2603001', 'twpar2603001', 'TW-É', '2026-10-15', 'ａｂｃ', '中文']
        check('cached sort key equals the uncached key', all(js_locale_key_cached(s) == js_locale_key(s) for s in samples))
        raise Rollback()
except Rollback:
    pass
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back')
