"""
Dashboard 的計算 - 移植自 Alpha api/dashboard.js（v53，雜湊 26002e5c…）查詢之後的全部邏輯（純函式，不碰資料庫）。

兩個開關（2026-09-26 你的決定）。預設值是 Alpha v53 的行為；Alpha v57 起與 VM 的 API 相同（台北時間＋production_rules），
差異測試也改用這個模式與 Alpha v57 的 JavaScript 逐位比對（qa/calc/compare.py 的 _dashboard_vm）：
  - tz：「今天／本月／今年」用哪個時區。Alpha 是 UTC；VM 的 API 傳台北時間。
    （Announce 月取的是傳入文字的前 7 個字，API 會傳台北時間的文字，同 Production Report。）
  - production_rules：每月佣金趨勢與再保人占比改用 Production Report 的規則（VM 的 API 用 True）：
      * 分期金額用 production.calc.installment_allocations（逐期進位到分、尾差放第一期）
      * 批單的業績月用建立月（Alpha 的 Dashboard 用 Announce 月）
      * 再保人名稱去掉「(Facility)」與「[Facility]」（Alpha 的 Dashboard 只去掉前者）
"""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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


def build_month_rate_lookup(fx_rows):
    """(幣別, 月份) → 匯率：該月以前最新的一筆；那個月以前完全沒有時用任何月份中最新的一筆；沒有這個幣別的匯率回傳 0。
    2026-11-26 業主決定：Total Gross Premium 的每張保單用它認列月的匯率（不再全部用最新匯率）。同月重複時取先出現的（同 build_rate_lookup）。"""
    from bisect import bisect_right
    table = {}
    for row in (fx_rows if is_array(fx_rows) else []):
        currency = js_upper(js_to_string(js_or(get(row, "currency"), "")))
        year_month = js_to_string(js_or(get(row, "year_month"), ""))
        rate = js_to_number(get(row, "rate"))
        if not currency or not js_is_finite(rate) or rate <= 0:
            continue
        table.setdefault(currency, {}).setdefault(year_month, rate)
    sorted_table = {c: ([m for m in sorted(rows, key=_u16)], rows) for c, rows in table.items()}

    def rate_at(currency, month):
        if currency == "TWD":
            return 1.0
        entry = sorted_table.get(currency)
        if not entry:
            return 0.0
        months, rows = entry
        i = bisect_right([_u16(m) for m in months], _u16(month or "")) - 1
        return rows[months[i]] if i >= 0 else rows[months[-1]]
    return rate_at


def reinsurer_legs(payload, reinsurer):
    from cases.oversea import enabled as oversea_enabled, legs as oversea_legs
    if oversea_enabled(payload):
        result = oversea_legs(payload,reinsurer)
        return {'cedantPremium': result['cp'], 'brokerage': result['brokerage']}
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
    from cases.oversea import enabled as oversea_enabled
    if oversea_enabled(payload):
        from production.calc import installment_allocations
        return installment_allocations(payload)
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


MIX_ROWS = 10   # Mix by Class of Business 至少列出的列數（2026-11-26 業主決定）


def class_mix(totals, classes):
    """classes＝啟用中的險種名稱（依 Master Data 順序）。沒傳（None）時維持原本「前 5 名＋Other」。
    有傳時：依金額前 10 名（其餘併入 Other）；有金額的不足 10 個時，依 classes 順序補 0% 到 10 列。完全沒有金額時不補（畫面顯示沒有資料）。"""
    if classes is None:
        return top_rows(totals, 5)
    rows = top_rows(totals, MIX_ROWS)
    if not any(amount > 0 for amount in totals.values()):
        return rows
    present = {str(name).strip().casefold() for name in totals}
    for name in classes:
        if len(rows) >= MIX_ROWS:
            break
        key = str(name).strip().casefold()
        if key and key not in present:
            present.add(key)
            rows.append({"name": name, "amount": 0.0, "pct": 0})
    return rows


def _ge_text(value, text):
    """value >= text（JavaScript 的比較：字串比 UTF-16；其他型別轉成數字，與日期文字比較一律 false）。"""
    if isinstance(value, str):
        return _u16(value) >= _u16(text)
    if isinstance(value, (list, dict)):
        return _u16(js_to_string(value)) >= _u16(text)
    return False


def _live(row):
    return get(row, "status") in ("posted", "closed") and isinstance(get(row, "status"), str)


OUTSTANDING_YEARS = 5
_TAIPEI = ZoneInfo("Asia/Taipei")


def _taipei_day(value):
    """帳款建立時間的台北日期；缺漏或無法解讀回 None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp.date().isoformat()
    return stamp.astimezone(_TAIPEI).date().isoformat()


def _years_before(day_text, years):
    """台北今天往回 N 年（2/29 往回到非閏年時用 2/28）。"""
    y, m, d = (int(x) for x in day_text.split("-"))
    y -= years
    if m == 2 and d == 29 and not (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)):
        d = 28
    return f"{y:04d}-{m:02d}-{d:02d}"


def _pad2(n):
    return f"{n:02d}"


LEGACY_CLASS_CODES = {'PD': 'Property', 'GL': 'Commercial General Liability'}


def _previous_months(current_month, count):
    """含本月在內往回 count 個月（舊的在前）。"""
    year, number = int(current_month[:4]), int(current_month[5:7])
    result = []
    for _ in range(count):
        result.append(f"{year:04d}-{number:02d}")
        number -= 1
        if number == 0:
            year, number = year - 1, 12
    return list(reversed(result))


def _insights(extras_inputs):
    """趨勢圖與統計卡的補充資料（2026-11-25）：全部由 build_dashboard 已算好的資料整理，不改任何既有數字。
      - brokerage.prior2：前前年每月佣金（與 prior、current 同一套規則；已結算月份用 Production 關帳數字）
      - byClass：每月佣金按險種拆分；前 5 大險種各一列，其餘（含舊資料與 Facility 沒有險種的收入）併入 Other，
        各險種加總永遠等於當月總額
      - trends：近 12 個月的新承保件數（bound、new 含舊資料，Total Bound YTD 為今年各月 bound 加總；renew 只算新系統）
      - reinsurersByCases：在保保單件數的再保人排行（新系統保單＋舊資料在保保單，與金額榜同一批）
      - outstandingByCurrency（2026-11-26）：未結清應收／應付與其中的逾期，依原幣別分開（不換匯；台幣在前、其他幣別依代碼排序；Accounting · Receivable / Payable 小卡用）
      - overdueOutstanding（2026-11-26）：Accounting · Receivable / Payable 中已逾期的應收與應付（台幣；實際到期日早於今天、同一批帳款與匯率，是兩個總額的一部分）
      - grossPremiumUsd（2026-11-26）：Total Gross Premium 的美金對照；每張保單用認列月匯率換成台幣、再用同一個月的 USD 匯率換成美金後加總（沒有任何 USD 匯率時為 None）
    """
    x = extras_inputs
    monthly, class_monthly, other = x['monthly'], x['class_monthly'], x['OTHER']
    trend_year, months = x['trend_year'], x['months']

    def series(year):
        return [monthly[f"{year}-{m}"] for m in months]

    def status(year):
        return ["closed" if f"{year}-{m}" in x['closed_months'] or production.is_historical(f"{year}-{m}") else "estimated" for m in months]

    # 險種：以三年合計排名，前 5 名各自一列，其餘併入 Other
    totals = {}
    for key, bucket in class_monthly.items():
        for name, amount in bucket.items():
            if name != other:
                totals[name] = totals.get(name, 0.0) + amount
    ranked = [n for n, _ in sorted(totals.items(), key=lambda e: (-e[1], e[0])) if totals[n] > 0][:5]
    names = ranked + ["Other"]

    def by_class(year):
        out = {name: [] for name in names}
        for m in months:
            key = f"{year}-{m}"
            named = 0.0
            for name in ranked:
                value = class_monthly[key].get(name, 0.0)
                named += value
                out[name].append(value)
            rest = monthly[key] - named   # 其餘＝總額減去前 5 名，加總永遠對得上
            out["Other"].append(0.0 if abs(rest) < 0.005 else rest)
        return out

    # 近 12 個月件數
    window = _previous_months(x['current_month'], 12)
    bound = {m: 0 for m in window}
    renew = {m: 0 for m in window}
    new = {m: 0 for m in window}
    for r in x['roots']:
        if not x['live'](r):
            continue
        key = x['posted_month'](r)
        if key in bound:
            bound[key] += 1
            kind = get(r["payload"], "newOrRenew")
            if kind == "Renew":
                renew[key] += 1
            elif kind == "New":
                new[key] += 1
    for b in x['legacy_bound']:
        key = b["month"][:7]
        if key in bound:
            bound[key] += 1
            if b["newOrRenew"] == "New":
                new[key] += 1   # 續保件數只算新系統（與 Renewals Bound MTD 同一口徑），舊資料不加

    # 再保人件數：由多到少，同件數維持與金額榜相同的名稱順序；前 6 名＋其餘併成 Other（其餘的件數是聯集，不重複計算）
    cases = x['reinsurer_cases']
    ordered = sorted(((name, len(cases[name])) for name in _key_order(list(cases))), key=lambda e: -e[1])
    top, rest = ordered[:6], ordered[6:]
    rows = [{"name": name, "cases": count} for name, count in top]
    if rest:
        union = set()
        for name, _ in rest:
            union |= cases[name]
        rows.append({"name": "Other", "cases": len(union)})
    everyone = set()
    for policies in cases.values():
        everyone |= policies
    return {
        "brokerage": {"prior2": series(trend_year - 2), "prior2Status": status(trend_year - 2),
                      "byClass": {"names": names, "current": by_class(trend_year), "prior": by_class(trend_year - 1), "prior2": by_class(trend_year - 2)}},
        "trends": {"months": window, "bound": [bound[m] for m in window], "renew": [renew[m] for m in window], "new": [new[m] for m in window]},
        "reinsurersByCases": {"rows": rows, "policies": len(everyone)},
        "overdueOutstanding": {"receivable": x['overdue1'], "payable": x['overdue2']},
        "outstandingByCurrency": [{"currency": c, "receivable": v[0], "payable": v[1], "overdueReceivable": v[2], "overduePayable": v[3]}
                                  for c, v in sorted(x['by_currency'].items(), key=lambda e: (e[0] != 'TWD', e[0]))],
        "grossPremiumUsd": ({"amount": x['gross_usd'], "basis": "recognition-month"} if x['usd_available'] else None),
    }


def build_dashboard(case_rows, target_rows, fx_rows, now=None, *, tz=timezone.utc, production_rules=False, closed_reports=None, brokerage_year=None, legacy=None, facility_trend=None, extras=None, mix_classes=None):
    """extras（2026-11-25）：傳入 dict 時，另外把趨勢圖與統計卡的補充資料（前前年對照、險種逐月、近 12 個月件數、再保人件數）填進去；
    回傳值與不傳 extras 時逐位元組相同。"""
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    today = now.strftime("%Y-%m-%d")
    year, month_number = now.year, now.month
    current_month = f"{year}-{_pad2(month_number)}"
    case_rate = build_rate_lookup(fx_rows, current_month)
    month_rate = build_month_rate_lookup(fx_rows)
    rows = []
    data_errors=[]
    from cases.data_integrity import financial_issues
    for row in case_rows:
        integrity=financial_issues(get(row,"payload"))
        if integrity:data_errors.append({"caseId":get(row,"id"),"issues":integrity})
        payload = js_spread(js_or(get(row, "payload"), {}))
        payload["announcedAt"] = js_or(get(row, "announced_at"), get(get(row, "payload"), "announcedAt"))
        if production_rules:
            payload["createdAt"] = js_or(get(row, "created_at"), get(get(row, "payload"), "createdAt"))
        rows.append({**row, "payload": payload, **({"_financialInvalid":True} if integrity else {})})
    roots = [r for r in rows if not js_truthy(get(r, "parent_case_id"))]
    active_endorsements = [r for r in rows if js_truthy(get(r, "parent_case_id")) and _live(r)
                           and is_array(get(r["payload"], "endoTypes")) and get(r["payload"], "endoTypes")
                           and js_truthy(get(r["payload"], "policyTo")) and _ge_text(r["payload"]["policyTo"], today)]
    # Follow-up C (2026-11-14): a policy's period ends at the latest Announced
    # endorsement expiry; Gross Premium, In-Force and Expected Renewals share it.
    latest_to = {}
    for r in rows:
        parent = get(r, "parent_case_id")
        expiry = get(r["payload"], "policyTo")
        if js_truthy(parent) and _live(r) and isinstance(expiry, str) and expiry:
            if expiry > latest_to.get(parent, ""):
                latest_to[parent] = expiry
    def policy_to(r):
        own = get(r["payload"], "policyTo")
        own = own if isinstance(own, str) else ""
        later = latest_to.get(get(r, "id"), "")
        return later if later > own else own
    in_force = [r for r in roots if _live(r) and policy_to(r) and _ge_text(policy_to(r), today)]

    def posted_month(r):
        return month(js_or(get(r["payload"], "postedAt"), get(r, "announced_at")))

    def ytd(target_year, predicate=None):
        low, high = _u16(f"{js_num_str(target_year)}-01"), _u16(f"{js_num_str(target_year)}-{_pad2(month_number)}")
        return len([r for r in roots if _live(r) and _u16(posted_month(r)) >= low and _u16(posted_month(r)) <= high
                    and (predicate is None or predicate(r["payload"]))])

    ytd_current, ytd_prior = ytd(year), ytd(year - 1)
    renewals_ytd = ytd(year, lambda p: get(p, "newOrRenew") == "Renew")
    renewals_mtd = len([r for r in roots if _live(r) and get(r["payload"], "newOrRenew") == "Renew" and posted_month(r) == current_month])
    expected_renewals_mtd = len([r for r in roots if _live(r) and month(policy_to(r)) == current_month])
    new_business_mtd = len([r for r in roots if _live(r) and get(r["payload"], "newOrRenew") == "New" and posted_month(r) == current_month])
    # 2026-11-19 owner: legacy policies (company-wide Dashboard) count by Revenue Month and New / Renew.
    bound = [b for b in (legacy or {}).get("bound", []) if isinstance(b.get("month"), str)]
    def legacy_ytd(target_year, kind=None):
        low, high = f"{js_num_str(target_year)}-01", f"{js_num_str(target_year)}-{_pad2(month_number)}"
        return len([b for b in bound if low <= b["month"][:7] <= high and (kind is None or b["newOrRenew"] == kind)])
    # 2026-11-26 owner: Renewals Bound MTD, Expected Renewals MTD and the Retention Ratio count the new system only
    # (legacy policies still count in Total Bound YTD, Prior-Year YTD and New Business MTD).
    ytd_prior_new_system = ytd_prior
    ytd_current += legacy_ytd(year); ytd_prior += legacy_ytd(year - 1)
    new_business_mtd += len([b for b in bound if b["month"][:7] == current_month and b["newOrRenew"] == "New"])

    gross = out1 = out2 = 0.0
    by_currency = {}   # extras：幣別 → [應收, 應付, 逾期應收, 逾期應付]（原幣別金額，不換匯；與 out1／out2 同一批帳款與 5 年窗口，缺匯率的也計入）
    def add_outstanding(cur, direction, amount, late):
        row = by_currency.setdefault(str(cur or 'TWD').upper(), [0.0, 0.0, 0.0, 0.0])
        i = 0 if direction == 'receivable' else 1
        row[i] += amount
        if late:
            row[2 + i] += amount
    overdue1 = overdue2 = 0.0   # extras：未結清應收／應付中「實際到期日早於今天」的部分（2026-11-26 業主決定；是 out1／out2 的子集）
    gross_usd = 0.0   # extras：每張保單用認列月匯率換成台幣、再用同月的 USD 匯率換成美金後加總
    class_totals, reinsurer_totals = {}, {}
    reinsurer_cases = {}   # extras：再保人 → 參與的在保保單（新系統用保單的根案件 id，舊資料用清單序號）
    # Problem 3 (2026-11-13): Gross Premium uses the stepwise-rounded ceded premium
    # (same as Accounting) and includes Announced endorsements of in-force policies.
    from cases.calc.accounting import calc_legs_for_reinsurer
    in_force_ids = {get(r, "id") for r in in_force}
    contributors = in_force + [r for r in rows if js_truthy(get(r, "parent_case_id")) and _live(r)
                               and get(r, "parent_case_id") in in_force_ids]
    for r in contributors:
        if r.get("_financialInvalid"):continue
        payload = r["payload"]
        if production_rules:
            # 2026-11-26 owner: each policy converts at the rate of its recognition month (Production's base month; legacy uses its Revenue Month)
            recognition = production.base_month(payload)
            recognition = production.effective_month(recognition) if recognition else current_month
            rate = month_rate(js_upper(js_to_string(js_or(get(payload, "currency"), ""))), recognition)
            usd_rate_here = month_rate("USD", recognition)
        else:
            rate, usd_rate_here = case_rate(payload), 0.0
        for reinsurer in _reinsurers(payload):
            amount = calc_legs_for_reinsurer(payload, reinsurer)["cp"] * rate
            gross += amount
            if usd_rate_here > 0:
                gross_usd += amount / usd_rate_here
            class_name = js_to_string(js_or(get(payload, "classOfBusiness"), "Unclassified"))
            class_totals[class_name] = class_totals.get(class_name, 0.0) + amount
            name = js_or(strip_facility(get(reinsurer, "name"), production_rules), "Unnamed")
            reinsurer_totals[name] = reinsurer_totals.get(name, 0.0) + amount
            if extras is not None:
                reinsurer_cases.setdefault(name, set()).add(("case", get(r, "parent_case_id") or get(r, "id")))
    legacy_in_force = legacy_renewals = 0
    for policy_index, policy in enumerate((legacy or {}).get("policies", [])):
        expiry = policy.get("expiry") or ""
        if month(expiry) == current_month:
            legacy_renewals += 1
        if not expiry or not _ge_text(expiry, today):
            continue
        legacy_in_force += 1
        for item in policy.get("items", []):
            if production_rules:
                item_currency = js_upper(js_to_string(js_or(item.get("currency"), "")))
                item_month = item.get("month") or current_month
                amount = number_or_zero(item.get("premium")) * month_rate(item_currency, item_month)
                item_usd = month_rate("USD", item_month)
                if item_usd > 0:
                    gross_usd += amount / item_usd
            else:
                amount = number_or_zero(item.get("premium")) * case_rate({"currency": item.get("currency")})
            gross += amount
            class_totals[item["className"]] = class_totals.get(item["className"], 0.0) + amount
            name = js_or(strip_facility(item.get("party"), production_rules), "Unnamed")
            reinsurer_totals[name] = reinsurer_totals.get(name, 0.0) + amount
            if extras is not None:
                reinsurer_cases.setdefault(name, set()).add(("legacy", policy_index))
    # 2026-11-19 owner: legacy endorsements still in force (company-wide Dashboard).
    legacy_active_endorsements = len([e for e in (legacy or {}).get("endorsements", [])
                                      if isinstance(e.get("expiry"), str) and e["expiry"] and _ge_text(e["expiry"], today)])
    # Accounting obligations remain outstanding after policy expiry. Convert each
    # at its own posting month; unknown FX stays visibly incomplete, never zero.
    from cases.cash_ledger import transaction_details
    from cases.case_result_cache import cached as cached_case_result
    from cases.accounting_policy import stored_all_settled
    rates = {(r['year_month'], r['currency']): float(r['rate']) for r in fx_rows}
    missing_fx = []
    claim_outstanding = {}
    estimated_fx = []
    from cases.accounting_policy import latest_rates
    latest = latest_rates(fx_rows, current_month)
    # 2026-10-29 業主：未結清應收／應付只算 5 年內建立的帳款（正常 2 年內結清）。往回 5 年、每天滾動（台北今天）。
    # 每筆帳款看它自己建立的時間（createdAt，台北日期）：保費帳款是 Announce 時、理賠帳款是記錄理賠付款時。
    # 建立時間缺漏或無法解讀的照算（不藏欠款）。
    outstanding_since = _years_before(today, OUTSTANDING_YEARS)
    def recent(tx):
        day = _taipei_day(tx.get('createdAt'))
        return day is None or day >= outstanding_since
    for r in rows:
        if r.get("_financialInvalid"):continue
        if r.get("status") not in ("posted", "closed", "reversed"):
            continue
        payload = r['payload']
        live_txs = [t for t in payload.get('transactions', []) if isinstance(t, dict)] if isinstance(payload.get('transactions'), list) else []
        if live_txs and not any(recent(t) for t in live_txs):
            continue   # 這件案件的帳款全都超過 5 年：不計算
        if stored_all_settled(payload):
            continue   # 2026-10-29 業主：整件都已銷帳（依帳款標記）就不重算；標記是否正確由 Accounting 每次核對
        case_currency = str(payload.get('currency') or 'TWD').upper()
        stored = {t.get('txNo'): t for t in payload.get('transactions', []) if isinstance(t, dict)}
        # 2026-10-29：與 Accounting 共用每件案件記住的答案（同一份資料、同一個台北日期才共用），見 cases/case_result_cache
        for no, detail in cached_case_result('details', payload, now, lambda: transaction_details(payload, now)).items():
            tx = stored.get(no, {})
            if tx.get('reversed') or tx.get('isReversalEntry') or detail['cashTracking'] == 'derived' or abs(detail['outstanding']) < .005:
                continue
            if not recent(tx):
                continue
            # Conflict 2 (2026-11-15): every Claim is converted into the TWD totals at its
            # own currency and posting month (Accounting keeps its 11-14 display).
            currency = str(tx.get('currency') or case_currency).upper() if tx.get('source') == 'claim' else case_currency
            # 逾期＝實際到期日（合約到期日，沒有就用到期日；與 Accounting 同一規則）早於今天（台北日期）；到期當天不算，沒有到期日不算
            due_day = str(detail.get('contractDueDate') or detail.get('dueDate') or '')[:10]
            late = bool(due_day) and due_day < today
            add_outstanding(currency, detail['paymentDirection'], abs(detail['outstanding']), late)
            from cases.accounting_policy import fx_for_transaction
            rate,posting_month,estimated=fx_for_transaction(payload,tx,rates,latest)
            if estimated:estimated_fx.append({'currency':currency,'month':posting_month or None,'caseId':r.get('id'),'txNo':no})
            if rate is None:
                missing_fx.append({'currency': currency, 'month': posting_month or None, 'caseId': r.get('id')})
                continue
            value = abs(detail['outstanding']) * rate
            if detail['paymentDirection'] == 'receivable':
                out1 += value
                if late:
                    overdue1 += value
            else:
                out2 += value
                if late:
                    overdue2 += value

    for item in (legacy or {}).get("outstanding", []):
        if item.get("ageDate") and item["ageDate"] < outstanding_since:
            continue
        cur = item.get("currency") or "TWD"
        add_outstanding(cur, item.get("paymentDirection"), item["outstanding"], bool(item.get("due")) and str(item["due"])[:10] < today)
        if cur == "TWD":
            rate = 1
        elif item.get("postedRate"):
            rate = item["postedRate"]
        elif rates.get((item.get("postedMonth"), cur)):
            rate = rates[(item["postedMonth"], cur)]
        elif latest.get(cur):
            rate = latest[cur][1]
            estimated_fx.append({'currency': cur, 'month': latest[cur][0], 'caseId': None, 'txNo': item.get('txNo')})
        else:
            missing_fx.append({'currency': cur, 'month': item.get('postedMonth') or None, 'caseId': None})
            continue
        value = item["outstanding"] * rate
        late = bool(item.get("due")) and str(item["due"])[:10] < today
        if item.get("paymentDirection") == "receivable":
            out1 += value
            if late:
                overdue1 += value
        else:
            out2 += value
            if late:
                overdue2 += value

    trend_year = year if brokerage_year is None else brokerage_year
    trend_months = month_number if trend_year == year else 12
    trend_years = (trend_year - 2, trend_year - 1, trend_year) if extras is not None else (trend_year - 1, trend_year)
    monthly = {f"{y}-{_pad2(m)}": 0.0 for y in trend_years for m in range(1, 13)}
    OTHER = '__other__'
    class_monthly = {k: {} for k in monthly} if extras is not None else None
    class_of_case = {str(r.get('id')): js_to_string(js_or(get(r['payload'], 'classOfBusiness'), 'Unclassified')) for r in rows} if extras is not None else {}
    def add_class(month_key, class_name, amount):
        bucket = class_monthly[month_key]
        bucket[class_name] = bucket.get(class_name, 0.0) + amount
    for r in rows:
        if r.get("_financialInvalid"):continue
        if not _live(r):
            continue
        if r['payload'].get('reinsuranceStructure') == 'FACILITY':
            continue
        rate = case_rate(r["payload"])
        entries = production.installment_allocations(r["payload"]) if production_rules else installment_income(r["payload"])
        for entry in entries:
            # 2026-11-15: new-system production before the start month is recognized in the start month.
            entry_month = production.effective_month(entry["performanceMonth"]) if production_rules else entry["performanceMonth"]
            if entry_month in monthly:
                monthly[entry_month] += entry["income"] * rate
                if extras is not None:
                    add_class(entry_month, class_of_case.get(str(r.get('id'))) or OTHER, entry["income"] * rate)

    for entry in (legacy or {}).get("trend", []):
        if entry.get("month") in monthly and entry.get("incomeTwd") is not None:
            monthly[entry["month"]] += number_or_zero(entry["incomeTwd"])
            if extras is not None:
                add_class(entry["month"], entry.get("className") or OTHER, number_or_zero(entry["incomeTwd"]))

    for entry in facility_trend or []:
        if entry.get('month') in monthly and entry.get('incomeTwd') is not None:
            monthly[entry['month']] += number_or_zero(entry['incomeTwd'])
            if extras is not None:
                add_class(entry['month'], class_of_case.get(str(entry.get('caseId'))) or OTHER, number_or_zero(entry['incomeTwd']))

    closed_months = set()
    visible_ids = {str(r.get('id')) for r in rows}
    for report in closed_reports or []:
        report_month = report.get('year_month') or report.get('month')
        if report_month in monthly:
            closed_months.add(report_month)
            monthly[report_month] = sum(number_or_zero(row.get('income')) for row in report.get('rows', [])
                                        if str(row.get('caseId')) in visible_ids
                                        or (legacy is not None and str(row.get('caseId') or '').startswith('legacy:')))
            if extras is not None:
                class_monthly[report_month] = {}
                for row in report.get('rows', []):
                    case_key = str(row.get('caseId') or '')
                    if case_key in visible_ids:
                        add_class(report_month, class_of_case.get(case_key) or OTHER, number_or_zero(row.get('income')))
                    elif legacy is not None and case_key.startswith('legacy:'):
                        add_class(report_month, LEGACY_CLASS_CODES.get(str(row.get('classCode') or '').upper()) or OTHER, number_or_zero(row.get('income')))

    targets_annual, targets_monthly = None, {}
    for t in target_rows:
        if get(t, "period_type") == "annual" and get(t, "period_key") == str(trend_year):
            targets_annual = js_to_number(get(t, "amount"))
        if get(t, "period_type") == "monthly":
            targets_monthly[js_to_string(get(t, "period_key"))] = js_to_number(get(t, "amount"))

    months = [_pad2(i + 1) for i in range(trend_months)]
    if extras is not None:
        extras.update(_insights(extras_inputs={
            'monthly': monthly, 'class_monthly': class_monthly, 'OTHER': OTHER, 'trend_year': trend_year, 'months': months,
            'closed_months': closed_months, 'reinsurer_cases': reinsurer_cases, 'roots': roots, 'live': _live, 'posted_month': posted_month,
            'legacy_bound': bound, 'current_month': current_month, 'in_force_count': len(in_force), 'overdue1': overdue1, 'overdue2': overdue2, 'by_currency': by_currency, 'gross_usd': gross_usd, 'usd_available': month_rate('USD', current_month) > 0,
        }))
    return {
        "ok": True,
        "period": {"year": year, "currentMonth": current_month, "monthNumber": month_number},
        "metrics": {
            "ytdCurrent": ytd_current, "ytdPrior": ytd_prior, "renewalsMtd": renewals_mtd,
            "expectedRenewalsMtd": expected_renewals_mtd, "newBusinessMtd": new_business_mtd,
            "inForcePolicies": len(in_force) + legacy_in_force, "activeEndorsements": len(active_endorsements) + legacy_active_endorsements,
            "openQuotes": len([r for r in roots if get(r, "status") == "draft"]),
            "retentionRatio": renewals_ytd / ytd_prior_new_system * 100 if ytd_prior_new_system > 0 else None,
            "grossPremiumNtd": gross, "outstandingLeg1Ntd": out1, "outstandingLeg2Ntd": out2, "outstandingSince": outstanding_since,
            "claimOutstandingByCurrency": [dict(currency=key, receivable=round(group['receivable'], 2), payable=round(group['payable'], 2)) for key, group in sorted(claim_outstanding.items())],
            "accountingTotalIncomplete": bool(missing_fx or data_errors), "missingPostingRates": missing_fx,
            "accountingTotalEstimated":bool(estimated_fx), "estimatedPostingRates":estimated_fx,
            **({"dataErrors":data_errors} if data_errors else {}),
        },
        "brokerage": {
            "labels": months,
            "currentStatus": ["closed" if f"{trend_year}-{m}" in closed_months or production.is_historical(f"{trend_year}-{m}") else "estimated" for m in months],
            "priorStatus": ["closed" if f"{trend_year-1}-{m}" in closed_months or production.is_historical(f"{trend_year-1}-{m}") else "estimated" for m in months],
            "current": [monthly[f"{trend_year}-{m}"] for m in months],
            "prior": [monthly[f"{trend_year - 1}-{m}"] for m in months],
            "target": [js_or(targets_monthly.get(f"{trend_year}-{m}"), 0) for m in months],
            "annualTarget": targets_annual,
        },
        "classMix": class_mix(class_totals, mix_classes),
        "reinsurers": top_rows(reinsurer_totals, 6),
    }
