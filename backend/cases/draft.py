"""
案件草稿的驗證與整理 - 逐行移植自 Hatchable Alpha 的 lib/case-draft.js（v53）。

  normalize_draft(input)          把前端送來的案件資料整理成可以存檔的樣子，並回報所有錯誤
  validate_announce_ready(payload) Announce（正式公告）前，檢查必填欄位是否齊全

與 Alpha 逐位相同是刻意的（含錯誤訊息的文字與「順序」）：差異測試（scripts/run_qa.sh calc）會拿 Alpha 的
JavaScript 與這裡的 Python 餵同一批輸入，要求輸出完全一致。所以刻意保留 JavaScript 的語意（見 calc/jsnum.py），
例如文字以 UTF-16 單位截斷、Number() 的解析規則、Date.UTC 把 0–99 年當成 1900–1999、Clause 代碼用 ICU 排序。

一個刻意的差別：整數值的數字輸出成 int（5，而不是 5.0），因為存進 JSON 後要能用文字比對（例如 personnelId）。
"""
import re

from .calc.jsnum import (
    UNDEFINED, WS_CLASS, get, is_array, is_nullish, js_json_stringify, js_is_finite, js_is_integer, js_len, js_locale_key,
    js_num_str, js_number_out, js_or, js_slice, js_to_number, js_to_string, js_trim, js_truthy, js_upper, json_roundtrip,
)

MAX_ROWS = 50
STRUCTURE_SUFFIX = {
    "QS": "Facultative Reinsurance",
    "XOL": "Excess of Loss Facultative Reinsurance",
    "TREATY": "Reinsurance Treaty",
}
UNIVERSAL_CLAUSES = [
    {"code": "LMA3333", "title": "Reinsurers Liability Clause"},
    {"code": "INTERMEDIARY", "title": "Intermediary Clause (TW Insurance Brokers Ltd.)"},
]

_WS_RUN = re.compile(WS_CLASS + "+")
_DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})\Z")
_POSTCODE_RE = re.compile(r"[0-9]{3,6}\Z")
_MONTH_RE = re.compile(r"[0-9]{4}-[0-9]{2}\Z")
_CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")


def text(value, max_len=5000):
    if is_nullish(value):
        return ""
    return js_slice(js_trim(js_to_string(value)), 0, max_len)


def nullable_number(value, label, errors, min=None, max=None, integer=False):
    if value == "" and isinstance(value, str) or is_nullish(value):
        return None
    number = js_to_number(value)
    if not js_is_finite(number):
        errors.append(f"{label} must be a valid number.")
        return None
    if min is not None and number < min:
        errors.append(f"{label} must be at least {js_num_str(min)}.")
    if max is not None and number > max:
        errors.append(f"{label} must not exceed {js_num_str(max)}.")
    if integer and not js_is_integer(number):
        errors.append(f"{label} must be a whole number.")
    return js_number_out(number)


def _days_in_month(year, month):
    if month == 2:
        return 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def nullable_date(value, label, errors):
    result = text(value, 10)
    if not result:
        return None
    match = _DATE_RE.match(result)
    exact = False
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        # Date.UTC 會把 0–99 年當成 1900–1999，所以檢查「年份原樣回來」對 0000–0099 一律不成立
        exact = year >= 100 and 1 <= month <= 12 and 1 <= day <= _days_in_month(year, month)
    if not exact:
        errors.append(f"{label} must use YYYY-MM-DD.")
        return None
    return result


def rows(value, label, errors):
    if not is_array(value):
        return []
    if len(value) > MAX_ROWS:
        errors.append(f"{label} cannot contain more than {MAX_ROWS} rows.")
    return value[:MAX_ROWS]


def compatible_json(value, fallback, label, errors, max_length=250000):
    if is_nullish(value):
        return fallback
    encoded = js_json_stringify(value)
    if js_len(encoded) > max_length:
        errors.append(f"{label} is too large.")
        return fallback
    return json_roundtrip(value)


def compatible_rows(value, label, errors, max_rows=500):
    if is_nullish(value):
        return []
    if not is_array(value):
        errors.append(f"{label} must be a list.")
        return []
    if len(value) > max_rows:
        errors.append(f"{label} cannot contain more than {max_rows} rows.")
    return compatible_json(value[:max_rows], [], label, errors)


def clause_code(value):
    return _WS_RUN.sub("_", js_upper(text(value, 80)))


def clause_rows(value, label, errors):
    if is_nullish(value):
        return []
    if not is_array(value):
        errors.append(f"{label} must be a list.")
        return []
    if len(value) > 100:
        errors.append(f"{label} cannot contain more than 100 rows.")
    seen = set()
    result = []
    for row in value[:100]:
        code = clause_code(get(row, "code"))
        title = text(get(row, "title"), 300)
        if not code or not title:
            errors.append(f"Every {label.lower()} row requires both a code and full name.")
            continue
        if code in seen:
            errors.append(f"{label} contains duplicate code {code}.")
            continue
        seen.add(code)
        result.append({"code": code, "title": title})
    return result


def _clause_rank(code):
    if code == "LMA3333":
        return 0
    if code == "INTERMEDIARY":
        return 1
    if code.startswith("LMA"):
        return 2
    if code.startswith("NMA"):
        return 3
    if code.startswith("LPO"):
        return 4
    return 5


def _clause_sort_key(row):
    return (_clause_rank(row["code"]), js_locale_key(row["code"]))


def _texts(items, max_len):
    return [t for t in (text(item, max_len) for item in items) if t]


def normalize_draft(input_):
    errors = []
    if not isinstance(input_, dict):
        return {"errors": ["case must be an object."], "value": None}
    inp = input_

    situations = []
    for index, row in enumerate(rows(get(inp, "situations"), "Situation", errors)):
        address = text(get(row, "address"), 500)
        postcode = text(get(row, "postcode"), 6)
        if postcode and not _POSTCODE_RE.match(postcode):
            errors.append(f"Situation {index + 1} postcode must be 3–6 digits.")
        situations.append({"address": address, "postcode": postcode})

    reinsurers = []
    for index, row in enumerate(rows(get(inp, "reinsurers"), "Schedule of Security", errors)):
        n = index + 1
        reinsurers.append({
            "name": text(get(row, "name"), 240),
            "sharePct": nullable_number(get(row, "sharePct"), f"Reinsurer {n} Order hereon", errors, min=0, max=100),
            "premium": nullable_number(get(row, "premium"), f"Reinsurer {n} Premium", errors, min=0),
            "riCommPct": nullable_number(get(row, "riCommPct"), f"Reinsurer {n} Deductions", errors, min=0, max=100),
            "taxPct": nullable_number(get(row, "taxPct"), f"Reinsurer {n} Tax", errors, min=0, max=100),
            "paymentTermsDays": nullable_number(get(row, "paymentTermsDays"), f"Reinsurer {n} Payment terms", errors, min=15, integer=True),
            "foreignBroker": text(get(row, "foreignBroker"), 240),
            "settlementRef": text(get(row, "settlementRef"), 160),
        })

    sum_insured = []
    for index, row in enumerate(rows(get(inp, "sumInsured"), "Breakdown of Sum Insured", errors)):
        n = index + 1
        category = text(get(row, "category"), 240)
        amount = nullable_number(get(row, "amount"), f"Sum insured row {n} Amount", errors, min=0)
        location = nullable_number(get(row, "locationIndex"), f"Sum insured row {n} location", errors, min=0, integer=True)
        sum_insured.append({"category": category, "amount": amount, "locationIndex": 0 if location is None else location})

    performance_installments = []
    for index, row in enumerate(rows(get(inp, "performanceInstallments"), "Premium Installments", errors)):
        n = index + 1
        performance_month = text(get(row, "performanceMonth"), 7)
        if performance_month and not _MONTH_RE.match(performance_month):
            errors.append(f"Installment {n} performance month must use YYYY-MM.")
        performance_installments.append({
            "id": js_or(text(get(row, "id"), 100), f"I{n}"),
            "performanceMonth": performance_month,
            "paymentBaseDate": js_or(nullable_date(get(row, "paymentBaseDate"), f"Installment {n} payment base date", errors), ""),
            "paymentTermsDays": nullable_number(get(row, "paymentTermsDays"), f"Installment {n} Payment terms", errors, min=15, integer=True),
            "reinsurerPaymentTerms": compatible_json(get(row, "reinsurerPaymentTerms"), {}, f"Installment {n} Reinsurer Payment terms", errors),
            "premium": nullable_number(get(row, "premium"), f"Installment {n} Premium", errors, min=0),
            "ratio": nullable_number(get(row, "ratio"), f"Installment {n} ratio", errors, min=0, max=100),
        })

    raw_split_parties = rows(get(inp, "splitParties"), "Performance Split", errors)
    if len(raw_split_parties) > 2:
        errors.append("Performance Split cannot contain more than two people.")
    split_parties = []
    for index, row in enumerate(raw_split_parties[:2]):
        n = index + 1
        split_parties.append({
            "personnelId": nullable_number(get(row, "personnelId"), f"Performance Split person {n} ID", errors, min=1, integer=True),
            "name": text(get(row, "name"), 160),
            "pct": nullable_number(get(row, "pct"), f"Performance Split person {n} percentage", errors, min=0, max=100),
        })

    loss_record = []
    for index, row in enumerate(rows(get(inp, "lossRecord"), "Loss Record", errors)):
        n = index + 1
        loss_record.append({
            "date": js_or(nullable_date(get(row, "date"), f"Loss {n} Date of Loss", errors), ""),
            "cause": text(get(row, "cause"), 1000),
            "lossPaid": nullable_number(get(row, "lossPaid"), f"Loss {n} Loss Paid", errors, min=0),
        })

    effective_date = nullable_date(get(inp, "policyFrom"), "Effective date", errors)
    expiration_date = nullable_date(get(inp, "policyTo"), "Expiration date", errors)
    policy_from_time = js_or(text(get(inp, "policyFromTime"), 5), "12:00")
    policy_to_time = js_or(text(get(inp, "policyToTime"), 5), "12:00")
    if policy_from_time not in ("00:00", "12:00"):
        errors.append("Effective time must be 12:00 or 00:00.")
    if policy_to_time not in ("00:00", "12:00"):
        errors.append("Expiration time must be 12:00 or 00:00.")
    if effective_date and expiration_date and expiration_date < effective_date:
        errors.append("Expiration date cannot be earlier than Effective date.")

    requested_structure = js_upper(text(get(inp, "reinsuranceStructure"), 20))
    reinsurance_structure = "QS" if requested_structure == "FACULTATIVE" else requested_structure
    if reinsurance_structure and reinsurance_structure not in ("QS", "XOL", "TREATY"):
        errors.append("Reinsurance structure must be Quota Share, Excess of Loss, or Treaty.")
    suffix = STRUCTURE_SUFFIX.get(reinsurance_structure, "")
    stored_type = text(get(inp, "type"), 200)
    type_prefix = text(get(inp, "typePrefix"), 120)
    if not type_prefix and stored_type:
        if suffix and stored_type.endswith(suffix):
            type_prefix = js_slice(js_trim(js_slice(stored_type, 0, -len(suffix))), 0, 120)
        else:
            type_prefix = js_slice(stored_type, 0, 120)
    type_ = text((f"{type_prefix} {suffix}" if type_prefix else suffix) if suffix else type_prefix, 200)

    currency = js_upper(text(get(inp, "currency"), 3))
    if currency and not _CURRENCY_RE.match(currency):
        errors.append("Currency must be a three-letter code.")

    basis_of_valuation = text(get(inp, "basisOfValuation"), 100)
    manual_clauses = clause_rows(get(inp, "manualClauses"), "Manual clauses", errors)
    supplied_details = clause_rows(get(inp, "clauseDetails"), "Clause details", errors)
    manual_codes = {row["code"] for row in manual_clauses}
    universal_codes = {row["code"] for row in UNIVERSAL_CLAUSES}
    for row in manual_clauses:
        if row["code"] in universal_codes:
            errors.append(f"{row['code']} is universal and cannot be a manual clause.")
    clause_map = {row["code"]: dict(row) for row in UNIVERSAL_CLAUSES}
    for row in supplied_details:
        clause_map.setdefault(row["code"], row)
    for row in manual_clauses:
        clause_map.setdefault(row["code"], row)
    clause_details = sorted(clause_map.values(), key=_clause_sort_key)
    auto_clauses = [row["code"] for row in clause_details if row["code"] not in universal_codes and row["code"] not in manual_codes]

    # 以下的順序必須與 Alpha 物件字面值的欄位順序相同：欄位是依序求值的，錯誤訊息也依這個順序加入
    value = {}
    value["ownerPersonnelId"] = nullable_number(get(inp, "ownerPersonnelId"), "Case owner Personnel ID", errors, min=1, integer=True)
    value["ownerPersonnelName"] = text(get(inp, "ownerPersonnelName"), 160)
    value["parentTwRef"] = text(get(inp, "parentTwRef"), 120)
    value["endorsementSeq"] = nullable_number(get(inp, "endorsementSeq"), "Endorsement sequence", errors, min=0, integer=True)
    value["renewedFromTwRef"] = text(get(inp, "renewedFromTwRef"), 120)
    value["endoEffectiveDate"] = js_or(nullable_date(get(inp, "endoEffectiveDate"), "Endorsement effective date", errors), "")
    value["endoTypes"] = _texts(compatible_rows(get(inp, "endoTypes"), "Endorsement types", errors, 20), 120)
    value["endoText"] = text(get(inp, "endoText"), 5000)
    value["type"] = type_
    value["typePrefix"] = type_prefix
    value["originalInsured"] = text(get(inp, "originalInsured"), 240)
    value["originalInsuredCn"] = text(get(inp, "originalInsuredCn"), 240)
    value["reinsured"] = text(get(inp, "reinsured"), 240)
    value["situations"] = situations if situations else [{"address": "", "postcode": ""}]
    value["classOfBusiness"] = text(get(inp, "classOfBusiness"), 160)
    value["classCode"] = text(get(inp, "classCode"), 80)
    value["reinsuranceStructure"] = reinsurance_structure
    value["policyFrom"] = effective_date or ""
    value["policyFromTime"] = policy_from_time if policy_from_time in ("00:00", "12:00") else "12:00"
    value["policyTo"] = expiration_date or ""
    value["policyToTime"] = policy_to_time if policy_to_time in ("00:00", "12:00") else "12:00"
    value["currency"] = currency
    value["originalPremium"] = nullable_number(get(inp, "originalPremium"), "100% Premium", errors, min=0)
    value["riCommPct"] = nullable_number(get(inp, "riCommPct"), "Ceding commission", errors, min=0, max=100)
    value["taxPct"] = nullable_number(get(inp, "taxPct"), "Cedant tax", errors, min=0, max=100)
    value["paymentTermsDays"] = nullable_number(get(inp, "paymentTermsDays"), "Payment terms", errors, min=15, integer=True)
    value["installmentEnabled"] = get(inp, "installmentEnabled") is True
    value["performanceInstallments"] = performance_installments
    value["splitEnabled"] = get(inp, "splitEnabled") is True
    value["splitParties"] = split_parties
    value["reinsurers"] = reinsurers if reinsurers else [{
        "name": "", "sharePct": None, "premium": None, "riCommPct": None, "taxPct": None,
        "paymentTermsDays": None, "foreignBroker": "", "settlementRef": ""}]
    value["sumInsured"] = sum_insured if sum_insured else [{"category": "", "amount": None, "locationIndex": 0}]
    value["lossAdvisedDate"] = js_or(nullable_date(get(inp, "lossAdvisedDate"), "Loss record advised date", errors), "")
    value["lossRecordYears"] = nullable_number(get(inp, "lossRecordYears"), "Loss record years", errors, min=0, integer=True)
    value["lossRecord"] = loss_record
    value["lossRecordText"] = text(get(inp, "lossRecordText"), 5000)
    value["clauses"] = [row["code"] for row in clause_details]
    value["clauseDetails"] = clause_details
    value["autoClauses"] = auto_clauses
    value["manualClauses"] = manual_clauses
    value["status"] = "draft"
    value["interest"] = text(get(inp, "interest"), 3000)
    value["limitOfLiability"] = nullable_number(get(inp, "limitOfLiability"), "Limit of Liability", errors, min=0)
    value["aggregateLimit"] = nullable_number(get(inp, "aggregateLimit"), "Aggregate Limit", errors, min=0)
    value["underlyingLimits"] = "" if reinsurance_structure == "QS" else text(get(inp, "underlyingLimits"), 3000)
    value["subLimits"] = text(get(inp, "subLimits"), 3000)
    value["deductibles"] = text(get(inp, "deductibles"), 3000)
    value["reinsuredRetention"] = text(get(inp, "reinsuredRetention"), 3000)
    value["reinstatementProvisions"] = text(get(inp, "reinstatementProvisions"), 3000)
    value["indemnityPeriod"] = text(get(inp, "indemnityPeriod"), 1000)
    value["originalExclusions"] = text(get(inp, "originalExclusions"), 5000)
    value["basisOfValuation"] = basis_of_valuation
    value["basisOfValuationOther"] = text(get(inp, "basisOfValuationOther"), 1000) if basis_of_valuation == "Other" else ""
    value["originalConditions"] = text(get(inp, "originalConditions"), 5000)
    value["expressWarranties"] = text(get(inp, "expressWarranties"), 3000)
    value["conditionsPrecedent"] = text(get(inp, "conditionsPrecedent"), 3000)
    value["subjectivities"] = text(get(inp, "subjectivities"), 3000)
    value["occupation"] = text(get(inp, "occupation"), 3000)
    value["construction"] = text(get(inp, "construction"), 3000)
    value["lossPayee"] = text(get(inp, "lossPayee"), 3000)
    value["notices"] = text(get(inp, "notices"), 5000)
    value["specialAgreement"] = text(get(inp, "specialAgreement"), 5000)
    value["ae"] = text(get(inp, "ae"), 160)
    value["newOrRenew"] = text(get(inp, "newOrRenew"), 20)
    value["exchRate"] = nullable_number(get(inp, "exchRate"), "Exchange rate", errors, min=0)
    value["remark"] = text(get(inp, "remark"), 5000)
    value["postedAt"] = text(get(inp, "postedAt"), 80)
    value["confirmedProductionKeys"] = _texts(compatible_rows(get(inp, "confirmedProductionKeys"), "Confirmed production keys", errors, 200), 240)
    value["productionExclusions"] = compatible_json(get(inp, "productionExclusions"), {}, "Production exclusions", errors)
    value["endorsements"] = compatible_rows(get(inp, "endorsements"), "Endorsements", errors)
    value["transactions"] = compatible_rows(get(inp, "transactions"), "Transactions", errors)
    value["claims"] = compatible_rows(get(inp, "claims"), "Claims", errors)
    value["statementNo"] = text(get(inp, "statementNo"), 160)
    reversal_cycle = nullable_number(get(inp, "reversalCycle"), "Reversal cycle", errors, min=0, integer=True)
    value["reversalCycle"] = 0 if reversal_cycle is None else reversal_cycle
    pending = get(inp, "pendingReversalOffset")
    value["pendingReversalOffset"] = pending is True or js_to_number(pending) == 1
    value["accountingNotifications"] = compatible_rows(get(inp, "accountingNotifications"), "Accounting notifications", errors)
    value["paymentEntries"] = compatible_rows(get(inp, "paymentEntries"), "Payment entries", errors)
    value["paymentScheduleReviewRequired"] = get(inp, "paymentScheduleReviewRequired") is True

    return {
        "errors": errors,
        "value": value,
        "columns": {
            "reinsuranceStructure": reinsurance_structure or None,
            "currency": currency or None,
            "effectiveDate": effective_date,
            "expirationDate": expiration_date,
        },
    }


def _filled(value):
    if is_nullish(value):
        return False
    if isinstance(value, str):
        return js_trim(value) != ""
    return True


def _is_int_number(value):
    return js_is_integer(js_to_number(value))


def validate_announce_ready(payload):
    issues = []

    def add(field, label):
        issues.append({"field": field, "label": label})

    value = payload if isinstance(payload, (dict, list)) else {}
    if not _is_int_number(get(value, "ownerPersonnelId")) or js_to_number(get(value, "ownerPersonnelId")) < 1:
        add("ownerPersonnelId", "Case Owner")
    for field, label in (
        ("reinsuranceStructure", "Reinsurance structure"), ("ae", "AE"), ("currency", "Currency"),
        ("classOfBusiness", "Class"), ("newOrRenew", "New / Renew"), ("type", "Type"),
        ("reinsured", "Reinsured"), ("originalInsured", "Original insured (EN)"),
        ("policyFrom", "Effective date"), ("policyTo", "Expiration date"), ("interest", "Interest"),
    ):
        if not _filled(get(value, field)):
            add(field, label)

    if _filled(get(value, "parentTwRef")):
        if not _filled(get(value, "endoEffectiveDate")):
            add("endoEffectiveDate", "Endorsement effective date")
        endo_types = get(value, "endoTypes")
        if not is_array(endo_types) or not endo_types:
            add("endoTypes", "At least one endorsement type")
        if not _filled(get(value, "endoText")):
            add("endoText", "Endorsement wording")

    situations = get(value, "situations")
    situations = situations if is_array(situations) else []
    if not situations:
        add("situations", "Situation")
    for index, row in enumerate(situations):
        if not _filled(get(row, "address")):
            add(f"situations.{index}.address", f"Situation {index + 1} Risk Address")
        if not _POSTCODE_RE.match(js_trim(js_to_string(js_or(get(row, "postcode"), "")))):
            add(f"situations.{index}.postcode", f"Situation {index + 1} Postcode")

    reinsurers = get(value, "reinsurers")
    reinsurers = reinsurers if is_array(reinsurers) else []
    if not reinsurers:
        add("reinsurers", "Schedule of Security")
    for index, row in enumerate(reinsurers):
        n = index + 1
        if not _filled(get(row, "name")):
            add(f"reinsurers.{index}.name", f"Reinsurer {n}")
        if not _filled(get(row, "sharePct")):
            add(f"reinsurers.{index}.sharePct", f"Reinsurer {n} Order hereon")
        if not _filled(get(row, "premium")):
            add(f"reinsurers.{index}.premium", f"Reinsurer {n} Premium")
        if not _filled(get(row, "riCommPct")):
            add(f"reinsurers.{index}.riCommPct", f"Reinsurer {n} Deductions")
        if not _filled(get(row, "taxPct")):
            add(f"reinsurers.{index}.taxPct", f"Reinsurer {n} Tax")

    if not _filled(get(value, "limitOfLiability")):
        add("limitOfLiability", "Limit of Liability")
    if not _filled(get(value, "deductibles")):
        add("deductibles", "Deductibles")
    if not _filled(get(value, "originalConditions")):
        add("originalConditions", "Original Conditions")
    if get(value, "basisOfValuation") == "Other" and not _filled(get(value, "basisOfValuationOther")):
        add("basisOfValuationOther", "Basis of Valuation — Other")
    if not _filled(get(value, "occupation")):
        add("occupation", "Occupation")
    if not _filled(get(value, "construction")):
        add("construction", "Construction")

    sum_insured = get(value, "sumInsured")
    sum_insured = sum_insured if is_array(sum_insured) else []
    if not sum_insured:
        add("sumInsured", "Breakdown of Sum Insured")
    for index, row in enumerate(sum_insured):
        n = index + 1
        if not _filled(get(row, "category")):
            add(f"sumInsured.{index}.category", f"Sum insured {n} Interest insured")
        if not _filled(get(row, "amount")):
            add(f"sumInsured.{index}.amount", f"Sum insured {n} Amount")
    if not _filled(get(value, "lossAdvisedDate")):
        add("lossAdvisedDate", "Loss record advised by broker on")
    years = js_to_number(get(value, "lossRecordYears"))
    if not js_is_integer(years) or years <= 0:
        add("lossRecordYears", "Loss history years")
    loss_record = get(value, "lossRecord")
    loss_record = loss_record if is_array(loss_record) else []
    for index, row in enumerate(loss_record):
        n = index + 1
        if not _filled(get(row, "date")):
            add(f"lossRecord.{index}.date", f"Loss {n} Date of Loss")
        if not _filled(get(row, "cause")):
            add(f"lossRecord.{index}.cause", f"Loss {n} Cause")
        if not _filled(get(row, "lossPaid")):
            add(f"lossRecord.{index}.lossPaid", f"Loss {n} Loss Paid")

    for field, label in (("originalPremium", "100% Premium"), ("paymentTermsDays", "Payment terms"),
                         ("riCommPct", "Ceding commission"), ("taxPct", "Cedant tax")):
        if not _filled(get(value, field)):
            add(field, label)
    if _filled(get(value, "paymentTermsDays")) and js_to_number(get(value, "paymentTermsDays")) < 15:
        add("paymentTermsDays", "Payment terms of at least 15 calendar days")

    if js_truthy(get(value, "installmentEnabled")):
        installment_rows = get(value, "performanceInstallments")
        installment_rows = installment_rows if is_array(installment_rows) else []
        if not installment_rows:
            add("performanceInstallments", "At least one Premium Installment")
        else:
            for index, row in enumerate(installment_rows):
                n = index + 1
                if not _MONTH_RE.match(js_to_string(js_or(get(row, "performanceMonth"), ""))):
                    add(f"performanceInstallments.{index}.performanceMonth", f"Installment {n} performance month")
                if not re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z", js_to_string(js_or(get(row, "paymentBaseDate"), ""))):
                    add(f"performanceInstallments.{index}.paymentBaseDate", f"Installment {n} payment base date")
            total_premium = js_to_number(js_or(get(value, "originalPremium"), 0))
            if total_premium == 0:
                ratio_total = 0.0
                for row in installment_rows:
                    ratio_total += js_to_number(js_or(get(row, "ratio"), 0))
                if any(js_to_number(js_or(get(row, "ratio"), 0)) <= 0 for row in installment_rows) or abs(ratio_total - 100) > 0.0001:
                    add("performanceInstallments", "Installment ratios greater than 0 totaling 100%")
            else:
                def missing(row):
                    premium = get(row, "premium")
                    return premium is None or premium is UNDEFINED or not js_is_finite(js_to_number(premium))

                missing_premium = any(missing(row) for row in installment_rows)
                installment_total = 0.0
                for row in installment_rows:
                    installment_total += js_to_number(js_or(get(row, "premium"), 0))
                if missing_premium or abs(installment_total - total_premium) > 0.01:
                    add("performanceInstallments", "Installment Premium total equal to 100% Premium")

    if js_truthy(get(value, "splitEnabled")):
        parties = get(value, "splitParties")
        parties = parties if is_array(parties) else []
        if len(parties) != 2:
            add("splitParties", "Exactly two Performance Split people")
        else:
            names = [js_trim(js_to_string(js_or(get(row, "name"), ""))).lower() for row in parties]
            if any(not name for name in names) or len(set(names)) != 2:
                add("splitParties", "Two different Performance Split people")
            ids = [js_to_number(get(row, "personnelId")) for row in parties]
            if any(not js_is_integer(i) or i < 1 for i in ids) or len(set(ids)) != 2:
                add("splitParties", "Two different Personnel records for Performance Split")
            percentages = [js_to_number(get(row, "pct")) for row in parties]
            if any(not js_is_finite(p) or p <= 0 for p in percentages):
                add("splitParties", "Performance Split percentages greater than 0")
            total = 0.0
            for pct in percentages:
                total += pct if js_is_finite(pct) else 0
            if abs(total - 100) > 0.0001:
                add("splitParties", "Performance Split percentages totaling 100%")
    return issues
