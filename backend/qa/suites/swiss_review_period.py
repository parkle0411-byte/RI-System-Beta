"""2026-11-19 業主決定：Swiss Property 付 Swiss Re 的保費 T2，結算期改由這筆 T2 的對帳日（Mark reviewed 的
Review date）決定。截止＝結算日前 7 天（當天也算），截止前沒對帳自動延一季；Cedant 該期全額收現前不能對帳；
取消審核後依新的對帳日重算。退保應收、理賠、Swiss CGL 不適用。只在獨立測試資料庫執行，寫入最後整筆回復。
"""
from pathlib import Path
from datetime import datetime
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.calc.swiss_facility import review_period, settlement_on_or_after, SWISS_NAME
from cases.calc.payment_terms import build_payment_schedule
from cases.finance_workflow import swiss_premium_t2

# ---- 對照表 ----
for day, period in [('2027-02-07', '2027-02-14'), ('2027-02-08', '2027-05-14'), ('2027-05-07', '2027-05-14'), ('2027-05-08', '2027-08-14'),
                    ('2027-08-07', '2027-08-14'), ('2027-11-07', '2027-11-14'), ('2027-11-08', '2028-02-14'), ('2026-12-20', '2027-02-14')]:
    check(f'對帳日 {day} → 結算期 {period}（截止＝結算日前 7 天，當天也算）', review_period(day) == period, review_period(day))
check('當天或之後的第一個結算日', settlement_on_or_after('2027-02-14') == '2027-02-14' and settlement_on_or_after('2027-02-15') == '2027-05-14')


def swiss_case(ref, value=1000, klass='Property'):
    c = fixture(ref, value)
    p = c.payload; p['reinsurers'][0]['name'] = SWISS_NAME; p['classOfBusiness'] = klass
    p['transactions'] = transactions(p, '2026-09-01T00:00:00Z')
    c.payload = p; c.save(); return c
def swiss_row(c, when):
    c.refresh_from_db()
    return next(i for i in build_payment_schedule(c.payload, datetime.fromisoformat(when + 'T04:00:00+00:00'))['items'] if i['partyType'] == 'reinsurer')
def listing(who): return accounting_get(who, '?view=list').json()
def row_of(body, case, no): return next(r for r in body['transactionRows'] if r['caseUid'] == str(case.case_uid) and r['txNo'] == no)


class Done(Exception): pass
try:
    with transaction.atomic():
        fin = client('sp-fin', 'accounting'); rs = client('sp-rs', 'sales')
        a = swiss_case('QA-SP-A'); T1, T2 = leg(a, 'Leg 1'), leg(a, 'Leg 2')   # 保單 2026-09-01 生效：B＋90＝11-30 → 原始期 2027-02-14

        # ---- 尚未對帳：預計期隨今天往後移 ----
        r = swiss_row(a, '2026-11-19'); check('未對帳：預計 2027-02-14，截止 02-07', r['dueDate'] == '2027-02-14' and r['projectedDueDate'] == '2027-02-14' and r['confirmationCutoff'] == '2027-02-07', r)
        r = swiss_row(a, '2027-02-08'); check('過了 02-07 還沒對帳 → 自動延到 05-14', r['dueDate'] == '2027-05-14' and r['contractDueDate'] == '2027-05-14' and r['confirmationCutoff'] == '2027-05-07', r)
        r = swiss_row(a, '2027-05-08'); check('再過 05-07 還沒對帳 → 再延到 08-14（未對帳不會逾期）', r['dueDate'] == '2027-08-14' and r['status'] != 'overdue', r)

        # ---- Cedant 收齊前不能對帳 ----
        body = listing(fin)
        check('清單標示：Cedant 未收齊，Swiss T2 不能對帳', 'Cedant premium' in row_of(body, a, T2)['reviewBlockedReason'])
        r = review([(a, T2)], fin, date='2027-02-07'); check('Finance 也不能在 Cedant 收齊前審核 Swiss T2', r.status_code == 409 and r.json()['error'] == 'cedant_collection_required', r.content)
        r = review([(a, T2)], rs, date='2027-02-07'); check('Reinsurance Staff 同樣不能', r.status_code == 409 and r.json()['error'] == 'cedant_collection_required', r.content)
        amount = next(t['amount'] for t in rows(a) if t['txNo'] == T1)
        check('Cedant 先對帳', review([(a, T1)]).status_code == 200)
        check('Cedant 全額收現', register([(a, T1, amount, 0)], amount).status_code == 200)
        check('收齊後清單不再標示不能對帳', row_of(listing(fin), a, T2)['reviewBlockedReason'] == '')

        # ---- 截止前對帳 → 留在 02-14；之後未付就逾期 ----
        r = review([(a, T2)], rs, date='2027-02-07'); check('截止日當天（02-07）對帳', r.status_code == 200, r.content)
        a.refresh_from_db(); check('案件資料記下這筆 T2 的對帳日', a.payload['swissAccounting']['t2ReviewDates'] == {T2: '2027-02-07'}, a.payload.get('swissAccounting'))
        r = swiss_row(a, '2027-02-10'); check('已對帳：期別固定在 02-14，不再是預計期', r['dueDate'] == '2027-02-14' and not r['projectedDueDate'] and r['swissReviewDate'] == '2027-02-07', r)
        r = swiss_row(a, '2027-02-15'); check('過了結算日沒付 → 逾期', r['status'] == 'overdue', r)

        # ---- 取消審核 → 依新的對帳日重算 ----
        bid = row_of(listing(fin), a, T2)['reviewBatchId']
        r = api(rs, {'action': 'cancel_review_batch', 'reviewBatchId': bid, 'scope': 'account', 'members': [member(a, T2)], 'reason': 'QA period re-check'})
        check('取消這筆審核', r.status_code == 200, r.content)
        a.refresh_from_db(); check('取消後移除對帳日', 't2ReviewDates' not in (a.payload.get('swissAccounting') or {}), a.payload.get('swissAccounting'))
        r = swiss_row(a, '2027-02-10'); check('取消後（已過 02-07）→ 延到 05-14 的預計期', r['dueDate'] == '2027-05-14' and r['projectedDueDate'] == '2027-05-14', r)
        r = review([(a, T2)], rs, date='2027-02-08'); check('02-08 重新對帳', r.status_code == 200, r.content)
        r = swiss_row(a, '2027-02-10'); check('Review date 02-08 → 05-14', r['dueDate'] == '2027-05-14' and not r['projectedDueDate'], r)
        bid = row_of(listing(fin), a, T2)['reviewBatchId']
        g = next(x for x in listing(fin)['reviewBatches'] if x['id'] == bid)
        r = api(fin, {'action': 'cancel_review_batch', 'reviewBatchId': bid, 'reason': 'QA whole batch', 'members': [{k: m[k] for k in ('caseUid', 'txNo', 'rowVersion')} for m in g['members']]})
        check('Finance 整批取消也會移除對帳日', r.status_code == 200 and 't2ReviewDates' not in (a.refresh_from_db() or a.payload.get('swissAccounting') or {}), r.content)
        r = review([(a, T2)], fin, date='2026-12-01'); check('比原始期早的 Review date', r.status_code == 200, r.content)
        r = swiss_row(a, '2026-12-05'); check('期別不會早於原始期（仍是 02-14）', r['dueDate'] == '2027-02-14', r)

        # ---- 不適用的帳款 ----
        refund = swiss_case('QA-SP-R', -1000)
        check('退保應收（向 Swiss Re 收回）不適用', swiss_premium_t2(refund.payload, leg(refund, 'Leg 2')) is None)
        cgl = swiss_case('QA-SP-G', klass='Commercial General Liability')
        check('Swiss CGL QS 不適用', swiss_premium_t2(cgl.payload, leg(cgl, 'Leg 2')) is None)
        o = fixture('QA-SP-O'); OT1 = leg(o, 'Leg 1')
        check('一般再保人不適用', swiss_premium_t2(o.payload, leg(o, 'Leg 2')) is None)
        check('非 Swiss 案件審核', review([(o, OT1)]).status_code == 200)
        g = next(x for x in listing(fin)['reviewBatches'] if x['id'] == row_of(listing(fin), o, OT1)['reviewBatchId'])
        before = set(o.payload); api(fin, {'action': 'cancel_review_batch', 'reviewBatchId': g['id'], 'reason': 'QA', 'members': [{k: m[k] for k in ('caseUid', 'txNo', 'rowVersion')} for m in g['members']]})
        o.refresh_from_db(); check('非 Swiss 案件審核與取消不會多出 swissAccounting 欄位', 'swissAccounting' not in o.payload or 'swissAccounting' in before, sorted(set(o.payload) - before))
        raise Done()
except Done:
    pass
print(f'{len(checks)}/{len(checks)} passed（Swiss Property 結算期依對帳日檢查全部通過；資料庫變更已回復）')
