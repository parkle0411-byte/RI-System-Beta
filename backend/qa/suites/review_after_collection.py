"""2026-11-20 業主決定：所有再保人，Mark reviewed 前要先收齊「對應的那筆錢」，只看該再保人的份額：
付再保人的保費 T2 ← 該份額的 Cedant T1；退給 Cedant 的退費 ← 該份額的再保人退款；付給 Cedant 的理賠 ← 同一筆、同一再保人的理賠款。
付款前提不變（付再保人仍要該期 Cedant 全部收齊）。只在獨立測試資料庫執行，寫入最後整筆回復。
"""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.finance_workflow import REVIEW_PREREQUISITES

SWISS = 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)'
GA = 'Great American Insurance Company, Singapore Branch (Facility)'


def multi(ref, names_shares, value=1000, layout='per-reinsurer-v1'):
    c = fixture(ref, value)
    p = c.payload; p['premiumLedgerLayout'] = layout
    p['reinsurers'] = [{'name': n, 'sharePct': sh, 'premium': round(value * sh / 100, 2), 'riCommPct': 20, 'taxPct': 0, 'paymentTermsDays': 90} for n, sh in names_shares]
    p['transactions'] = transactions(p, '2026-09-01T00:00:00Z')
    c.payload = p; c.save(); return c
def tx(c, leg_type, index=None):
    return next(t['txNo'] for t in rows(c) if t['legType'] == leg_type and (index is None or t.get('reinsurerIdx') == index))
def amount(c, no): return abs(next(t['amount'] for t in rows(c) if t['txNo'] == no))
def collect(c, no):
    assert review([(c, no)]).status_code == 200, ('review', no)
    r = register([(c, no, amount(c, no), 0)], amount(c, no)); assert r.status_code == 200, (no, r.content)
def listing(): return accounting_get(fin, '?view=list').json()
def reason(c, no): return next(r for r in listing()['transactionRows'] if r['caseUid'] == str(c.case_uid) and r['txNo'] == no)['reviewBlockedReason']
def error(r): return r.json().get('error') if r.status_code >= 400 else None


class Done(Exception): pass
try:
    with transaction.atomic():
        fin = client('rc-fin', 'accounting'); rs = client('rc-rs', 'sales')
        PREMIUM, REFUND, CLAIM = (REVIEW_PREREQUISITES[k][0] for k in ('premium', 'refund', 'claim'))

        # ---- 一般再保人 ----
        o = fixture('QA-RC-O'); OT1, OT2 = leg(o, 'Leg 1'), leg(o, 'Leg 2')
        check('一般再保人：Cedant 未收，付再保人的 T2 不能審核', error(review([(o, OT2)])) == PREMIUM)
        check('清單標示原因', 'Cedant premium' in reason(o, OT2))
        check('Cedant 應收本身照常可以審核', reason(o, OT1) == '')
        collect(o, OT1)
        check('Cedant 收齊後可以審核 T2', review([(o, OT2)]).status_code == 200 and reason(o, OT2) == '')

        # ---- 兩家再保人：只看自己的份額 ----
        m = multi('QA-RC-M', [(SWISS, 55), (GA, 45)])
        S1, S2, G1, G2 = tx(m, 'Leg 1', 0), tx(m, 'Leg 2', 0), tx(m, 'Leg 1', 1), tx(m, 'Leg 2', 1)
        check('兩家都還不能審核 T2', error(review([(m, S2)])) == PREMIUM and error(review([(m, G2)])) == PREMIUM)
        collect(m, G1)
        check('只收到 Great American 份額：Great American 的 T2 可以審核', review([(m, G2)]).status_code == 200, )
        check('Swiss Re 份額未收：Swiss Re 的 T2 仍不能審核（Swiss Property 也只看自己的份額）', error(review([(m, S2)])) == PREMIUM)
        r = register([(m, G2, amount(m, G2), 0)], -amount(m, G2))   # 付款：合計為負
        check('付款前提不變：Swiss Re 份額未收前，Great American 的 T2 仍不能付款', r.status_code == 409 and 'Cedant installment' in r.json().get('message', ''), r.content)
        collect(m, S1)
        check('Swiss Re 份額收到後，Swiss Re 的 T2 可以審核', review([(m, S2)]).status_code == 200)

        # ---- Reinsurance Staff 也一樣 ----
        s = multi('QA-RC-S', [(SWISS, 100)]); SS2 = tx(s, 'Leg 2', 0)
        check('Reinsurance Staff 同樣要等 Cedant 收齊', error(review([(s, SS2)], rs)) == PREMIUM)

        # ---- 舊版面：Cedant T1 合併 → 看整期 ----
        g = multi('QA-RC-G', [(GA, 60), ('QA Other Re', 40)], layout='preserved')
        AT1 = next(t['txNo'] for t in rows(g) if t['legType'] == 'Leg 1'); AG2 = tx(g, 'Leg 2', 0)
        check('舊版面 Cedant 合併帳款：要等整期 Cedant 收齊', error(review([(g, AG2)])) == PREMIUM)
        collect(g, AT1)
        check('整期收齊後可以審核', review([(g, AG2)]).status_code == 200)

        # ---- 退保：退給 Cedant 要先收回再保人退款 ----
        root = fixture('QA-RC-ROOT')
        refund = fixture('QA-RC-RF', -1000); p = refund.payload   # 照 finance_facilities 的退保寫法：要有批改生效日與 Announce 日
        p.update(parentTwRef='QA-RC-ROOT', endoEffectiveDate='2026-09-01', endorsementAnnouncedAt='2026-09-01T00:00:00Z')
        p['transactions'] = transactions(p, '2026-09-01T00:00:00Z'); refund.payload = p; refund.save()
        RT1, RT2 = leg(refund, 'Leg 1'), leg(refund, 'Leg 2')
        check('退保：再保人退款未收，退給 Cedant 的那筆不能審核', error(review([(refund, RT1)])) == REFUND)
        check('清單標示原因', 'refund' in reason(refund, RT1))
        collect(refund, RT2)
        check('再保人退款收回後，可以審核退給 Cedant 的那筆', review([(refund, RT1)]).status_code == 200)

        # ---- 理賠：付給 Cedant 要先收到再保人的理賠款 ----
        k = fixture('QA-RC-K'); KT1, KT2 = add_claim(k, 300, 1)
        check('理賠：再保人理賠款未收，付給 Cedant 的理賠不能審核', error(review([(k, KT2)])) == CLAIM)
        assert review([(k, KT1)]).status_code == 200
        check('再保人先付一部分（100／300）', register([(k, KT1, 100, 0)], 100).status_code == 200)
        check('理賠收到一部分就可以審核付給 Cedant 的理賠', review([(k, KT2)]).status_code == 200)
        r = register([(k, KT2, 150, 0)], -150)
        check('付給 Cedant 仍不能超過已收（100）', r.status_code == 409 and r.json().get('error') == 'payment_dependency', r.content)
        check('已收範圍內可以先付給 Cedant（100）', register([(k, KT2, 100, 0)], -100).status_code == 200)
        raise Done()
except Done:
    pass
print(f'{len(checks)}/{len(checks)} passed（審核前先收齊對應款檢查全部通過；資料庫變更已回復）')
