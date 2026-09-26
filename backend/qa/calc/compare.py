"""
差異測試的比對端：從標準輸入讀入 {"vectors": [...], "js": [...]}，
用 VM 的 Python 版跑同一批向量，並與 Alpha 的 JavaScript 結果「逐位」比對。

用法（由 scripts/run_calc_diff.sh 呼叫）：
  python -m qa.calc.compare < combined.json
"""
import json
import math
import sys

from cases import draft
from cases import workflow as wf
from cases import documents as docs
from cases import ledger
from production import calc as prod
from production import closing
from cases.calc import signed_slip as slip
from cases.calc import accounting as acc
from cases.calc import payment_terms as pt
from cases.calc.jsnum import UNDEFINED

FUNCTIONS = {
    "stripFacilityTag": lambda a, now: acc.strip_facility_tag(*a),
    "calcLegsForReinsurer": lambda a, now: acc.calc_legs_for_reinsurer(*a),
    "buildPremiumTransactions": lambda a, now: acc.build_premium_transactions(*a),
    "buildClaimPaymentTransactions": lambda a, now: acc.build_claim_payment_transactions(*a),
    "reconciliationRefFor": lambda a, now: acc.reconciliation_ref_for(*a),
    "addCalendarDays": lambda a, now: pt.add_calendar_days(*a),
    "taipeiDate": lambda a, now: pt.taipei_date(now),
    "daysBetweenDates": lambda a, now: pt.days_between_dates(*a),
    "paymentInstallments": lambda a, now: pt.payment_installments(*a),
    "buildPaymentSchedule": lambda a, now: pt.build_payment_schedule(a[0], now),
    "deriveLedgerSettlement": lambda a, now: pt.derive_ledger_settlement(a[0], a[1], now),
    "reminderKind": lambda a, now: pt.reminder_kind(*a),
    "normalizeDraft": lambda a, now: draft.normalize_draft(*a),
    "validateAnnounceReady": lambda a, now: draft.validate_announce_ready(*a),
    "reinsurerKey": lambda a, now: wf.reinsurer_key(*a),
    "requiredReinsurers": lambda a, now: wf.required_reinsurers(*a),
    "coverageFor": lambda a, now: wf.coverage_for(*a),
    "sameIds": lambda a, now: wf.same_ids(*a),
    "referencePrefix": lambda a, now: wf.reference_prefix(*a),
    "shiftYear": lambda a, now: wf.shift_year(*a),
    "resetSharedPayload": lambda a, now: wf.reset_shared_payload(*a),
    "buildEndorsementPayload": lambda a, now: wf.build_endorsement_payload(*a),
    "buildRenewalPayload": lambda a, now: wf.build_renewal_payload(*a),
    "buildReversedPayload": lambda a, now: wf.build_reversed_payload(*a),
    "appendNotification": lambda a, now: wf.append_notification(*a),
    "documentsReinsurerKey": lambda a, now: docs.reinsurer_key(*a),
    "documentsRequiredReinsurers": lambda a, now: docs.required_reinsurers(*a),
    "documentsCoverageFor": lambda a, now: docs.coverage_for(*a),
    "safeFilename": lambda a, now: docs.safe_filename(*a),
    # Alpha 的上限是 5 MB（VM 是 10 MB）：用 Alpha 的上限比對邏輯；bytes 以 JSON.stringify(Uint8Array) 的樣子比對
    "decodeAndValidate": lambda a, now: _uint8(docs.decode_and_validate(*a, max_bytes=5 * 1024 * 1024)),
    "slipReinsurerKey": lambda a, now: slip.reinsurer_key(*a),
    "slipRequiredReinsurers": lambda a, now: slip.required_reinsurers(*a),
    "slipDateUtc": lambda a, now: slip.date_utc(*a),
    "slipAddDays": lambda a, now: slip.add_days(*a),
    "slipDaysBetween": lambda a, now: slip.days_between(*a),
    "slipTaipeiToday": lambda a, now: slip.taipei_today(now),
    "slipMissingSignedReinsurers": lambda a, now: slip.missing_signed_reinsurers(*a),
    "slipReminderDue": lambda a, now: slip.reminder_due(*(list(a) + [UNDEFINED] * (4 - len(a)))),
    "slipSignedSlipTracking": lambda a, now: slip.signed_slip_tracking(*a, now=now),
    "slipIsReservedTestEmail": lambda a, now: slip.is_reserved_test_email(*a),
    "buildProductionPreview": lambda a, now: prod.build_production_preview(*a),
    "productionKeysForCase": lambda a, now: prod.production_keys_for_case(*a),
    "nextProductionMonth": lambda a, now: prod.next_production_month(*a),
    "productionConfirmCase": lambda a, now: closing.confirm_case(*a),
    "accountingLedgerRows": lambda a, now: dict(zip(("rows", "warnings"), ledger.ledger_rows(a[0], now))),
}


def _uint8(result):
    if isinstance(result, dict) and isinstance(result.get("bytes"), bytes):
        return {**result, "bytes": {str(i): b for i, b in enumerate(result["bytes"])}}
    return result


def to_json_value(x):
    """把 Python 的結果轉成「JavaScript 會 JSON 出來」的樣子。"""
    if isinstance(x, dict):
        return {k: to_json_value(v) for k, v in x.items() if v is not UNDEFINED}
    if isinstance(x, (list, tuple)):
        return [None if v is UNDEFINED else to_json_value(v) for v in x]
    if isinstance(x, float):
        if math.isnan(x):
            return {"__nonfinite": "NaN"}
        if math.isinf(x):
            return {"__nonfinite": "Infinity" if x > 0 else "-Infinity"}
    return x


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def first_difference(a, b, path="$"):
    if same(a, b):
        return None
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}.{k}: 只有 Python 有 = {json.dumps(b[k], ensure_ascii=False)[:120]}"
            if k not in b:
                return f"{path}.{k}: 只有 JavaScript 有 = {json.dumps(a[k], ensure_ascii=False)[:120]}"
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
    return f"{path}: JavaScript = {json.dumps(a, ensure_ascii=False)[:140]}   Python = {json.dumps(b, ensure_ascii=False)[:140]}"


def main():
    # 與 JavaScript 一致：所有數字都當成雙精度浮點數（Python 預設會把整數保留成 int）
    data = json.loads(sys.stdin.read(), parse_int=float)
    vectors, js = data["vectors"], data["js"]
    assert len(vectors) == len(js), "向量數與 JavaScript 結果數不同"
    stats, samples = {}, {}
    for index, (vec, expected) in enumerate(zip(vectors, js)):
        name = vec["fn"]
        try:
            value = FUNCTIONS[name](vec["args"], vec.get("now"))
            actual = {"undef": True} if value is UNDEFINED else {"ok": to_json_value(value)}
        except Exception as exc:  # noqa: BLE001 - 任何例外都視為「會出錯」，與 JavaScript 是否也出錯比對
            actual = {"error": type(exc).__name__}
        if "error" in expected or "error" in actual:
            ok = "error" in expected and "error" in actual          # 兩邊都出錯才算一致
        elif "undef" in expected or "undef" in actual:
            ok = expected == actual
        else:
            ok = same(expected["ok"], actual["ok"])
        total, bad = stats.get(name, (0, 0))
        stats[name] = (total + 1, bad + (0 if ok else 1))
        if not ok and len(samples.setdefault(name, [])) < 3:
            detail = (first_difference(expected.get("ok"), actual.get("ok")) if "ok" in expected and "ok" in actual
                      else f"JavaScript = {json.dumps(expected, ensure_ascii=False)[:100]}   Python = {json.dumps(actual, ensure_ascii=False)[:100]}")
            samples[name].append((index, vec, detail))

    width = max(len(n) for n in stats)
    grand_total = grand_bad = 0
    for name, (total, bad) in stats.items():
        grand_total += total
        grand_bad += bad
        print(f"  {'OK ' if not bad else 'BAD'} {name:<{width}}  {total - bad:>5}/{total:<5} 一致")
    print(f"\n  共 {grand_total} 組向量，{grand_total - grand_bad} 組完全一致，{grand_bad} 組不一致")
    for name, items in samples.items():
        print(f"\n--- {name} 的不一致範例 ---")
        for index, vec, detail in items:
            args = json.dumps(vec["args"], ensure_ascii=False)
            print(f"  向量 #{index}  now={vec.get('now')}\n    輸入: {args[:260]}\n    差異: {detail}")
    sys.exit(1 if grand_bad else 0)


if __name__ == "__main__":
    main()
