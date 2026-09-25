"""
Signed Slip 提醒的判斷邏輯。移植自 Hatchable Alpha 的 lib/signed-slip-reminders.js（逐函式對應），
並以差異測試與 Alpha 原始 JavaScript（backend/qa/alpha_js/lib/signed-slip-reminders.js）逐位比對。

注意：這裡的 reinsurer_key 與 Announce 的不同，不會去掉「(Facility)」（Alpha 兩處本來就不同，照搬）。
"""
import math
import re

from .jsnum import (
    MAX_DAYS, UNDEFINED, days_from_civil, get, is_array, iso_date_prefix, js_or, js_to_string,
    js_to_number, js_trim, js_truthy, strip_ws_regex,
)
from .payment_terms import taipei_date

DAY = 86400000
_WS_RUN = strip_ws_regex(r"\s+")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")


def reinsurer_key(value):
    """String(value || '').trim().toLowerCase().replace(/\\s+/g, ' ')"""
    return _WS_RUN.sub(" ", js_trim(js_to_string(js_or(value, ""))).lower())


def required_reinsurers(payload):
    rows = get(payload, "reinsurers")
    keys = [reinsurer_key(get(row, "name")) for row in (rows if is_array(rows) else [])]
    return list(dict.fromkeys(k for k in keys if k))


def date_utc(value):
    """Date.UTC(年, 月-1, 日) 的毫秒數（含月／日溢位、0–99 年視為 1900–1999）；格式不合回傳 NaN。"""
    match = _DATE.match(js_to_string(js_or(value, "")))
    if not match:
        return math.nan
    year, month, day = (int(g) for g in match.groups())
    if 0 <= year <= 99:
        year += 1900
    month_index = month - 1
    year += month_index // 12
    month_index %= 12
    return (days_from_civil(year, month_index + 1, 1) + day - 1) * DAY


def add_days(value, days):
    timestamp = date_utc(value)
    if math.isnan(timestamp):
        return ""
    total = timestamp + days * DAY
    clipped = math.trunc(total)  # new Date(x) 會把毫秒數截成整數（TimeClip）
    if not math.isfinite(total) or abs(clipped) > MAX_DAYS * DAY:
        raise ValueError("RangeError: Invalid time value")  # toISOString() 對無效時間拋出 RangeError
    return iso_date_prefix(clipped // DAY)


def days_between(date_from, date_to):
    start, end = date_utc(date_from), date_utc(date_to)
    if math.isnan(start) or math.isnan(end):
        return math.nan
    return (end - start) // DAY


def taipei_today(now=None):
    return taipei_date(now)


def missing_signed_reinsurers(payload, files):
    covered = set()
    for f in files if is_array(files) else []:
        if get(f, "kind") == "signed":
            names = get(f, "reinsurers")
            if is_array(names):
                covered.update(reinsurer_key(name) for name in names)
    return [name for name in required_reinsurers(payload) if name not in covered]


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def reminder_due(case_data, files, last_successful_alert_on, today):
    if not js_truthy(case_data) or get(case_data, "status") not in ("posted", "closed") \
            or not js_truthy(get(case_data, "policyFrom")):
        return None
    missing = missing_signed_reinsurers(case_data, files)
    if not missing:
        return None
    days_since = days_between(get(case_data, "policyFrom"), today)
    if not _finite(days_since) or days_since < 60:
        return None
    due_since = add_days(last_successful_alert_on, 7) if js_truthy(last_successful_alert_on) \
        else add_days(get(case_data, "policyFrom"), 60)
    if not due_since or _js_less(today, due_since):
        return None
    return {"missing": missing, "daysSinceEffective": days_since,
            "firstReminder": not js_truthy(last_successful_alert_on), "dueSince": due_since}


def _js_less(a, b):
    """
    JavaScript 的 a < b（today 與 dueSince）：物件與陣列先轉成字串（ToPrimitive）；
    兩邊都是字串就逐 UTF-16 單位比較，否則轉成數字比較。
    """
    a, b = (js_to_string(v) if isinstance(v, (dict, list)) else v for v in (a, b))
    if isinstance(a, str) and isinstance(b, str):
        return a.encode("utf-16-be", "surrogatepass") < b.encode("utf-16-be", "surrogatepass")
    return js_to_number(a) < js_to_number(b)


def signed_slip_tracking(case_data, files, today=UNDEFINED, now=None):
    if today is UNDEFINED:
        today = taipei_today(now)
    required = required_reinsurers(case_data)
    missing = missing_signed_reinsurers(case_data, files)
    days_since = days_between(get(case_data, "policyFrom"), today)
    eligible = get(case_data, "status") in ("posted", "closed")
    policy_from = get(case_data, "policyFrom")
    first_on = add_days(policy_from, 60) if js_truthy(policy_from) else ""
    return {
        "complete": len(required) > 0 and len(missing) == 0,
        "missing": missing,
        "eligibleStatus": eligible,
        "daysSinceEffective": days_since if _finite(days_since) else None,
        "firstReminderOn": first_on,
        "due": bool(eligible and missing and _finite(days_since) and days_since >= 60),
        "today": today,
        "cadenceDays": 7,
        "outboundEnabled": True,  # VM 在 API 層依設定覆寫（見 cases/document_views.py）
    }


_RESERVED_EXACT = {"example", "test", "invalid", "localhost", "example.com", "example.net", "example.org"}
_RESERVED_SUFFIX = (".example", ".test", ".invalid", ".example.com", ".example.net", ".example.org", ".localhost")


def is_reserved_test_email(value):
    email = js_trim(js_to_string(js_or(value, ""))).lower()
    domain = email.split("@")[-1] if "@" in email else ""
    return domain in _RESERVED_EXACT or domain.endswith(_RESERVED_SUFFIX)
