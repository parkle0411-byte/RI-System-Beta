"""
Production Report 的計算 - 逐函式移植自 Alpha lib/production-report.js（v53，雜湊 4474c028…）。

與 Alpha 的 JavaScript 逐位一致（scripts/run_qa.sh calc 的差異測試）。JavaScript 特有的行為：
  - Number(String(x).replace(/,/g, ''))、Math.round（.5 往正無限大）、數字轉文字（jsnum.py）
  - Date.UTC 把 0–99 年當成 1900–1999；toISOString 超過 9999 年是 +YYYYYY
  - 正則的 \\d 與 /i 只對 ASCII（Python 的 IGNORECASE 會讓 i 比對到 ı、İ，所以寫成明確的字元類別）；$ 只比對字串結尾
  - localeCompare（js_locale_key）、Array.prototype.sort() 的 UTF-16 順序
這裡不做時區換算：月份是「傳入的文字的前 7 個字」，要用台北時間就由呼叫端傳入台北時間的文字（見 views.py）。

VM 2026-10-06：負保費批單即使經紀費為零，仍列入 Production 與確認 key，以產生應退／應收交易。
"""
import re
from cases.property_original import enabled as property_enabled, periods as property_periods, report_values, report_amounts

from cases.calc.jsnum import (
    EPSILON, UNDEFINED, WS_CLASS, days_from_civil, get, is_array, is_nullish, iso_date_prefix, js_is_finite,
    js_json_stringify, js_locale_key, js_num_str, js_or, js_round, js_slice, js_spread, js_string_to_number, js_to_number,
    js_to_string, js_trim, js_truthy, js_upper,
)

PRODUCTION_REPORT_HEADERS = [
    "Original Insured", "Reinsured", "Reinsurer / RI Broker", "Class", "Type",
    "Currency", "Exch. Rate", "Account Executive", "Eff Date", "Exp Date", "Comm (%)",
    "Premium (NTD)", "Income (NTD)", "Policy No", "Endorse No", "Remark", "Tranx Date",
    "First Policy No",  # VM 新增（Alpha 沒有）：續保鏈最初那張保單的 TW Ref，放最後一欄
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
    # An endorsement's premium belongs to its own effective month. The original
    # policy's policyFrom can be months earlier than the amendment.
    if js_truthy(get(case_data, "parentTwRef")):
        # Preserve the explicit, one-off attribution of already repaired legacy
        # cases; normal Drafts cannot set this server-owned field.
        override = year_month(get(case_data, "endorsementPerformanceMonth"))
        if override:
            return override
        effective = year_month(get(case_data, "endoEffectiveDate")) or year_month(get(case_data, "policyFrom"))
        announced = year_month(get(case_data, "announcedAt")) or year_month(get(case_data, "endorsementAnnouncedAt")) or year_month(get(case_data, "postedAt"))
        return max(effective, announced)
    effective = year_month(get(case_data, "policyFrom"))
    activity_source = js_or(get(case_data, "announcedAt"), get(case_data, "postedAt"))
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
    if property_enabled(case_data):
        return [{"id":r["id"] if get(case_data,"installmentEnabled") else "FULL",
                 "performanceMonth":r.get("performanceMonth", base_month(case_data)),
                 "ratio":number_or_zero(r.get("weight"))/total_premium if total_premium and get(case_data,"installmentEnabled") else 1,
                 "income":r["t3"]} for r in property_periods(case_data)]
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


def _return_premium_activity(case_data, reinsurer, installment):
    return (js_truthy(get(case_data, "parentTwRef"))
            and number_or_zero(get(case_data, "originalPremium")) < 0
            and reinsurer_legs(case_data, reinsurer)["cedantPremium"] * installment["ratio"] != 0)


def production_key_groups_for_case(source):
    """依分期分組的 Production key（與 installment_allocations 同順序；沒有收入的期別 keys 是空串列）。"""
    case_data = normalize_source(source)
    from cases.endorsement_rules import all_zero
    if case_data.get('endorsementRules') and all_zero(case_data):
        return []
    groups = []
    reinsurers = _reinsurers(case_data)
    for installment in installment_allocations(case_data):
        keys = []
        key = f"{js_num_str(case_data['id'])}:{installment['id']}"
        raw, tail = _income_split(case_data, reinsurers, installment)
        from cases.calc.accounting import calc_legs_for_reinsurer
        for index, reinsurer in enumerate(reinsurers):
            legs = calc_legs_for_reinsurer(case_data, reinsurer)
            if property_enabled(case_data) or raw[index] + (tail if index == 0 else 0) != 0 or any(legs[k] * installment['ratio'] != 0 for k in ('leg1', 'leg2')):
                keys.append(f"{key}:R{index}")
        groups.append({"id": installment["id"], "keys": keys})
    return groups


def production_keys_for_case(source):
    return [key for group in production_key_groups_for_case(source) for key in group["keys"]]


def production_source_signature(rows):
    return js_json_stringify([[
        get(row, "id"), get(row, "originalInsured"), get(row, "reinsured"), get(row, "reinsurer"), get(row, "classCode"),
        get(row, "type"), get(row, "currency"), get(row, "rate"), get(row, "ae"), get(row, "effDate"), get(row, "expDate"),
        round2(get(row, "comm")), get(row, "premium"), get(row, "income"), get(row, "policyNo"), get(row, "endorseNo"),
        get(row, "remark"), get(row, "tranxDate"),
    ] for row in (rows if is_array(rows) else [])])


# ---------- First Policy No（首次承保號碼）：VM 新增，Alpha 沒有 ----------
# 續保會產生新的 TW Ref，Policy No 因此不同；批單的 Policy No 則是原保單的 TW Ref。
# 這裡沿著「批單 → 原保單 → 續保來源」一路追到最初那張保單，讓 Insured Name 改過的續保也能用同一個號碼分組。
# 這個欄位不放進 production_source_signature：連結不會影響金額，也避免讓已產生的報表全部變成「過期」。

def _ref_text(value):
    return value.strip() if isinstance(value, str) else ""


def reference_links(cases):
    """cases：(tw_ref, payload) 的可迭代物件 → {任一 TW Ref（含 previousTwRefs）: 連結資料}。"""
    links = {}
    for tw_ref, payload in cases:
        payload = payload if isinstance(payload, dict) else {}
        entry = {"ref": _ref_text(tw_ref), "parent": _ref_text(payload.get("parentTwRef")),
                 "renewedFrom": _ref_text(payload.get("renewedFromTwRef"))}
        previous = payload.get("previousTwRefs")
        for ref in [tw_ref, *(previous if isinstance(previous, list) else [])]:
            ref = _ref_text(ref)
            if ref:
                links.setdefault(ref, entry)
    return links


def first_policy_no(policy_no, links):
    """從 policy_no 出發：批單回到原保單，續保回到來源；找不到來源時，以最後知道的號碼為準。"""
    current, seen = _ref_text(policy_no), set()
    while current and current not in seen:
        seen.add(current)
        entry = links.get(current)
        if entry is None:
            break
        if entry["parent"]:
            current = entry["parent"]
        elif entry["renewedFrom"]:
            current = entry["renewedFrom"]
        else:
            return entry["ref"] or current
    return current


def build_production_preview(case_rows, month, fx_rates=UNDEFINED, exclusions=UNDEFINED, links=UNDEFINED):
    fx_rates = {} if fx_rates is UNDEFINED else fx_rates
    exclusions = [] if exclusions is UNDEFINED else exclusions
    if not _MONTH.match(_js(js_or(month, ""))):
        return {"errors": ["Report month must use YYYY-MM."], "rows": [], "excluded": [], "missingRateCurrencies": []}
    if links is UNDEFINED:  # 呼叫端沒給完整連結表時，只用傳進來的案件
        links = reference_links((data["twRef"], data) for data in map(normalize_source, case_rows if is_array(case_rows) else []))
    rows, excluded_rows, missing_rates, accounting_rows = [], [], [], []
    data_errors=[]
    from cases.data_integrity import financial_issues
    for source in (case_rows if is_array(case_rows) else []):
        integrity=financial_issues(get(source,"payload") if isinstance(source,dict) and "payload" in source else source)
        if integrity:
            data_errors.append({"caseUid":get(source,"caseUid") or get(source,"case_uid"),"issues":integrity})
            continue
        case_data = normalize_source(source)
        from cases.endorsement_rules import all_zero
        if case_data.get("endorsementRules") and all_zero(case_data):
            continue
        if property_enabled(case_data):
            for batch in case_data.get("productionReversals") or []:
                for snapshot in batch.get("rows") or []:
                    if snapshot["id"] in batch.get("confirmedKeys",[]):continue
                    if batch["month"] != month and not deferred_from(exclusions,case_data["id"],snapshot["key"],snapshot["reinsurerKey"],month):continue
                    excluded = exclusion_for(exclusions,case_data["id"],snapshot["key"],snapshot["reinsurerKey"],month)
                    row={**snapshot,"caseRowVersion":case_data["rowVersion"],"month":month,"tranxDate":month_end(month),"exclusion":excluded}
                    (excluded_rows if excluded else rows).append(row)
            if case_data["status"] == "reversed":continue
        if case_data["status"] not in ("posted", "closed", "reversed") or not isinstance(case_data["status"], str):
            continue
        reinsurers = _reinsurers(case_data)
        people = performance_people(case_data)
        case_id = case_data["id"]
        for installment_index, installment in enumerate(installment_allocations(case_data)):
            key = f"{js_num_str(case_id)}:{installment['id']}"
            belongs = installment["performanceMonth"] == month
            raw, tail = _income_split(case_data, reinsurers, installment)
            property_premiums = None
            if property_enabled(case_data):
                period = property_periods(case_data)[installment_index]
                property_premiums, raw = report_values(case_data,period)
                tail = 0
            for reinsurer_index, reinsurer in enumerate(reinsurers):
                reinsurer_key = f"{key}:R{reinsurer_index}"
                if confirmed(case_data, reinsurer_key):
                    continue
                if not belongs and not deferred_from(exclusions, case_id, key, reinsurer_key, month):
                    continue
                exclusion = exclusion_for(exclusions, case_id, key, reinsurer_key, month)
                legs = reinsurer_legs(case_data, reinsurer)
                source_premium = property_premiums[reinsurer_index] if property_premiums is not None else legs["cedantPremium"] * installment["ratio"]
                source_income = raw[reinsurer_index] + (tail if reinsurer_index == 0 else 0)
                if source_income == 0 and property_enabled(case_data):
                    rate=rate_for(case_data,month,fx_rates)
                    currency=js_upper(_js(js_or(get(case_data,"currency"),"TWD")))
                    if rate is None and currency not in missing_rates:missing_rates.append(currency)
                    if exclusion is None:
                        accounting_rows.append({'key':key,'reinsurerKey':reinsurer_key,'caseId':case_id,
                            'caseUid':case_data['caseUid'],'caseRowVersion':case_data['rowVersion'],
                            'installmentId':installment['id'],'month':month,'currency':currency,'rate':rate,
                            'amounts':[period['t1shares'][reinsurer_index],period['t2s'][reinsurer_index]]})
                    continue
                if source_income == 0 and not _return_premium_activity(case_data, reinsurer, installment):
                    from cases.calc.accounting import calc_legs_for_reinsurer
                    account_legs = calc_legs_for_reinsurer(case_data, reinsurer)
                    if not any(account_legs[k] * installment['ratio'] != 0 for k in ('leg1', 'leg2')):
                        continue
                    currency = js_upper(_js(js_or(get(case_data, 'currency'), 'TWD')))
                    rate = rate_for(case_data, month, fx_rates)
                    if rate is None and currency not in missing_rates:
                        missing_rates.append(currency)
                    if exclusion is None:
                        accounting_rows.append({'key': key, 'reinsurerKey': reinsurer_key, 'caseId': case_id,
                            'caseUid': case_data['caseUid'], 'caseRowVersion': case_data['rowVersion'],
                            'installmentId': installment['id'], 'month': month, 'currency': currency, 'rate': rate,
                            'amounts': [account_legs[k] * installment['ratio'] for k in ('leg1', 'leg2')]})
                    continue
                rate = rate_for(case_data, month, fx_rates)
                currency = js_upper(_js(js_or(get(case_data, "currency"), "TWD")))
                if rate is None and currency not in missing_rates:
                    missing_rates.append(currency)
                ae = get(case_data, "ae")
                premiums = [None] * len(people) if rate is None else rounded_shares(source_premium * rate, people, ae)
                incomes = [None] * len(people) if rate is None else rounded_shares(source_income * rate, people, ae)
                if property_enabled(case_data) and rate is not None:
                    premiums,incomes=report_amounts(case_data,installment["id"],rate)[reinsurer_index]
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
                policy_no = _js(js_or(get(case_data, "parentTwRef"), get(case_data, "twRef"), ""))
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
                        "policyNo": policy_no, "firstPolicyNo": first_policy_no(policy_no, links),
                        "endorseNo": _js(get(case_data, "endorsementSeq")) if get(case_data, "twRefSource") == "auw_manual" and js_truthy(get(case_data, "parentTwRef")) else (endorse.group(1) if endorse else ""),
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
        "errors": [], "rows": rows, "excluded": excluded_rows, "accountingRows": accounting_rows,
        "missingRateCurrencies": sorted(missing_rates, key=_utf16),
        "sourceSignature": js_json_stringify([production_source_signature(rows), accounting_rows, *([data_errors] if data_errors else [])]),
        **({"dataErrors":data_errors} if data_errors else {}),
    }
