"""
差異測試的比對端：從標準輸入讀入 {"vectors": [...], "js": [...]}，
用 VM 的 Python 版跑同一批向量，並與 Alpha 的 JavaScript 結果「逐位」比對。

用法（由 scripts/run_calc_diff.sh 呼叫）：
  python -m qa.calc.compare < combined.json
"""
import json
import math
import sys
import copy

from cases import draft
from cases import workflow as wf
from cases import documents as docs
from cases import ledger
from production import calc as prod
from production import closing
from dashboard import calc as dash
from reminders import messages as rem
from cases.calc import signed_slip as slip
from cases.calc import accounting as acc
from cases.calc import payment_terms as pt
from cases.calc.jsnum import UNDEFINED

FUNCTIONS = {
    "stripFacilityTag": lambda a, now: acc.strip_facility_tag(*a),
    "calcLegsForReinsurer": lambda a, now: acc.calc_legs_for_reinsurer(*a),
    "buildPremiumTransactions": lambda a, now: acc.build_premium_transactions(*a),
    "premiumInstallmentPlan": lambda a, now: pt.premium_installment_plan(*a),
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
    "buildProductionPreview": lambda a, now: _production_preview_vm(a),
    "productionKeysForCase": lambda a, now: prod.production_keys_for_case(*a),
    "nextProductionMonth": lambda a, now: prod.next_production_month(*a),
    "dashboardSummary": lambda a, now: _dashboard_vm(a, now),
    "productionConfirmCase": lambda a, now: closing.confirm_case(*a),
    "accountingLedgerRows": lambda a, now: dict(zip(("rows", "warnings"), ledger.ledger_rows(a[0], now))),
    "payEsc": lambda a, now: rem.esc(a[0]),
    "payValidEmail": lambda a, now: rem.valid_email(a[0]),
    "payLabel": lambda a, now: rem.label(a[0]),
    "payMessage": lambda a, now: rem.message(*a),
    "payResolveRecipients": lambda a, now: rem.resolve_recipients(*a),
    "payFinanceEmails": lambda a, now: rem.finance_emails(a[0]),
    "payDueKind": lambda a, now: rem.due_kind(*a),
    "slipEscapeHtml": lambda a, now: rem.escape_html(a[0]),
    "slipValidEmailApi": lambda a, now: rem.valid_email(a[0]),
    "slipContactFor": lambda a, now: rem.contact_for(*a),
    "slipReminderMessage": lambda a, now: rem.reminder_message(*a),
}


def _production_preview_vm(a):
    """VM 在每一列多了 firstPolicyNo（Alpha 沒有）；先拿掉再與 Alpha 比。沒有這個欄位會 KeyError → 算不一致。
    這個欄位本身由 suites/production_api.py 與 suites/production_first_policy.py 檢查。"""
    result = prod.build_production_preview(*a)
    for key in ("rows", "excluded"):
        for row in result.get(key, []):
            row.pop("firstPolicyNo")
    return result


def _dashboard_vm(a, now):
    """VM 的 API 實際用的模式（台北時間＋Production 規則）；Alpha v57 起 Dashboard 也是這樣。
    與 views.py 相同，先把時間戳記換成台北時間的文字再交給 build_dashboard。"""
    from zoneinfo import ZoneInfo
    tpe = ZoneInfo("Asia/Taipei")

    def text(value):
        if not isinstance(value, str) or not value:
            return None
        try:
            return _now(value).astimezone(tpe).isoformat()
        except ValueError:
            return None
    rows = [{**r, "announced_at": text(r.get("announced_at")), "created_at": text(r.get("created_at"))} if isinstance(r, dict) else r for r in a[0]]
    return dash.build_dashboard(rows, a[1], a[2], _now(now), tz=tpe, production_rules=True)



def _now(value):
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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


def vm_numbering_expected(vec, expected):
    """Frozen Alpha uses TX/CLM; adapt only newly generated transaction numbers.

    Existing entries and reversal references must retain their stored identifiers.
    All other fields, including amounts, are still compared without adaptation.
    """
    if 'ok' not in expected:
        return expected
    name = vec['fn']
    if name not in ('buildPremiumTransactions', 'buildClaimPaymentTransactions', 'productionConfirmCase'):
        return expected
    result = copy.deepcopy(expected)
    if name == 'productionConfirmCase':
        payload = vec['args'][0].get('payload') or {}
        previous = payload.get('transactions')
        previous_count = len(previous) if isinstance(previous, list) else 0
        rows = result['ok']['payload'].get('transactions')
        rows = rows[previous_count:] if isinstance(rows, list) else []
    else:
        rows = result['ok']
    for row in rows:
        if not isinstance(row, dict) or row.get('isReversalEntry'):
            continue
        number = row.get('txNo')
        if not isinstance(number, str):
            continue
        head, separator, tail = number.rpartition('-TX')
        if separator:
            number = head + '-T' + tail
        if name == 'buildClaimPaymentTransactions':
            head, separator, tail = number.rpartition('-CLM')
            if separator:
                number = head + '-C' + tail
        row['txNo'] = number
    return result


def vm_split_remainder_expected(vec, expected):
    """2026-10-14: with Performance Split percentages totalling 100%, the VM books the b party as
    (leg total - a party) so a + b equals the leg exactly; frozen Alpha rounds each side independently.
    Only the b amount is adapted; the leg total comes from the VM's own non-split build of the same input."""
    if vec["fn"] != "buildPremiumTransactions" or not isinstance(expected.get("ok"), list):
        return expected
    import copy as _copy
    from cases.calc.jsnum import get, is_array, js_is_finite, js_to_number, money
    case = vec["args"][0]
    parties = get(case, "splitParties")
    if get(case, "splitEnabled") is not True or not is_array(parties) or len(parties) != 2:
        return expected
    pct_a, pct_b = (js_to_number(get(p, "pct")) if get(p, "pct") is not None else 0.0 for p in parties)
    if not (js_is_finite(pct_a) and js_is_finite(pct_b)) or abs(pct_a + pct_b - 100) >= 1e-9:
        return expected
    plain = acc.build_premium_transactions({**case, "splitEnabled": False}, *vec["args"][1:])
    totals = {(t.get("reinsurerIdx"), t.get("installmentId"), t["legType"]): t["amount"] for t in plain}
    result = _copy.deepcopy(expected)
    by_key = {}
    for row in result["ok"]:
        if isinstance(row, dict) and str(row.get("legType", "")).endswith(("a", "b")):
            by_key[(row.get("reinsurerIdx"), row.get("installmentId"), row["legType"])] = row
    for (idx, inst, leg), row in by_key.items():
        if leg.endswith("b") and (idx, inst, leg[:-1] + "a") in by_key:
            total = totals.get((idx, inst, leg[:-1]))
            if total is not None:
                row["amount"] = money(total - by_key[(idx, inst, leg[:-1] + "a")]["amount"])
    return result


def vm_split_remainder_confirm_expected(vec, expected, actual):
    """productionConfirmCase builds the same split legs (see vm_split_remainder_expected, which is checked exactly through
    buildPremiumTransactions). Its output does not contain the leg total, so a 'b' split amount may differ from Alpha by one cent
    when every other field of that transaction is identical."""
    if vec["fn"] != "productionConfirmCase" or "ok" not in expected or "ok" not in actual:
        return expected
    import copy as _copy
    payload = vec["args"][0].get("payload") or {}
    previous = payload.get("transactions")
    skip = len(previous) if isinstance(previous, list) else 0
    try:
        exp_rows = expected["ok"]["payload"]["transactions"]
        act_rows = actual["ok"]["payload"]["transactions"]
    except (KeyError, TypeError):
        return expected
    if not isinstance(exp_rows, list) or not isinstance(act_rows, list) or len(exp_rows) != len(act_rows):
        return expected
    result = _copy.deepcopy(expected)
    for index in range(skip, len(exp_rows)):
        row, other = result["ok"]["payload"]["transactions"][index], act_rows[index]
        if not (isinstance(row, dict) and isinstance(other, dict)) or not str(row.get("legType", "")).endswith("b"):
            continue
        if (isinstance(row.get("amount"), float) and isinstance(other.get("amount"), float)
                and abs(row["amount"] - other["amount"]) <= 0.0101
                and {k: v for k, v in row.items() if k != "amount"} == {k: v for k, v in other.items() if k != "amount"}):
            row["amount"] = other["amount"]
    return result

def vm_optional_cedant_fields_expected(vec, expected):
    """2026-10-12: Case-level Ceding Commission and Tax are optional in the VM."""
    if vec["fn"] != "validateAnnounceReady" or not isinstance(expected.get("ok"), list):
        return expected
    return {**expected, "ok": [issue for issue in expected["ok"] if issue.get("field") not in ("riCommPct", "taxPct")]}


def vm_positive_sum_amount_expected(vec, expected):
    """VM: preserve Alpha issue order while requiring each Sum Insured amount > 0."""
    if vec["fn"] != "validateAnnounceReady" or not isinstance(expected.get("ok"), list):
        return expected
    from cases.calc.jsnum import get, is_array, js_is_finite, js_to_number
    rows = get(vec["args"][0], "sumInsured")
    if not is_array(rows):
        return expected
    issues = [dict(issue) for issue in expected["ok"]]
    # This block precedes loss history and cedant premium validation in Alpha.
    following = {"lossAdvisedDate", "lossRecordYears", "lossRecord", "originalPremium", "paymentTermsDays", "performanceInstallments", "splitParties"}
    for index, row in enumerate(rows):
        field = f"sumInsured.{index}.amount"
        amount = js_to_number(get(row, "amount"))
        existing = next((i for i, issue in enumerate(issues) if issue["field"] == field), None)
        if existing is not None:
            issues[existing]["label"] = f"Sum insured {index + 1} Amount must be greater than 0"
        elif not js_is_finite(amount) or amount <= 0:
            position = len(issues)
            for i, issue in enumerate(issues):
                path = issue["field"]
                if (path.startswith("sumInsured.") and int(path.split(".")[1]) > index) or path.split(".")[0] in following:
                    position = i
                    break
            issues.insert(position, {"field": field, "label": f"Sum insured {index + 1} Amount must be greater than 0"})
    return {**expected, "ok": issues}


def vm_sum_placements_expected(vec, expected):
    if vec["fn"] == "normalizeDraft" and isinstance(expected.get("ok"), dict) and isinstance(expected["ok"].get("value"), dict):
        from cases.calc.jsnum import js_is_integer, js_to_number
        result = copy.deepcopy(expected)
        raw = vec["args"][0].get("sumInsured")
        if isinstance(raw, list):
            for source, row in zip(raw[:50], result["ok"]["value"]["sumInsured"]):
                if isinstance(source, dict) and "locationIndex" in source:
                    value = source["locationIndex"]
                    if value is None or (isinstance(value, str) and not value.strip()) or not js_is_integer(js_to_number(value)) or js_to_number(value) < 0:
                        row["locationIndex"] = None
        return result
    if vec["fn"] != "validateAnnounceReady" or not isinstance(expected.get("ok"), list):
        return expected
    from cases.sum_insured import placement_issues
    additions = [{"field": i["field"], "label": i["label"]} for i in placement_issues(vec["args"][0])]
    issues = list(expected["ok"])
    following = {"lossAdvisedDate", "lossRecordYears", "lossRecord", "originalPremium", "paymentTermsDays", "performanceInstallments", "splitParties"}
    index = next((i for i, issue in enumerate(issues) if issue["field"].split(".")[0] in following), len(issues))
    return {**expected, "ok": issues[:index] + additions + issues[index:]}


def vm_account_executive_email_expected(vec, expected):
    """VM email salutation uses the full role name; Alpha source stays frozen."""
    if vec["fn"] != "slipReminderMessage" or not isinstance(expected.get("ok"), dict):
        return expected
    result = copy.deepcopy(expected)
    text = result["ok"].get("text")
    html = result["ok"].get("html")
    if isinstance(text, str) and text.startswith("AE "):
        result["ok"]["text"] = "Account Executive " + text[3:]
    if isinstance(html, str) and html.startswith("<p>AE "):
        result["ok"]["html"] = "<p>Account Executive " + html[6:]
    return result


def main():
    # 與 JavaScript 一致：所有數字都當成雙精度浮點數（Python 預設會把整數保留成 int）
    data = json.loads(sys.stdin.read(), parse_int=float)
    vectors, js = data["vectors"], data["js"]
    assert len(vectors) == len(js), "向量數與 JavaScript 結果數不同"
    stats, samples = {}, {}
    for index, (vec, expected) in enumerate(zip(vectors, js)):
        expected = vm_account_executive_email_expected(vec, vm_sum_placements_expected(vec, vm_positive_sum_amount_expected(vec, vm_optional_cedant_fields_expected(vec, vm_split_remainder_expected(vec, vm_numbering_expected(vec, expected))))))
        name = vec["fn"]
        try:
            value = FUNCTIONS[name](vec["args"], vec.get("now"))
            actual = {"undef": True} if value is UNDEFINED else {"ok": to_json_value(value)}
        except Exception as exc:  # noqa: BLE001 - 任何例外都視為「會出錯」，與 JavaScript 是否也出錯比對
            actual = {"error": type(exc).__name__}
        expected = vm_split_remainder_confirm_expected(vec, expected, actual)
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
