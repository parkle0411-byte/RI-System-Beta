"""
Production Report 的計算 - 逐函式移植自 Alpha lib/production-report.js（v53，雜湊 4474c028…）。

與 Alpha 的 JavaScript 逐位一致（scripts/run_qa.sh calc 的差異測試）。JavaScript 特有的行為：
  - Number(String(x).replace(/,/g, ''))、Math.round（.5 往正無限大）、數字轉文字（jsnum.py）
  - Date.UTC 把 0–99 年當成 1900–1999；toISOString 超過 9999 年是 +YYYYYY
  - 正則的 \\d 與 /i 只對 ASCII（Python 的 IGNORECASE 會讓 i 比對到 ı、İ，所以寫成明確的字元類別）；$ 只比對字串結尾
  - localeCompare（js_locale_key）、Array.prototype.sort() 的 UTF-16 順序
這裡不做時區換算：月份是「傳入的文字的前 7 個字」，要用台北時間就由呼叫端傳入台北時間的文字（見 views.py）。
"""
import re

from cases.calc.jsnum import (
    EPSILON, UNDEFINED, WS_CLASS, days_from_civil, get, is_array, is_nullish, iso_date_prefix, js_is_finite,
    js_json_stringify, js_locale_key, js_num_str, js_or, js_round, js_slice, js_spread, js_string_to_number, js_to_number,
    js_to_string, js_trim, js_truthy, js_upper,
)

PRODUCTION_REPORT_HEADERS = [
    "Original Insured", "Reinsured", "Reinsurer / RI Broker", "Class", "Type",
    "Currency", "Exch. Rate", "A/E", "Eff Date", "Exp Date", "Comm (%)",
    "Premium (NTD)", "Income (NTD)", "Policy No", "Endorse No", "Remark", "Tranx Date",
]

_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])\Z")
_ENDORSE_NO = re.compile(r"-([Ee][0-9]+)\Z")
_FACILITY = re.compile(WS_CLASS + r"*[\[(][Ff][Aa][Cc][Ii][Ll][Ii][Tt][Yy][\])]" + WS_CLASS + r"*\Z")


def _js(value):
    """String(value)，null／undefined 也照 JavaScript 轉成文字。"""
    return js_to_string(value)


def number_or_zero(value):
    """Number(String(value ?? '').replace(/,/g, ''))；非有限數字回傳 0。"""
    text = "" if is_nullish(value) else js_to_string(value)
    number = js_string_to_number(text.replace(",", ""))
    return number if js_is_finite(number) else 0.0


def round2(value):
    return js_round((number_or_zero(value) + EPSILON) * 100) / 100


def year_month(value):
    result = js_slice(js_to_string(js_or(value, "")), 0, 7)
    return result if _MONTH.match(result) else ""


def _utc_days(year, month_index, day):
    """Date.UTC(year, monthIndex, day) 的天數（0–99 年視為 1900–1999；月份溢位往後滾）。"""
    if 0 <= year <= 99:
        year += 1900
    year += month_index // 12
    month_index %= 12
    return days_from_civil(year, month_index + 1, 1) + day - 1


def month_end(month):
    match = _MONTH.match(month) if isinstance(month, str) else None
    if not match:
        return ""
    return iso_date_prefix(_utc_days(int(match.group(1)), int(match.group(2)), 0))


def next_production_month(month):
    match = _MONTH.match(month) if isinstance(month, str) else None
    if not match:
        return ""
    return iso_date_prefix(_utc_days(int(match.group(1)), int(match.group(2)), 1))[:7]


def base_month(case_data):
    effective = year_month(get(case_data, "policyFrom"))
    activity_source = get(case_data, "createdAt") if js_truthy(get(case_data, "parentTwRef")) \
        else js_or(get(case_data, "announcedAt"), get(case_data, "postedAt"))
    activity = year_month(activity_source)
    return effective if _utf16(effective) > _utf16(activity) else activity


def _utf16(text):
    return text.encode("utf-16-be", "surrogatepass")


def reinsurer_legs(case_data, reinsurer):
    order = number_or_zero(get(reinsurer, "sharePct")) / 100
    cedant_premium = number_or_zero(get(case_data, "originalPremium")) * order
    cedant_commission = cedant_premium * number_or_zero(get(case_data, "riCommPct")) / 100
    cedant_tax = cedant_premium * number_or_zero(get(case_data, "taxPct")) / 100
    leg1 = cedant_premium - cedant_commission - cedant_tax
    reinsurer_premium = number_or_zero(get(reinsurer, "premium")) * order
    reinsurer_deductions = reinsurer_premium * number_or_zero(get(reinsurer, "riCommPct")) / 100
    reinsurer_tax = reinsurer_premium * number_or_zero(get(reinsurer, "taxPct")) / 100
    leg2 = reinsurer_premium - reinsurer_deductions - reinsurer_tax
    return {"cedantPremium": cedant_premium, "brokerage": leg1 - leg2}


def _reinsurers(case_data):
    rows = get(case_data, "reinsurers")
    return rows if is_array(rows) else []


def total_income(case_data):
    total = 0.0
    for reinsurer in _reinsurers(case_data):
        total = total + reinsurer_legs(case_data, reinsurer)["brokerage"]
    return total


def installment_allocations(case_data):
    total_premium = number_or_zero(get(case_data, "originalPremium"))
    income = total_income(case_data)
    if not js_truthy(get(case_data, "installmentEnabled")):
        return [{"id": "FULL", "performanceMonth": base_month(case_data), "ratio": 1.0, "income": income}]
    source = get(case_data, "performanceInstallments")
    source = source if is_array(source) else []
    rows = []
    for index, row in enumerate(source):
        if total_premium == 0:
            ratio = number_or_zero(get(row, "ratio")) / 100
        else:
            ratio = number_or_zero(get(row, "premium")) / total_premium
        rows.append({"id": _js(js_or(get(row, "id"), f"I{index + 1}")),
                     "performanceMonth": year_month(get(row, "performanceMonth")),
                     "ratio": ratio, "income": round2(income * ratio)})
    if rows:
        allocated = 0.0
        for row in rows:
            allocated = allocated + row["income"]
        tail = round2(income - allocated)
        rows[0]["income"] = round2(rows[0]["income"] + tail)
    return rows


def performance_people(case_data):
    parties = get(case_data, "splitParties")
    if js_truthy(get(case_data, "splitEnabled")) and is_array(parties) and parties:
        return [{"name": _js(js_or(get(p, "name"), get(case_data, "ae"), f"Party {i + 1}")),
                 "pct": number_or_zero(get(p, "pct"))} for i, p in enumerate(parties)]
    return [{"name": _js(js_or(get(case_data, "ae"), "")), "pct": 100.0}]


def rounded_shares(total, people, ae_name):
    rounded = [js_round(number_or_zero(total) * p["pct"] / 100) for p in people]
    allocated = 0.0
    for value in rounded:
        allocated = allocated + value
    delta = js_round(number_or_zero(total)) - allocated
    if js_truthy(delta) and people:
        winner = 0
        for index, person in enumerate(people):
            current = people[winner]
            if person["pct"] > current["pct"] or (person["pct"] == current["pct"]
                                                  and isinstance(ae_name, str) and person["name"] == ae_name):
                winner = index
        rounded[winner] += delta
    return rounded


def rate_for(case_data, month, fx_rates):
    currency = js_upper(_js(js_or(get(case_data, "currency"), "TWD")))
    if currency == "TWD":
        return 1.0
    direct = js_to_number(get(fx_rates, currency))
    monthly = js_to_number(get(get(fx_rates, month), currency))
    rate = monthly if js_is_finite(monthly) and monthly > 0 else direct
    return rate if js_is_finite(rate) and rate > 0 else None


def _row_sort_key(row):
    return tuple(js_locale_key(row[k]) for k in ("originalInsured", "policyNo", "effDate", "reinsurer", "ae"))


def normalize_source(source):
    case_data = js_spread(js_or(get(source, "payload"), source, {}))
    case_data["id"] = js_to_number(js_or(get(source, "id"), get(case_data, "id")))
    case_data["status"] = js_or(get(source, "status"), get(case_data, "status"))
    case_data["twRef"] = js_or(get(source, "twRef"), get(source, "tw_ref"), get(case_data, "twRef"))
    case_data["announcedAt"] = js_or(get(source, "announcedAt"), get(source, "announced_at"), get(case_data, "announcedAt"))
    case_data["createdAt"] = js_or(get(source, "createdAt"), get(source, "created_at"), get(case_data, "createdAt"))
    case_data["caseUid"] = js_or(get(source, "caseUid"), get(source, "case_uid"), get(case_data, "caseUid"))
    case_data["rowVersion"] = js_to_number(js_or(get(source, "rowVersion"), get(source, "row_version"),
                                                 get(case_data, "rowVersion"), 0))
    return case_data


def _nullish_or(a, b):
    """a ?? b"""
    return b if is_nullish(a) else a


def exclusion_matches(exclusion, case_id, key, reinsurer_key, field, value):
    if js_to_number(_nullish_or(get(exclusion, "case_id"), get(exclusion, "caseId"))) != js_to_number(case_id):
        return False
    alternative = "yearMonth" if field == "year_month" else "deferredTo"
    if _js(js_or(_nullish_or(get(exclusion, field), get(exclusion, alternative)), "")) != value:
        return False
    scope = get(exclusion, "scope")
    if scope == "case":
        return _js(js_or(_nullish_or(get(exclusion, "installment_key"), get(exclusion, "installmentKey")), "")) == key
    return scope == "reinsurer" and \
        _js(js_or(_nullish_or(get(exclusion, "reinsurer_key"), get(exclusion, "reinsurerKey")), "")) == reinsurer_key


def exclusion_for(exclusions, case_id, key, reinsurer_key, month):
    return next((row for row in exclusions if exclusion_matches(row, case_id, key, reinsurer_key, "year_month", month)), None)


def deferred_from(exclusions, case_id, key, reinsurer_key, month):
    return any(exclusion_matches(row, case_id, key, reinsurer_key, "deferred_to", month) for row in exclusions)


def confirmed(case_data, key):
    keys = get(case_data, "confirmedProductionKeys")
    return is_array(keys) and any(isinstance(k, str) and k == key for k in keys)


def _income_split(case_data, reinsurers, installment):
    raw = [reinsurer_legs(case_data, r)["brokerage"] * installment["ratio"] for r in reinsurers]
    total = 0.0
    for value in raw:
        total = total + value
    return raw, installment["income"] - total


def production_keys_for_case(source):
    case_data = normalize_source(source)
    keys = []
    reinsurers = _reinsurers(case_data)
    for installment in installment_allocations(case_data):
        if installment["income"] == 0:
            continue
        key = f"{js_num_str(case_data['id'])}:{installment['id']}"
        raw, tail = _income_split(case_data, reinsurers, installment)
        for index in range(len(reinsurers)):
            if raw[index] + (tail if index == 0 else 0) != 0:
                keys.append(f"{key}:R{index}")
    return keys


def production_source_signature(rows):
    return js_json_stringify([[
        get(row, "id"), get(row, "originalInsured"), get(row, "reinsured"), get(row, "reinsurer"), get(row, "classCode"),
        get(row, "type"), get(row, "currency"), get(row, "rate"), get(row, "ae"), get(row, "effDate"), get(row, "expDate"),
        round2(get(row, "comm")), get(row, "premium"), get(row, "income"), get(row, "policyNo"), get(row, "endorseNo"),
        get(row, "remark"), get(row, "tranxDate"),
    ] for row in (rows if is_array(rows) else [])])


def build_production_preview(case_rows, month, fx_rates=UNDEFINED, exclusions=UNDEFINED):
    fx_rates = {} if fx_rates is UNDEFINED else fx_rates
    exclusions = [] if exclusions is UNDEFINED else exclusions
    if not _MONTH.match(_js(js_or(month, ""))):
        return {"errors": ["Report month must use YYYY-MM."], "rows": [], "excluded": [], "missingRateCurrencies": []}
    rows, excluded_rows, missing_rates = [], [], []
    for source in (case_rows if is_array(case_rows) else []):
        case_data = normalize_source(source)
        if case_data["status"] not in ("posted", "closed", "reversed") or not isinstance(case_data["status"], str):
            continue
        reinsurers = _reinsurers(case_data)
        people = performance_people(case_data)
        case_id = case_data["id"]
        for installment_index, installment in enumerate(installment_allocations(case_data)):
            key = f"{js_num_str(case_id)}:{installment['id']}"
            belongs = installment["performanceMonth"] == month
            raw, tail = _income_split(case_data, reinsurers, installment)
            for reinsurer_index, reinsurer in enumerate(reinsurers):
                reinsurer_key = f"{key}:R{reinsurer_index}"
                if confirmed(case_data, reinsurer_key):
                    continue
                if not belongs and not deferred_from(exclusions, case_id, key, reinsurer_key, month):
                    continue
                exclusion = exclusion_for(exclusions, case_id, key, reinsurer_key, month)
                legs = reinsurer_legs(case_data, reinsurer)
                source_premium = legs["cedantPremium"] * installment["ratio"]
                source_income = raw[reinsurer_index] + (tail if reinsurer_index == 0 else 0)
                if source_income == 0:
                    continue
                rate = rate_for(case_data, month, fx_rates)
                currency = js_upper(_js(js_or(get(case_data, "currency"), "TWD")))
                if rate is None and currency not in missing_rates:
                    missing_rates.append(currency)
                ae = get(case_data, "ae")
                premiums = [None] * len(people) if rate is None else rounded_shares(source_premium * rate, people, ae)
                incomes = [None] * len(people) if rate is None else rounded_shares(source_income * rate, people, ae)
                endorse = None
                if js_truthy(get(case_data, "parentTwRef")):
                    endorse = _ENDORSE_NO.search(_js(js_or(get(case_data, "twRef"), "")))
                reinsurer_name = js_trim(_FACILITY.sub("", _js(js_or(get(reinsurer, "name"), "")), count=1))
                if source_premium == 0 and source_income != 0:
                    comm = 100.0
                elif js_truthy(source_premium):
                    comm = source_income / source_premium * 100
                else:
                    comm = 0.0
                for person_index, person in enumerate(people):
                    row = {
                        "id": f"{reinsurer_key}:P{person_index}", "key": key, "reinsurerKey": reinsurer_key,
                        "caseId": case_id, "caseUid": case_data["caseUid"], "caseRowVersion": case_data["rowVersion"],
                        "installmentId": installment["id"], "month": month,
                        "originalInsured": _js(js_or(get(case_data, "originalInsured"), "")),
                        "reinsured": _js(js_or(get(case_data, "reinsured"), "")),
                        "reinsurer": js_or(js_trim(_js(js_or(get(reinsurer, "foreignBroker"), ""))), reinsurer_name),
                        "classCode": _js(js_or(get(case_data, "classCode"), get(case_data, "classOfBusiness"), "")),
                        "type": "R" if get(case_data, "newOrRenew") == "Renew" else "N",
                        "currency": currency, "rate": rate, "missingRate": rate is None,
                        "ae": js_or(person["name"], _js(js_or(ae, ""))),
                        "effDate": _js(js_or(get(case_data, "policyFrom"), "")),
                        "expDate": _js(js_or(get(case_data, "policyTo"), "")),
                        "comm": comm, "premium": premiums[person_index], "income": incomes[person_index],
                        "policyNo": _js(js_or(get(case_data, "parentTwRef"), get(case_data, "twRef"), "")),
                        "endorseNo": endorse.group(1) if endorse else "",
                        "remark": "Ty" if get(case_data, "reinsuranceStructure") == "TREATY" else "Fac",
                        "tranxDate": month_end(month), "installment": installment_index + 1,
                        "exclusion": {
                            "id": get(exclusion, "id"), "scope": get(exclusion, "scope"), "reason": get(exclusion, "reason"),
                            "deferredTo": _nullish_or(get(exclusion, "deferred_to"), get(exclusion, "deferredTo")),
                            "createdAt": _nullish_or(get(exclusion, "created_at"), get(exclusion, "createdAt")),
                        } if exclusion is not None else None,
                    }
                    (excluded_rows if exclusion is not None else rows).append(row)
    rows.sort(key=_row_sort_key)
    excluded_rows.sort(key=_row_sort_key)
    return {
        "errors": [], "rows": rows, "excluded": excluded_rows,
        "missingRateCurrencies": sorted(missing_rates, key=_utf16),
        "sourceSignature": production_source_signature(rows),
    }
