"""2026-11-19 業主決定：Reinsurance Staff 可 Mark reviewed「對象是 Swiss Re Asia／Allianz（Facility）」的帳款
（應付與應收：保費、退保保費、理賠款；同日稍晚擴大到應收），
不能登錄收付款，只能取消自己做的審核；取消時可選「只取消這一筆」或「取消整批」（Finance 也可以選）。
只在獨立測試資料庫執行，所有寫入最後整筆回復。
"""
from pathlib import Path
exec(Path('/app/qa/suites/finance_workflow.py').read_text().split('class Done(Exception):')[0])
from cases.finance_workflow import facility_account, FACILITY_REVIEW_REINSURERS
from legacy.ledger import RULE_NAMES
SWISS, ALLIANZ = FACILITY_REVIEW_REINSURERS


def facility_case(ref, name, value=1000):
    c = fixture(ref, value)
    p = c.payload; p['reinsurers'][0]['name'] = name
    p['transactions'] = transactions(p, '2026-09-01T00:00:00Z')
    c.payload = p; c.save(); return c
def cancel_scope(who, bid, scope, members, reason='QA review correction'):
    return api(who, {'action': 'cancel_review_batch', 'reviewBatchId': bid, 'scope': scope, 'members': members, 'reason': reason})
def listing(who): return accounting_get(who, '?view=list').json()
def row_of(body, case, no): return next(r for r in body['transactionRows'] if r['caseUid'] == str(case.case_uid) and r['txNo'] == no)
def reviewed(case, no): return row_of(listing(fin), case, no)['financeReviewed']
def batch_id(case, no): return row_of(listing(fin), case, no)['reviewBatchId']


class Done(Exception): pass
try:
    with transaction.atomic():
        fin = client('fr-fin', 'accounting'); rs = client('fr-rs', 'sales'); rs2 = client('fr-rs2', 'sales'); gm = client('fr-gm', 'general_manager')
        a = facility_case('QA-FR-A', SWISS); b = facility_case('QA-FR-B', SWISS); c3 = facility_case('QA-FR-C', SWISS)
        c4 = facility_case('QA-FR-D', SWISS); z = facility_case('QA-FR-Z', ALLIANZ); o = fixture('QA-FR-O')   # o：一般再保人
        A, B, C, D, Z, O = (leg(x, 'Leg 2') for x in (a, b, c3, c4, z, o))
        # 2026-11-19／20：付再保人的保費 T2 要等 Cedant 收齊才能對帳 → Finance 先收齊這幾件
        for x in (a, b, c3, c4, z):   # 2026-11-20：所有再保人的保費 T2 都要先收齊該份額的 Cedant 款
            t1 = leg(x, 'Leg 1'); amt = next(t['amount'] for t in rows(x) if t['txNo'] == t1)
            assert review([(x, t1)]).status_code == 200 and register([(x, t1, amt, 0)], amt).status_code == 200, x.tw_ref

        # ---- 清單旗標 ----
        body = listing(rs)
        check('Reinsurance Staff：有 Facility 應付審核權，沒有 Finance 編輯權', body['scope']['canReviewFacilityAccounts'] is True and body['scope']['canEdit'] is False, body['scope'])
        check('對象是這兩家的帳款才標為可審核（Swiss Re、Allianz 的 T2；Cedant T1、一般再保人不算）',
              row_of(body, a, A)['facilityReviewable'] and row_of(body, z, Z)['facilityReviewable']
              and not row_of(body, o, leg(o, 'Leg 1'))['facilityReviewable'] and not row_of(body, o, O)['facilityReviewable'])
        check('General Manager 沒有這個權限', listing(gm)['scope']['canReviewFacilityAccounts'] is False)
        check('Finance 照舊可編輯', listing(fin)['scope']['canEdit'] is True)

        # ---- Mark reviewed 權限 ----
        r = review([(o, leg(o, 'Leg 1'))], rs); check('Reinsurance Staff 不能審核 Cedant 應收（T1）', r.status_code == 403, r.content)
        r = review([(o, O)], rs); check('Reinsurance Staff 不能審核應付給其他再保人的帳款', r.status_code == 403, r.content)
        r = review([(a, A)], gm); check('General Manager 不能審核', r.status_code == 403, r.content)
        r = review([(a, A)], rs); check('Reinsurance Staff 可審核應付給 Swiss Re（Facility）的帳款', r.status_code == 200, r.content)
        r = review([(b, B)], rs2); check('另一位 Reinsurance Staff 審核第二筆 Swiss Re 應付', r.status_code == 200, r.content)
        r = review([(c3, C), (c4, D)]); check('Finance 一次審核兩筆 Swiss Re 應付', r.status_code == 200, r.content)
        r = review([(z, Z)], rs); check('Reinsurance Staff 可審核應付給 Allianz（Facility）的帳款', r.status_code == 200, r.content)
        body = listing(rs); bid = row_of(body, a, A)['reviewBatchId']
        group = next(g for g in body['reviewBatches'] if g['id'] == bid)
        me = body['scope']['personnelId']
        check('同一對象合為一個批次（Swiss Re 4 筆）', len(group['members']) == 4, group['members'])
        check('每筆記錄審核人', row_of(body, a, A)['reviewedBy'] == me and row_of(body, b, B)['reviewedBy'] not in ('', me))

        # ---- 不能登錄收付款 ----
        r = register([(a, A, 800, 0)], -800, rs); check('Reinsurance Staff 不能登錄收付款', r.status_code == 403, r.content)

        # ---- Reinsurance Staff 取消：只能取消自己的 ----
        r = cancel_scope(rs, bid, 'account', [member(c3, C)]); check('不能單筆取消 Finance 審的帳款', r.status_code == 403 and r.json()['error'] == 'own_reviews_only', r.content)
        r = cancel_scope(rs, bid, 'account', [member(b, B)]); check('不能單筆取消其他同仁審的帳款', r.status_code == 403 and r.json()['error'] == 'own_reviews_only', r.content)
        r = cancel_scope(rs, bid, 'batch', [member(a, A), member(c3, C)]); check('整批取消時不能夾帶別人審的帳款', r.status_code == 409, r.content)
        r = cancel_scope(rs, bid, 'batch', [member(a, A)]); check('整批取消＝本人在這家審過的全部', r.status_code == 200, r.content)
        check('本人審的那筆退回未審核，其他人審的不動', not reviewed(a, A) and reviewed(b, B) and reviewed(c3, C) and reviewed(c4, D))
        check('Allianz 的審核不受影響', reviewed(z, Z))
        r = cancel_scope(rs, batch_id(b, B), 'batch', [member(b, B)]); check('批次裡已沒有本人的審核時不能整批取消', r.status_code == 403, r.content)

        # ---- Finance 單筆取消 ----
        r = cancel_scope(fin, batch_id(c4, D), 'account', [member(c4, D)]); check('Finance 單筆取消一次審核中的其中一筆', r.status_code == 200, r.content)
        check('只有那一筆退回，同次審核的另一筆仍已審核', not reviewed(c4, D) and reviewed(c3, C) and reviewed(b, B))
        event = FinanceReconciliationBatch.objects.get(members__contains=[{'txNo': C}])
        check('該次審核仍有效，並記下單筆取消的人、原因', event.status == 'active' and [m['txNo'] for m in event.cancelled_members] == [D]
              and event.cancelled_members[0]['cancelledByName'].startswith('Finance Test') and event.cancelled_members[0]['reason'] == 'QA review correction')
        check('單筆取消後原始審核內容保留不動', {m['txNo'] for m in event.members} == {C, D})
        r = cancel_scope(fin, batch_id(b, B), 'account', [member(b, B)]); check('Finance 可單筆取消其他人審的帳款', r.status_code == 200, r.content)
        lone = FinanceReconciliationBatch.objects.get(members__contains=[{'txNo': B}])
        check('一次審核的帳款全部取消時，整次審核改為已取消', lone.status == 'cancelled' and lone.cancel_reason == 'QA review correction')
        r = review([(c4, D)], rs); check('單筆取消後可以重新審核', r.status_code == 200, r.content)

        # ---- Finance 整批取消（原本的做法）----
        g = next(x for x in listing(fin)['reviewBatches'] if x['id'] == batch_id(c3, C))
        r = cancel_scope(fin, g['id'], 'batch', [{k: m[k] for k in ('caseUid', 'txNo', 'rowVersion')} for m in g['members']]); check('Finance 整批取消整個對象批次', r.status_code == 200, r.content)
        check('Swiss Re 批次全部退回未審核（含 Reinsurance Staff 審的）', not reviewed(c3, C) and not reviewed(c4, D))
        r = cancel(batch_id(z, Z), [z]); check('未指定取消方式時照原本整批取消', r.status_code == 200 and not reviewed(z, Z), r.content)

        # ---- 舊資料（Legacy Data）同樣適用 ----
        legacy = {'reinsurers': [{'name': RULE_NAMES['swiss']}], 'transactions': [{'txNo': 'LTX-QA-T2', 'reinsurerIdx': 0, 'source': 'premium'}]}
        check('舊資料應付給 Swiss Re（Facility）也算', facility_account(legacy, 'LTX-QA-T2', {'paymentDirection': 'payable', 'partyType': 'reinsurer', 'cashTracking': 'cash'}))
        check('舊資料向 Swiss Re 應收（退保、理賠）也算', facility_account(legacy, 'LTX-QA-T2', {'paymentDirection': 'receivable', 'partyType': 'reinsurer', 'cashTracking': 'cash'}))
        legacy['reinsurers'][0]['name'] = RULE_NAMES['qbe']
        check('其他 Facility（QBE）不算', not facility_account(legacy, 'LTX-QA-T2', {'paymentDirection': 'payable', 'partyType': 'reinsurer', 'cashTracking': 'cash'}))

        # ---- 同日擴大：向這兩家應收的退保保費與理賠款 ----
        refund = facility_case('QA-FR-R', SWISS, -1000); RT2 = leg(refund, 'Leg 2')
        k = facility_case('QA-FR-K', SWISS); KT1, KT2 = add_claim(k, 300, 1)
        # add_claim 把對象名稱寫死為 QA Reinsurer；改成系統實際產生的寫法（再保人名稱去掉 (Facility)）
        k.refresh_from_db(); k.payload = {**k.payload, 'transactions': [{**t, 'reinsurer': 'Swiss Re Asia Pte. Ltd., Hong Kong Branch'} if t.get('source') == 'claim' else t for t in k.payload['transactions']]}; k.save()
        body = listing(rs)
        check('退保：向 Swiss Re 收回的保費是應收，標為可審核', row_of(body, refund, RT2)['paymentDirection'] == 'receivable' and row_of(body, refund, RT2)['facilityReviewable'], row_of(body, refund, RT2))
        check('理賠：向 Swiss Re 收的理賠款標為可審核；付給 Cedant 的不算', row_of(body, k, KT1)['facilityReviewable'] and not row_of(body, k, KT2)['facilityReviewable'])
        r = review([(refund, RT2)], rs); check('Reinsurance Staff 可審核向 Swiss Re 收的退保保費', r.status_code == 200, r.content)
        r = review([(k, KT1)], rs); check('Reinsurance Staff 可審核向 Swiss Re 收的理賠款', r.status_code == 200, r.content)
        r = review([(k, KT2)], rs); check('Reinsurance Staff 不能審核付給 Cedant 的理賠', r.status_code == 403, r.content)
        r = register([(refund, RT2, 800, 0)], 800, rs); check('退保應收也不能登錄收款', r.status_code == 403, r.content)
        g = next(x for x in listing(rs)['reviewBatches'] if x['id'] == batch_id(refund, RT2))
        mine = [{k2: m[k2] for k2 in ('caseUid', 'txNo', 'rowVersion')} for m in g['members'] if m['reviewedBy'] == listing(rs)['scope']['personnelId']]
        r = cancel_scope(rs, g['id'], 'batch', mine); check('可取消自己審的應收（整批）', r.status_code == 200 and not reviewed(refund, RT2) and not reviewed(k, KT1), r.content)
        raise Done()
except Done:
    pass
print(f'{len(checks)}/{len(checks)} passed（Facility 帳款審核檢查全部通過；資料庫變更已回復）')
