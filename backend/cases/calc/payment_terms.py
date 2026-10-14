"""
付款期限、付款排程與帳款結清狀態 - 逐行移植自 Hatchable Alpha 的 lib/payment-terms.js（v53）。

與 accounting.py 一樣，刻意保留 JavaScript 的語意，並由差異測試對 Alpha 的 JavaScript 逐位比對。
Alpha 的函數裡有兩處會讀「現在時間」（buildPaymentSchedule、deriveLedgerSettlement 的預設值），
這裡把 now 做成可傳入的參數，測試才能固定時間；正式使用時不傳就是現在。

VM 2026-10-06：批單負保費／退款紀錄保留符號，依絕對值分攤與判斷结清；原保單與續保沿用既有結果。
"""
import calendar
import math
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from ..manual_reference import is_auw_reinsurer
from .accounting import calc_legs_for_reinsurer, strip_facility_tag
from .jsnum import (
    UNDEFINED, at, civil_from_days, get, is_array, js_spread, is_nullish, iso_date_prefix, js_is_finite, js_is_integer, js_or,
    js_max, js_min, js_round, js_string_to_number, js_to_number, js_to_string, js_truthy, js_trim, money,
    parse_iso_date_days, MAX_DAYS,
)

MIN_PAYMENT_TERMS_DAYS = 15
AUW_PAYMENT_TERMS_DAYS = 120
AUW_ACCOUNTING_LEAD_DAYS = 10
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


def month_end_date(value):
    """AUW uses the last real calendar date of the applicable base month."""
    if not isinstance(value, str) or not valid_date(value):
        return ""
    try:
        base = date.fromisoformat(value)
    except ValueError:
        return ""
    return base.replace(day=calendar.monthrange(base.year, base.month)[1]).isoformat()


def endorsement_base_date(case_data):
    """Later of the actual announcement's Taiwan date and endorsement effective date.

    Drafts have no actual Announce date yet; never infer it from creation or today.
    The announce endpoint supplies its authoritative candidate timestamp to validation.
    """
    effective = get(case_data, "endoEffectiveDate")
    announced = get(case_data, "endorsementAnnouncedAt")
    if not month_end_date(effective) or not isinstance(announced, (str, datetime)):
        return ""
    try:
        stamp = _as_utc(announced)
        if stamp.tzinfo is None:
            return ""
        announced_date = taipei_date(stamp)
    except (ValueError, TypeError, OverflowError):
        return ""
    return max(effective, announced_date)


def auw_payment_dates(case_data, installment):
    source_date = installment["baseDate"]
    if get(case_data, "installmentEnabled") is not True and js_truthy(get(case_data, "parentTwRef")):
        source_date = endorsement_base_date(case_data)
    base_date = month_end_date(source_date)
    actual_due = add_calendar_days(base_date, AUW_PAYMENT_TERMS_DAYS) if base_date else ""
    due_date = add_calendar_days(actual_due, -AUW_ACCOUNTING_LEAD_DAYS) if actual_due else ""
    return source_date, base_date, actual_due, due_date


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
                "weight": abs(float(weight)) if js_truthy(get(case_data, "parentTwRef")) else js_max(0.0, float(weight)),
            })
            result.append(entry)
        return result
    return [{
        "id": "case-effective-date",
        "label": "Case Effective Date",
        "baseDate": js_to_string(js_or(get(case_data, "endoEffectiveDate"), get(case_data, "policyFrom"), ""))
                    if js_truthy(get(case_data, "parentTwRef")) and (num(get(case_data, "originalPremium")) or 0) < 0
                    else js_to_string(js_or(get(case_data, "policyFrom"), "")),
        "weight": 1,
    }]


def premium_installment_plan(case_data):
    """每期關帳產生的保費交易：每個再保人的 Leg 1／2 依分期權重拆到各期（與付款排程同一個 allocate，
    所以 SoA 的 Leg 2 與 Accounting 的各期應付金額相同），Leg 3 = 該期 Leg 1 - Leg 2。沒有分期回傳空陣列。"""
    if get(case_data, "installmentEnabled") is not True:
        return []
    installments = payment_installments(case_data)
    reinsurers = get(case_data, "reinsurers")
    reinsurers = reinsurers if is_array(reinsurers) else []
    legs = [calc_legs_for_reinsurer(case_data, r) for r in reinsurers]
    leg1s = [allocate(row["leg1"], installments) for row in legs]
    leg2s = [allocate(row["leg2"], installments) for row in legs]
    return [{
        "id": row["id"], "label": row["label"], "number": index + 1,
        "amounts": [{
            "leg1": leg1s[r][index], "leg2": leg2s[r][index], "leg3": money(leg1s[r][index] - leg2s[r][index]),
        } for r in range(len(legs))],
    } for index, row in enumerate(installments)]


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
        # Endorsement refunds store signed cash entries; reversing cash negates that same sign.
        cash_amount = amount if js_truthy(get(case_data, "parentTwRef")) else abs(amount)
        signed = -cash_amount if get(entry, "entryType") == "reversal" else cash_amount
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
    signed_premiums = js_truthy(get(case_data, "parentTwRef"))

    def balances(raw_amount, applied_amount):
        amount = money(_or_zero(raw_amount))
        if not signed_premiums:
            amount = js_max(0.0, amount)
        sign = -1 if amount < 0 else 1
        paid = js_max(0.0, money(_or_zero(applied_amount) * sign))
        progress = js_min(abs(amount), paid)
        remaining = js_max(0.0, money(abs(amount) - paid))
        return amount, sign * progress, sign * remaining

    def refund_fields(amount, party_type):
        if amount >= 0:
            return {}
        return {"returnPremium": True, "paymentDirection": "payable" if party_type == "cedant" else "receivable"}

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
        # New cases use the Cedant's own contract terms. AUW's fixed 120-day
        # settlement must never become the Cedant's collection term. Ordinary
        # historical payloads retain their previous minimum-reinsurer rule.
        if get(case_data, "cedantTermsBasis") == "case" or any(is_auw_reinsurer(get(r, "name")) for r in reinsurers):
            cedant_terms = valid_terms(get(installment, "paymentTermsDays"))
            if cedant_terms is None:
                cedant_terms = valid_terms(get(case_data, "paymentTermsDays"))
        cedant_base = base_date
        cedant_rule = {}
        if js_truthy(get(case_data, "parentTwRef")) and get(case_data, "installmentEnabled") is not True:
            cedant_base = endorsement_base_date(case_data)
            cedant_terms = valid_terms(get(case_data, "paymentTermsDays"))
            cedant_rule = {"paymentRule": "endorsement_later_announce_effective",
                           "contractDueDate": add_calendar_days(cedant_base, cedant_terms) if cedant_base and cedant_terms is not None else "",
                           "accountingLeadDays": 15}
            if not cedant_base:
                issues.append("Endorsement: payment base date requires Announce and a valid endorsement effective date.")
        cedant_key = installment["id"] + ":cedant"
        cedant_amount, cedant_paid, cedant_outstanding = balances(
            cedant_amounts[installment_index] if installment_index < len(cedant_amounts) else None, applied.get(cedant_key))
        cedant_due = add_calendar_days(cedant_base, cedant_terms - 15) if cedant_base and cedant_terms is not None else ""
        items.append({
            "scheduleKey": cedant_key, "installmentId": installment["id"], "installmentLabel": installment["label"],
            "partyType": "cedant", "partyKey": "cedant",
            "partyName": js_to_string(js_or(get(case_data, "reinsured"), get(case_data, "reinsuredName"), get(case_data, "cedantName"), "Cedant"))
                         if cedant_amount < 0 else js_to_string(js_or(get(case_data, "reinsuredName"), get(case_data, "cedantName"), "Cedant")),
            "currency": js_to_string(js_or(get(case_data, "currency"), "")), "baseDate": cedant_base, "termsDays": cedant_terms,
            "dueDate": cedant_due, "dueTime": "12:00", "amount": cedant_amount, "paid": cedant_paid,
            "outstanding": cedant_outstanding, "status": _status_for(cedant_due, abs(cedant_outstanding), abs(cedant_paid), today, now),
            "partial": abs(cedant_paid) > 0.004 and abs(cedant_outstanding) > 0.004,
            **refund_fields(cedant_amount, "cedant"),
            **cedant_rule,
        })

        for reinsurer_index, reinsurer in enumerate(reinsurers):
            auw = is_auw_reinsurer(get(reinsurer, "name"))
            terms = AUW_PAYMENT_TERMS_DAYS if auw else _resolved_terms(case_data, installment, reinsurer, reinsurer_index)
            if terms is None:
                issues.append(installment["label"] + ": invalid Payment Terms for Reinsurer " + str(reinsurer_index + 1) + ".")
            key = installment["id"] + ":reinsurer:r" + str(reinsurer_index + 1)
            row_amounts = reinsurer_amounts[reinsurer_index] if reinsurer_index < len(reinsurer_amounts) else []
            amount, paid, outstanding = balances(
                row_amounts[installment_index] if installment_index < len(row_amounts) else None, applied.get(key))
            row_base_date = base_date
            rule_fields = {}
            if auw:
                source_date, row_base_date, actual_due, due_date = auw_payment_dates(case_data, installment)
                rule_fields = {"paymentRule": "auw_month_end_120", "sourceBaseDate": source_date,
                               "contractDueDate": actual_due, "accountingLeadDays": AUW_ACCOUNTING_LEAD_DAYS}
                if not row_base_date:
                    issues.append(installment["label"] + ": AUW payment base date must be a valid effective or installment date.")
            else:
                if signed_premiums and get(case_data, "installmentEnabled") is not True:
                    # Each RI leg may have its own direction in a mixed endorsement.
                    # Payables wait for both inception and actual Announce; recovery
                    # of a negative premium follows the endorsement effective date.
                    if amount > 0:
                        row_base_date = endorsement_base_date(case_data)
                    else:
                        effective = get(case_data, "endoEffectiveDate")
                        row_base_date = effective if month_end_date(effective) else ""
                    if not row_base_date:
                        issues.append(installment["label"] + ": ordinary Reinsurer payment base date requires a valid endorsement effective date and, for payables, Announce.")
                due_date = add_calendar_days(row_base_date, terms - 10) if row_base_date and terms is not None else ""
            items.append({
                "scheduleKey": key, "installmentId": installment["id"], "installmentLabel": installment["label"],
                "partyType": "reinsurer", "partyKey": "r" + str(reinsurer_index + 1),
                "partyName": js_to_string(js_or(get(reinsurer, "foreignBroker"), strip_facility_tag(get(reinsurer, "name")),
                                                "Reinsurer " + str(reinsurer_index + 1))),
                "currency": js_to_string(js_or(get(case_data, "currency"), "")), "baseDate": row_base_date, "termsDays": terms,
                "dueDate": due_date, "dueTime": "12:00", "amount": amount, "paid": paid, "outstanding": outstanding,
                "status": _status_for(due_date, abs(outstanding), abs(paid), today, now),
                "partial": abs(paid) > 0.004 and abs(outstanding) > 0.004,
                **refund_fields(amount, "reinsurer"),
                **rule_fields,
            })

    from .swiss_facility import apply_schedule
    items = apply_schedule(case_data, items, now)
    from ..facility_accounting import apply_schedules
    items = apply_schedules(case_data, items)

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
    # 每期關帳產生的交易帶有 installmentId：只看該期的排程項目（舊的全額交易沒有，維持看全部）
    installment_id = get(transaction, "installmentId")

    def for_installment(item):
        return not js_truthy(installment_id) or item["installmentId"] == installment_id

    def summarize(items):
        if not items:
            return "not_tracked"
        outstanding = 0.0
        paid = 0.0
        for item in items:
            outstanding += abs(item["outstanding"])
        for item in items:
            paid += abs(item["paid"])
        if outstanding <= 0.004:
            return "settled"
        if paid > 0.004:
            return "partial"
        return "open"

    if leg_type.startswith("Leg 1"):
        return summarize([i for i in schedule["items"] if i["partyType"] == "cedant" and for_installment(i)])
    if leg_type.startswith("Leg 2"):
        idx = get(transaction, "reinsurerIdx")
        reinsurer_idx = int(idx) if js_is_integer(idx) else -1
        if reinsurer_idx < 0:
            return "not_tracked"
        key = "r" + str(reinsurer_idx + 1)
        return summarize([i for i in schedule["items"] if i["partyType"] == "reinsurer" and i["partyKey"] == key and for_installment(i)])
    return "not_tracked"


def reminder_kind(item, today=None):
    due = get(item, "dueDate")
    if not js_truthy(due):
        return ""
    outstanding = js_to_number(get(item, "outstanding"))
    if (abs(outstanding) if get(item, "returnPremium") is True else outstanding) <= 0.004:
        return ""
    today = today if today is not None else taipei_date()
    days = days_between_dates(today, due)
    if days == 7:
        return "seven_days_before"
    if days == 0:
        return "due_today"
    if get(item, "paymentRule") == "swiss_cedant_75_90":
        contract = get(item, "contractDueDate")
        overdue = days_between_dates(contract, today)
    else:
        overdue = days_between_dates(due, today)
    if overdue is not None and overdue > 0 and overdue % 7 == 0:
        return "weekly_overdue"
    return ""
