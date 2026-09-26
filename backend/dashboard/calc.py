"""
Dashboard 的計算 - 移植自 Alpha api/dashboard.js（v53，雜湊 26002e5c…）查詢之後的全部邏輯（純函式，不碰資料庫）。

兩個開關（2026-09-26 你的決定；預設值就是 Alpha 的行為，差異測試用預設值與 Alpha 的 JavaScript 逐位比對）：
  - tz：「今天／本月／今年」用哪個時區。Alpha 是 UTC；VM 的 API 傳台北時間。
    （Announce 月取的是傳入文字的前 7 個字，API 會傳台北時間的文字，同 Production Report。）
  - production_rules：每月佣金趨勢與再保人占比改用 Production Report 的規則（VM 的 API 用 True）：
      * 分期金額用 production.calc.installment_allocations（逐期進位到分、尾差放第一期）
      * 批單的業績月用建立月（Alpha 的 Dashboard 用 Announce 月）
      * 再保人名稱去掉「(Facility)」與「[Facility]」（Alpha 的 Dashboard 只去掉前者）
"""
import re
from datetime import datetime, timezone

from cases.calc.jsnum import (
    WS_CLASS, _key_order, get, is_array, js_is_finite, js_num_str, js_or, js_slice, js_spread, js_string_to_number,
    js_to_number, js_to_string, js_trim, js_truthy, js_upper, is_nullish,
)
from cases.calc.payment_terms import build_payment_schedule
from production import calc as production

_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\Z")
_PAREN_FACILITY = re.compile(WS_CLASS + r"*\([Ff][Aa][Cc][Ii][Ll][Ii][Tt][Yy]\)" + WS_CLASS + r"*\Z")


def _u16(text):
    return text.encode("utf-16-be", "surrogatepass")


def number_or_zero(value):
    number = js_string_to_number(("" if is_nullish(value) else js_to_string(value)).replace(",", ""))
    return number if js_is_finite(number) else 0.0


def strip_facility(value, production_rules=False):
    text = js_to_string(js_or(value, ""))
    rx = production._FACILITY if production_rules else _PAREN_FACILITY
    return js_trim(rx.sub("", text, count=1))


def month(value):
    result = js_slice(js_to_string(js_or(value, "")), 0, 7)
    return result if _MONTH.match(result) else ""


def build_rate_lookup(fx_rows, current_month):
    at_or_before, any_latest = {}, {}
    for row in (fx_rows if is_array(fx_rows) else []):
        currency = js_upper(js_to_string(js_or(get(row, "currency"), "")))
        year_month = js_to_string(js_or(get(row, "year_month"), ""))
        rate = js_to_number(get(row, "rate"))
        if not currency or not js_is_finite(rate) or rate <= 0:
            continue
        if currency not in any_latest or _u16(year_month) > _u16(any_latest[currency][0]):
            any_latest[currency] = (year_month, rate)
        if _u16(year_month) <= _u16(current_month) and (currency not in at_or_before or _u16(year_month) > _u16(at_or_before[currency][0])):
            at_or_before[currency] = (year_month, rate)

    def case_rate(payload):
        currency = js_upper(js_to_string(js_or(get(payload, "currency"), "")))
        if currency == "TWD":
            return 1.0
        match = at_or_before.get(currency) or any_latest.get(currency)
        return match[1] if match else 0.0
    return case_rate


def reinsurer_legs(payload, reinsurer):
    order = number_or_zero(get(reinsurer, "sharePct")) / 100
    cedant_premium = number_or_zero(get(payload, "originalPremium")) * order
    leg1 = (cedant_premium - cedant_premium * number_or_zero(get(payload, "riCommPct")) / 100
            - cedant_premium * number_or_zero(get(payload, "taxPct")) / 100)
    reinsurer_premium = number_or_zero(get(reinsurer, "premium")) * order
    leg2 = (reinsurer_premium - reinsurer_premium * number_or_zero(get(reinsurer, "riCommPct")) / 100
            - reinsurer_premium * number_or_zero(get(reinsurer, "taxPct")) / 100)
    return {"cedantPremium": cedant_premium, "brokerage": leg1 - leg2}


def _reinsurers(payload):
    rows = get(payload, "reinsurers")
    return rows if is_array(rows) else []


def installment_income(payload):
    income = 0.0
    for row in _reinsurers(payload):
        income = income + reinsurer_legs(payload, row)["brokerage"]
    effective = month(get(payload, "policyFrom"))
    activity = month(js_or(get(payload, "announcedAt"), get(payload, "postedAt")))
    base = effective if _u16(effective) > _u16(activity) else activity
    if not js_truthy(get(payload, "installmentEnabled")):
        return [{"performanceMonth": base, "income": income}]
    total_premium = number_or_zero(get(payload, "originalPremium"))
    rows = get(payload, "performanceInstallments")
    out = []
    for row in (rows if is_array(rows) else []):
        ratio = number_or_zero(get(row, "ratio")) / 100 if total_premium == 0 else number_or_zero(get(row, "premium")) / total_premium
        out.append({"performanceMonth": month(get(row, "performanceMonth")), "income": income * ratio})
    return out


def top_rows(source, limit):
    entries = [(k, source[k]) for k in _key_order(list(source))]
    entries.sort(key=lambda e: -e[1])   # b[1] - a[1]：由大到小，穩定排序
    selected = entries[:limit]
    other = 0.0
    for _, amount in entries[limit:]:
        other = other + amount
    if other > 0:
        selected.append(("Other", other))
    total = 0.0
    for _, amount in selected:
        total = total + amount
    return [{"name": name, "amount": amount, "pct": amount / total * 100 if total > 0 else 0} for name, amount in selected]


def _ge_text(value, text):
    """value >= text（JavaScript 的比較：字串比 UTF-16；其他型別轉成數字，與日期文字比較一律 false）。"""
    if isinstance(value, str):
        return _u16(value) >= _u16(text)
    if isinstance(value, (list, dict)):
        return _u16(js_to_string(value)) >= _u16(text)
    return False


def _live(row):
    return get(row, "status") in ("posted", "closed") and isinstance(get(row, "status"), str)


def _pad2(n):
    return f"{n:02d}"


def build_dashboard(case_rows, target_rows, fx_rows, now=None, *, tz=timezone.utc, production_rules=False):
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    today = now.strftime("%Y-%m-%d")
    year, month_number = now.year, now.month
    current_month = f"{year}-{_pad2(month_number)}"
    case_rate = build_rate_lookup(fx_rows, current_month)
    rows = []
    for row in case_rows:
        payload = js_spread(js_or(get(row, "payload"), {}))
        payload["announcedAt"] = js_or(get(row, "announced_at"), get(get(row, "payload"), "announcedAt"))
        if production_rules:
            payload["createdAt"] = js_or(get(row, "created_at"), get(get(row, "payload"), "createdAt"))
        rows.append({**row, "payload": payload})
    roots = [r for r in rows if not js_truthy(get(r, "parent_case_id"))]
    active_endorsements = [r for r in rows if js_truthy(get(r, "parent_case_id")) and _live(r)
                           and is_array(get(r["payload"], "endoTypes")) and get(r["payload"], "endoTypes")
                           and js_truthy(get(r["payload"], "policyTo")) and _ge_text(r["payload"]["policyTo"], today)]
    in_force = [r for r in roots if _live(r) and js_truthy(get(r["payload"], "policyTo")) and _ge_text(r["payload"]["policyTo"], today)]

    def posted_month(r):
        return month(js_or(get(r["payload"], "postedAt"), get(r, "announced_at")))

    def ytd(target_year, predicate=None):
        low, high = _u16(f"{js_num_str(target_year)}-01"), _u16(f"{js_num_str(target_year)}-{_pad2(month_number)}")
        return len([r for r in roots if _live(r) and _u16(posted_month(r)) >= low and _u16(posted_month(r)) <= high
                    and (predicate is None or predicate(r["payload"]))])

    ytd_current, ytd_prior = ytd(year), ytd(year - 1)
    renewals_ytd = ytd(year, lambda p: get(p, "newOrRenew") == "Renew")
    renewals_mtd = len([r for r in roots if _live(r) and get(r["payload"], "newOrRenew") == "Renew" and posted_month(r) == current_month])
    expected_renewals_mtd = len([r for r in roots if _live(r) and month(get(r["payload"], "policyTo")) == current_month])
    new_business_mtd = len([r for r in roots if _live(r) and get(r["payload"], "newOrRenew") == "New" and posted_month(r) == current_month])

    gross = out1 = out2 = 0.0
    class_totals, reinsurer_totals = {}, {}
    for r in in_force:
        payload = r["payload"]
        rate = case_rate(payload)
        for reinsurer in _reinsurers(payload):
            amount = reinsurer_legs(payload, reinsurer)["cedantPremium"] * rate
            gross += amount
            class_name = js_to_string(js_or(get(payload, "classOfBusiness"), "Unclassified"))
            class_totals[class_name] = class_totals.get(class_name, 0.0) + amount
            name = js_or(strip_facility(get(reinsurer, "name"), production_rules), "Unnamed")
            reinsurer_totals[name] = reinsurer_totals.get(name, 0.0) + amount
    for r in in_force + active_endorsements:
        rate = case_rate(r["payload"])
        totals = build_payment_schedule(r["payload"], now)["totals"]
        out1 += totals["cedantOutstanding"] * rate
        out2 += totals["reinsurerOutstanding"] * rate

    monthly = {f"{y}-{_pad2(m)}": 0.0 for y in (year - 1, year) for m in range(1, 13)}
    for r in rows:
        if not _live(r):
            continue
        rate = case_rate(r["payload"])
        entries = production.installment_allocations(r["payload"]) if production_rules else installment_income(r["payload"])
        for entry in entries:
            if entry["performanceMonth"] in monthly:
                monthly[entry["performanceMonth"]] += entry["income"] * rate

    targets_annual, targets_monthly = None, {}
    for t in target_rows:
        if get(t, "period_type") == "annual" and get(t, "period_key") == str(year):
            targets_annual = js_to_number(get(t, "amount"))
        if get(t, "period_type") == "monthly":
            targets_monthly[js_to_string(get(t, "period_key"))] = js_to_number(get(t, "amount"))

    months = [_pad2(i + 1) for i in range(month_number)]
    return {
        "ok": True,
        "period": {"year": year, "currentMonth": current_month, "monthNumber": month_number},
        "metrics": {
            "ytdCurrent": ytd_current, "ytdPrior": ytd_prior, "renewalsMtd": renewals_mtd,
            "expectedRenewalsMtd": expected_renewals_mtd, "newBusinessMtd": new_business_mtd,
            "inForcePolicies": len(in_force), "activeEndorsements": len(active_endorsements),
            "openQuotes": len([r for r in roots if get(r, "status") == "draft"]),
            "retentionRatio": renewals_ytd / ytd_prior * 100 if ytd_prior > 0 else None,
            "grossPremiumNtd": gross, "outstandingLeg1Ntd": out1, "outstandingLeg2Ntd": out2,
        },
        "brokerage": {
            "labels": months,
            "current": [monthly[f"{year}-{m}"] for m in months],
            "prior": [monthly[f"{year - 1}-{m}"] for m in months],
            "target": [js_or(targets_monthly.get(f"{year}-{m}"), 0) for m in months],
            "annualTarget": targets_annual,
        },
        "classMix": top_rows(class_totals, 5),
        "reinsurers": top_rows(reinsurer_totals, 6),
    }
