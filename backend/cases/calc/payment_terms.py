"""
付款期限、付款排程與帳款結清狀態 - 逐行移植自 Hatchable Alpha 的 lib/payment-terms.js（v53）。

與 accounting.py 一樣，刻意保留 JavaScript 的語意，並由差異測試對 Alpha 的 JavaScript 逐位比對。
Alpha 的函數裡有兩處會讀「現在時間」（buildPaymentSchedule、deriveLedgerSettlement 的預設值），
這裡把 now 做成可傳入的參數，測試才能固定時間；正式使用時不傳就是現在。
"""
import math
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .accounting import calc_legs_for_reinsurer, strip_facility_tag
from .jsnum import (
    UNDEFINED, at, civil_from_days, get, is_array, js_spread, is_nullish, iso_date_prefix, js_is_finite, js_is_integer, js_or,
    js_max, js_min, js_round, js_string_to_number, js_to_number, js_to_string, js_truthy, js_trim, money,
    parse_iso_date_days, MAX_DAYS,
)

MIN_PAYMENT_TERMS_DAYS = 15
TAIPEI = ZoneInfo("Asia/Taipei")
_DATE_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def num(value):
    """空值或空字串回傳 None（不是 0）；其餘依 Number() 解析，非有限數字回傳 None。"""
    if is_nullish(value):
        return None
    trimmed = js_trim(js_to_string(value))
    if trimmed == "":
        return None
    n = js_string_to_number(trimmed.replace(",", ""))
    return n if js_is_finite(n) else None


def valid_terms(value):
    n = num(value)
    return n if n is not None and js_is_integer(n) and n >= MIN_PAYMENT_TERMS_DAYS else None


def valid_date(value):
    return _DATE_SHAPE.match(js_to_string(js_or(value, ""))) is not None


def add_calendar_days(value, days):
    """回傳 YYYY-MM-DD 字串；日期格式不對回傳 ""。與 Alpha 相同，天數不是有限數字時會丟出例外（Date.toISOString 的 RangeError）。"""
    if not valid_date(value):
        return ""
    base = parse_iso_date_days(value)
    if base is None:
        return ""
    n = js_to_number(js_or(days, 0))
    day_of_month = civil_from_days(base)[2]
    target = day_of_month + n              # setUTCDate 收到的是「當月第幾日 + 天數」，再取整數部分
    if not js_is_finite(target):
        raise ValueError("Invalid time value")
    total = base + (int(math.trunc(target)) - day_of_month)
    if abs(total) > MAX_DAYS:
        raise ValueError("Invalid time value")
    return iso_date_prefix(total)


def _as_utc(now):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        return datetime.fromisoformat(now.replace("Z", "+00:00"))
    return now


def taipei_date(now=None):
    return _as_utc(now).astimezone(TAIPEI).strftime("%Y-%m-%d")


def days_between_dates(date_from, date_to):
    """相差天數；任一邊不是有效日期回傳 None（Alpha 這裡回傳 null）；日期滾動後無效則回傳 NaN。"""
    if not valid_date(date_from) or not valid_date(date_to):
        return None
    a, b = parse_iso_date_days(date_from), parse_iso_date_days(date_to)
    if a is None or b is None:
        return math.nan
    return js_round((b - a) * 86400000 / 86400000)


def allocate(total, installments):
    if not installments:
        return []
    weights = []
    for row in installments:
        w = js_to_number(row["weight"])
        weights.append(js_max(0.0, 0.0 if (w != w or w == 0) else w))   # Math.max(0, Number(w) || 0)
    total_weight = 0.0
    for w in weights:
        total_weight += w
    if total_weight <= 0:
        total_weight = float(len(installments))
        weights = [1.0] * len(installments)
    used = 0.0
    result = []
    last = len(installments) - 1
    for index, _row in enumerate(installments):
        if index == last:
            result.append(money(total - used))
        else:
            amount = money(total * weights[index] / total_weight)
            used = money(used + amount)
            result.append(amount)
    return result


def payment_installments(case_data):
    if get(case_data, "installmentEnabled") is True:
        rows = get(case_data, "performanceInstallments")
        rows = rows if is_array(rows) else []
        result = []
        for index, row in enumerate(rows):
            entry = js_spread(row)
            weight = num(get(row, "premium"))
            if weight is None:
                weight = num(get(row, "ratio"))
            if weight is None:
                weight = 0
            entry.update({
                "id": js_to_string(js_or(get(row, "id"), "installment-" + str(index + 1))),
                "label": js_to_string(js_or(get(row, "performanceMonth"), "Installment " + str(index + 1))),
                "baseDate": js_to_string(js_or(get(row, "paymentBaseDate"), "")),
                "weight": js_max(0.0, float(weight)),
            })
            result.append(entry)
        return result
    return [{
        "id": "case-effective-date",
        "label": "Case Effective Date",
        "baseDate": js_to_string(js_or(get(case_data, "policyFrom"), "")),
        "weight": 1,
    }]


def _resolved_terms(case_data, installment, reinsurer, reinsurer_index):
    key = "r" + str(reinsurer_index + 1)
    raw = get(installment, "reinsurerPaymentTerms")
    mapping = raw if (js_truthy_object(raw)) else {}
    for candidate in (
        get(mapping, key) if isinstance(mapping, dict) else UNDEFINED,
        get(reinsurer, "paymentTermsDays"),
        get(installment, "paymentTermsDays"),
        get(case_data, "paymentTermsDays"),
    ):
        terms = valid_terms(candidate)
        if terms is not None:
            return terms
    return None


def _or_zero(value):
    """x || 0"""
    return value if js_truthy(value) else 0


def js_truthy_object(value):
    """value && typeof value === 'object'（陣列與物件都算；null 不算）"""
    return isinstance(value, (dict, list))


def _applied_by_key(case_data):
    result = {}
    entries = get(case_data, "paymentEntries")
    entries = entries if is_array(entries) else []
    for entry in entries:
        key = js_to_string(js_or(get(entry, "scheduleKey"), ""))
        amount = num(get(entry, "amount"))
        if not key or amount is None:
            continue
        signed = -abs(amount) if get(entry, "entryType") == "reversal" else abs(amount)
        previous = result.get(key)
        result[key] = money((previous if js_truthy(previous) else 0) + signed)
    return result


def _status_for(due_date, outstanding, paid, today, now):
    if not due_date:
        return "pending_review"
    if outstanding <= 0.004:
        return "settled"
    delta = days_between_dates(due_date, today)
    if delta is not None and delta > 0:
        return "overdue"
    if delta == 0:
        time = _as_utc(now).astimezone(TAIPEI).strftime("%H:%M")
        return "overdue" if time > "12:00" else "due_today"
    return "partially_paid" if paid > 0.004 else "upcoming"


def build_payment_schedule(case_data, now=None):
    now = _as_utc(now)
    reinsurers = get(case_data, "reinsurers")
    reinsurers = reinsurers if is_array(reinsurers) else []
    installments = payment_installments(case_data)
    applied = _applied_by_key(case_data)
    today = taipei_date(now)
    issues = []
    weights = [{**row, "weight": row["weight"]} for row in installments]
    legs = [calc_legs_for_reinsurer(case_data, r) for r in reinsurers]
    leg1_total = 0.0
    for row in legs:
        leg1_total += row["leg1"]
    cedant_amounts = allocate(leg1_total, weights)
    reinsurer_amounts = [allocate(row["leg2"], weights) for row in legs]
    items = []

    if valid_terms(get(case_data, "paymentTermsDays")) is None:
        issues.append("Case Payment Terms must be at least 15 calendar days.")

    for installment_index, installment in enumerate(installments):
        base_date = installment["baseDate"] if valid_date(installment["baseDate"]) else ""
        if not base_date:
            issues.append(installment["label"] + ": payment base date is required.")

        resolved = [_resolved_terms(case_data, installment, r, i) for i, r in enumerate(reinsurers)]
        all_terms = [t for t in resolved if t is not None]
        if len(all_terms) < len(resolved):
            issues.append(installment["label"] + ": Cedant due date calculation excludes Reinsurer(s) with invalid Payment Terms.")
        if all_terms:
            cedant_terms = js_min(*all_terms)
        else:
            cedant_terms = valid_terms(get(installment, "paymentTermsDays"))
            if cedant_terms is None:
                cedant_terms = valid_terms(get(case_data, "paymentTermsDays"))
        cedant_key = installment["id"] + ":cedant"
        cedant_paid = js_max(0.0, money(_or_zero(applied.get(cedant_key))))
        cedant_amount = js_max(0.0, money(_or_zero(cedant_amounts[installment_index] if installment_index < len(cedant_amounts) else None)))
        cedant_outstanding = js_max(0.0, money(cedant_amount - cedant_paid))
        cedant_due = add_calendar_days(base_date, cedant_terms - 15) if base_date and cedant_terms is not None else ""
        items.append({
            "scheduleKey": cedant_key, "installmentId": installment["id"], "installmentLabel": installment["label"],
            "partyType": "cedant", "partyKey": "cedant",
            "partyName": js_to_string(js_or(get(case_data, "reinsuredName"), get(case_data, "cedantName"), "Cedant")),
            "currency": js_to_string(js_or(get(case_data, "currency"), "")), "baseDate": base_date, "termsDays": cedant_terms,
            "dueDate": cedant_due, "dueTime": "12:00", "amount": cedant_amount, "paid": js_min(cedant_amount, cedant_paid),
            "outstanding": cedant_outstanding, "status": _status_for(cedant_due, cedant_outstanding, cedant_paid, today, now),
            "partial": cedant_paid > 0.004 and cedant_outstanding > 0.004,
        })

        for reinsurer_index, reinsurer in enumerate(reinsurers):
            terms = _resolved_terms(case_data, installment, reinsurer, reinsurer_index)
            if terms is None:
                issues.append(installment["label"] + ": invalid Payment Terms for Reinsurer " + str(reinsurer_index + 1) + ".")
            key = installment["id"] + ":reinsurer:r" + str(reinsurer_index + 1)
            paid = js_max(0.0, money(_or_zero(applied.get(key))))
            row_amounts = reinsurer_amounts[reinsurer_index] if reinsurer_index < len(reinsurer_amounts) else []
            amount = js_max(0.0, money(_or_zero(row_amounts[installment_index] if installment_index < len(row_amounts) else None)))
            outstanding = js_max(0.0, money(amount - paid))
            due_date = add_calendar_days(base_date, terms - 10) if base_date and terms is not None else ""
            items.append({
                "scheduleKey": key, "installmentId": installment["id"], "installmentLabel": installment["label"],
                "partyType": "reinsurer", "partyKey": "r" + str(reinsurer_index + 1),
                "partyName": js_to_string(js_or(get(reinsurer, "foreignBroker"), strip_facility_tag(get(reinsurer, "name")),
                                                "Reinsurer " + str(reinsurer_index + 1))),
                "currency": js_to_string(js_or(get(case_data, "currency"), "")), "baseDate": base_date, "termsDays": terms,
                "dueDate": due_date, "dueTime": "12:00", "amount": amount, "paid": js_min(amount, paid), "outstanding": outstanding,
                "status": _status_for(due_date, outstanding, paid, today, now),
                "partial": paid > 0.004 and outstanding > 0.004,
            })

    cedant_out = 0.0
    reinsurer_out = 0.0
    for row in items:
        if row["partyType"] == "cedant":
            cedant_out += row["outstanding"]
    for row in items:
        if row["partyType"] == "reinsurer":
            reinsurer_out += row["outstanding"]
    return {
        "items": items,
        "issues": list(dict.fromkeys(issues)),
        "reviewRequired": any("payment base date" in issue for issue in issues),
        "totals": {"cedantOutstanding": money(cedant_out), "reinsurerOutstanding": money(reinsurer_out)},
    }


def derive_ledger_settlement(case_data, transaction, now=None):
    """
    舊帳本（payload.transactions[]）的一筆交易，對應到新付款排程（paymentEntries[]）的結清狀態。
    Leg 1 對應 Cedant；Leg 2 對應該再保人；Leg 3（佣金差）沒有對應的排程，回報 not_tracked。
    """
    if get(transaction, "source") == "claim":
        return "settled" if get(transaction, "settlement") == "settled" else "open"
    leg_type = js_to_string(js_or(get(transaction, "legType"), ""))
    schedule = build_payment_schedule(case_data, now)

    def summarize(items):
        if not items:
            return "not_tracked"
        outstanding = 0.0
        paid = 0.0
        for item in items:
            outstanding += item["outstanding"]
        for item in items:
            paid += item["paid"]
        if outstanding <= 0.004:
            return "settled"
        if paid > 0.004:
            return "partial"
        return "open"

    if leg_type.startswith("Leg 1"):
        return summarize([i for i in schedule["items"] if i["partyType"] == "cedant"])
    if leg_type.startswith("Leg 2"):
        idx = get(transaction, "reinsurerIdx")
        reinsurer_idx = int(idx) if js_is_integer(idx) else -1
        if reinsurer_idx < 0:
            return "not_tracked"
        key = "r" + str(reinsurer_idx + 1)
        return summarize([i for i in schedule["items"] if i["partyType"] == "reinsurer" and i["partyKey"] == key])
    return "not_tracked"


def reminder_kind(item, today=None):
    due = get(item, "dueDate")
    if not js_truthy(due):
        return ""
    if js_to_number(get(item, "outstanding")) <= 0.004:   # undefined <= 0.004 是 false（繼續往下）；null 當 0
        return ""
    today = today if today is not None else taipei_date()
    days = days_between_dates(today, due)
    if days == 7:
        return "seven_days_before"
    if days == 0:
        return "due_today"
    overdue = days_between_dates(due, today)
    if overdue is not None and overdue > 0 and overdue % 7 == 0:
        return "weekly_overdue"
    return ""
