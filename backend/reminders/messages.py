"""
提醒信的純函式（不碰資料庫、不依賴 Django；差異測試 qa/calc/compare.py 直接 import）。

  付款提醒     對應 Alpha api/payment-reminders.js 的 esc、validEmail、label、message、resolveRecipients、dueKind
  Signed Slip  對應 Alpha api/signed-slip-reminders.js 的 escapeHtml、validEmail、contactFor、reminderMessage

信件最後的連結：Alpha 寫死「開啟 RI System (Alpha)」連到 ri-system-alpha.hatchable.site；VM 改由參數傳入
（settings.REMINDER_LINK_URL／REMINDER_LINK_TEXT，2026-09-26 你的決定）。差異測試傳入 Alpha 的網址與文字，逐字比對其餘內容。
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from cases.calc.jsnum import JS_WS, UNDEFINED, get, is_array, is_nullish, js_or, js_to_number, js_to_string, js_trim, js_truthy
from cases.calc.payment_terms import add_calendar_days, days_between_dates

ALPHA_LINK_URL = "https://ri-system-alpha.hatchable.site"
ALPHA_LINK_TEXT = "開啟 RI System (Alpha)"

_NOT_WS_AT = f"[^{re.escape(JS_WS)}@]+"
_EMAIL = re.compile(f"{_NOT_WS_AT}@{_NOT_WS_AT}\\.{_NOT_WS_AT}\\Z")
_HTML = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def _s(value):
    """String(value)：undefined 是 "undefined"、null 是 "null"。"""
    return "undefined" if value is UNDEFINED else js_to_string(value)


def _nullish_text(value):
    """String(value ?? "")"""
    return "" if is_nullish(value) else js_to_string(value)


def _or_text(value, fallback=""):
    """String(value || fallback)"""
    return _s(js_or(value, fallback))


def js_lower(text):
    return text.lower()


def esc(value):
    return re.sub(r"[&<>\"']", lambda m: _HTML[m.group()], _nullish_text(value))


def escape_html(value):
    return re.sub(r"[&<>\"']", lambda m: _HTML[m.group()], "" if value is None or value is UNDEFINED else js_to_string(value))


def valid_email(value):
    return bool(_EMAIL.match(js_trim(_or_text(value))))


def label(kind):
    return "7 天後到期" if kind == "seven_days_before" else "今日到期" if kind == "due_today" else "逾期每週提醒"


def to_locale_2(value):
    """
    Number(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })。
    ICU 以數字「最短的十進位表示」（與 JavaScript 的 String(x)、Python 的 repr 相同）四捨五入（half-expand），
    不是 double 的精確值：0.015 → "0.02"（精確值 0.01499… 會得到 0.01，差異測試抓到）。
    """
    x = js_to_number(value)
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "∞" if x > 0 else "-∞"
    d = Decimal(repr(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(abs(d), ",.2f")
    negative = d < 0 or (d == 0 and str(x).startswith("-"))
    return ("-" if negative else "") + text


def message(case_data, kind, items, link_url=ALPHA_LINK_URL, link_text=ALPHA_LINK_TEXT):
    tw_ref = get(case_data, "twRef")
    reference = tw_ref if js_truthy(tw_ref) else "Case #" + _s(get(case_data, "id"))
    rows = []
    for item in items:
        amount = to_locale_2(js_or(get(item, "outstanding"), 0))
        rows.append(f"{_s(get(item, 'installmentLabel'))} · {_s(get(item, 'partyName'))} · {_s(get(item, 'currency'))} {amount} · "
                    f"{_s(get(item, 'dueDate'))} 12:00 (Taiwan)")
    return {
        "subject": f"[Payment {label(kind)}] {_s(reference)}",
        "html": f"<p>案件 <strong>{esc(reference)}</strong> 有以下付款期限項目：</p><ul>{''.join('<li>' + esc(r) + '</li>' for r in rows)}</ul>"
                f"<p><a href=\"{link_url}\">{link_text}</a></p><p style=\"color:#666\">本信由系統自動產生。</p>",
    }


def _name_matches(case_data, personnel):
    target = js_lower(js_trim(_or_text(get(case_data, "ae"))))
    matches = [row for row in personnel if js_lower(js_trim(_or_text(get(row, "name")))) == target]
    if not target or len(matches) != 1:
        return None, ("AE name matches multiple active Personnel records." if len(matches) > 1
                      else "AE does not match one active Personnel record.")
    return matches[0], None


def resolve_recipients(case_data, personnel, finance_emails):
    ae, error = _name_matches(case_data, personnel)
    if error:
        return {"error": error}
    ae_email = js_lower(js_trim(_or_text(get(ae, "email"))))
    supervisor_name = js_trim(_or_text(get(ae, "supervisor_name")))
    supervisor_email = js_lower(js_trim(_or_text(get(ae, "supervisor_email"))))
    if not valid_email(ae_email) or not supervisor_name or not valid_email(supervisor_email):
        return {"error": "AE or supervisor contact fields are incomplete or invalid."}
    if not finance_emails:
        return {"error": "No active Finance Staff or Finance Manager has a valid e-mail."}
    return {"recipients": list(dict.fromkeys([ae_email, supervisor_email, *finance_emails]))}


def finance_emails(personnel):
    return [row.get("email") for row in personnel
            if js_lower(_or_text(get(row, "role_code"))) in ("accounting", "accounting_manager") and valid_email(row.get("email"))]


def due_kind(item, today, success_dates):
    due_date = get(item, "dueDate") if isinstance(item, dict) else UNDEFINED
    outstanding = get(item, "outstanding") if isinstance(item, dict) else UNDEFINED
    if not js_truthy(due_date) or _le(outstanding, 0.004):
        return ""
    days = days_between_dates(today, due_date)
    if days is None:
        return ""
    sd = lambda k: get(success_dates, k)
    truthy = js_truthy
    if 1 <= days <= 7 and not truthy(sd("seven_days_before")):
        return "seven_days_before"
    if -6 <= days <= 0 and not truthy(sd("due_today")) and not truthy(sd("weekly_overdue")):
        return "due_today"
    if days < 0:
        anchor = sd("weekly_overdue") if truthy(sd("weekly_overdue")) else due_date
        due_since = add_calendar_days(anchor, 7)
        if due_since and _s(today) >= due_since:
            return "weekly_overdue"
    return ""


def _le(value, limit):
    """JavaScript 的 value <= limit（非數字先轉數字；NaN 比較都是 false）。"""
    x = js_to_number(value)
    return x == x and x <= limit


# ---------------------------------------------------------------- Signed Slip

def contact_for(case_data, personnel):
    person, error = _name_matches(case_data, personnel)
    if error:
        return {"error": error}
    ae_email = js_trim(_or_text(get(person, "email")))
    supervisor_name = js_trim(_or_text(get(person, "supervisor_name")))
    supervisor_email = js_trim(_or_text(get(person, "supervisor_email")))
    if not valid_email(ae_email) or not supervisor_name or not valid_email(supervisor_email):
        return {"error": "AE or supervisor contact fields are incomplete or invalid."}
    return {"aeEmail": ae_email, "supervisorName": supervisor_name, "supervisorEmail": supervisor_email}


def reminder_message(case_data, due, contact, link_url=ALPHA_LINK_URL, link_text=ALPHA_LINK_TEXT):
    tw_ref = get(case_data, "twRef")
    reference = tw_ref if js_truthy(tw_ref) else f"Case #{_s(get(case_data, 'id'))}"
    missing = get(due, "missing")
    missing = missing if is_array(missing) else []
    ae = js_or(get(case_data, "ae"), "—")
    days_text = _s(get(due, "daysSinceEffective"))
    subject = f"[Signed Slip 逾期警示] {_s(reference)} — 尚缺 {len(missing)} 家再保人簽署文件"
    text = (f"AE {_s(ae)}、{_s(get(contact, 'supervisorName'))} 您好：\n\n"
            f"案件 {_s(reference)} 自保單生效日 {_s(get(case_data, 'policyFrom'))} 起已經過 {days_text} 天，系統仍未收到以下再保人的 Reinsurer Signed Slip：\n"
            f"{chr(10).join('• ' + _s(name) for name in missing)}\n\n"
            "即使已上傳 Reinsurer Confirmation E-mail，Signed Slip 追蹤仍會持續。請完成追蹤並將 Signed Slip 上傳至 Reinsurance Department System。\n\n"
            "本信由系統自動產生。")
    html = (f"<p>AE {escape_html(ae)}、{escape_html(get(contact, 'supervisorName'))} 您好：</p>"
            f"<p>案件 <strong>{escape_html(reference)}</strong> 自保單生效日 {escape_html(get(case_data, 'policyFrom'))} 起已經過 {days_text} 天，"
            f"系統仍未收到以下再保人的 Reinsurer Signed Slip：</p><ul>{''.join(f'<li>{escape_html(name)}</li>' for name in missing)}</ul>"
            "<p>即使已上傳 Reinsurer Confirmation E-mail，Signed Slip 追蹤仍會持續。請完成追蹤並將 Signed Slip 上傳至 Reinsurance Department System。</p>"
            f"<p><a href=\"{link_url}\">{link_text}</a></p><p style=\"color:#666\">本信由系統自動產生。</p>")
    return {"subject": subject, "text": text, "html": html}
