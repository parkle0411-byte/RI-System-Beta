"""案件 History（2026-11-27 業主決定）：由版本紀錄（Entity Snapshot）整理案件內容改了什麼。純計算、唯讀。

比對對象是版本紀錄裡的 payload。系統自己維護的欄位（交易、收付款、各種內部歷程與版本標記、內部編號）不列；
空字串、None、空清單、空物件、False 與「沒有這個欄位」視為相同，所以伺服器補上的空欄位不會被當成修改。
"""
import re

EVENT_LABELS = {
    "draft_created": "Draft created",
    "draft_updated": "Draft edited",
    "case_updated": "Case edited",
    "announced": "Announced",
    "renewal_created": "Renewal created",
    "endorsement_created": "Endorsement created",
    "case_reversed": "Case reversed",
    "accounting_notified": "Accounting notified",
    "draft_recycled": "Draft moved to Recycle Bin",
    "draft_restored": "Draft restored",
    "claim_created": "Claim created",
    "claim_reserve_updated": "Claim reserve updated",
    "claim_loss_date_updated": "Claim loss date updated",
    "claim_cause_updated": "Claim cause updated",
    "claim_currency_updated": "Claim currency updated",
    "claim_payment_recorded": "Claim payment recorded",
    "claim_payment_corrected": "Claim payment corrected",
    "claim_renewal_sync": "Claim copied to renewal",
    "claim_loss_snapshot_updated": "Renewal claim record updated",
    "payment_recorded": "Payment recorded",
    "payment_reversed": "Payment reversed",
    "finance_accounts_reviewed": "Finance review",
    "finance_review_cancelled": "Finance review cancelled",
    "record_claim_followup": "Claim follow-up recorded",
    "production_case_confirmed": "Confirmed by Production close",
    "reconciliation_references_updated": "Settlement references edited",
    "historical_personnel_link": "Personnel link confirmed",
    "endorsement_single_settlement": "Endorsement settlement terms adjusted",
    "oversea_reference_corrected": "TW Ref corrected",
    "auw_howden_bound": "AUW reference bound",
    "auw_primary_reference_converted": "Primary reference converted",
}

# 這些事件列出案件欄位的修改前／後
CONTENT_REASONS = {
    "draft_updated", "case_updated", "reconciliation_references_updated", "historical_personnel_link",
    "endorsement_single_settlement", "oversea_reference_corrected", "auw_howden_bound",
    "auw_primary_reference_converted",
}
# 理賠事件只比對 claims
CLAIM_REASONS = {
    "claim_created", "claim_reserve_updated", "claim_loss_date_updated", "claim_cause_updated",
    "claim_currency_updated", "claim_payment_recorded", "claim_payment_corrected",
}
REFERENCE_REASONS = {"oversea_reference_corrected", "auw_howden_bound", "auw_primary_reference_converted"}

# payload 最上層由系統維護、不是使用者在案件上填的欄位
SYSTEM_KEYS = {
    "status", "twRef", "draftInput", "draftInputScope", "transactions", "paymentEntries", "swissAccounting",
    "facilityAccounting", "claims", "claimLossSnapshots", "paymentEditHistory", "claimCorrectionHistory",
    "accountingAdjustmentHistory", "paymentTermsHistory", "allianzClaimTracking", "greatAmericanClaimTracking",
    "qbeClaimTracking", "financeClaimTracking", "financeCorrectionHistory", "financeWorkflowVersion",
    "productionHistory", "productionReversals", "productionExclusions", "productionPartiallyConfirmed",
    "propertyReversalHistory", "propertyEditHistory", "confirmedProductionKeys", "accountingNotifications",
    "accountingRules", "accountingLegacyMath", "premiumRounding", "premiumLedgerLayout", "propertyOriginalRules",
    "placingRulesVersion", "personnelIdentityVersion", "personnelIdentityHistory", "cedantTermsBasis",
    "insuredDirectoryEnabled", "endorsementSource", "endorsementRules", "constructionSelectionVersion",
    "reversalCycle", "announcedAt", "postedAt", "endorsementAnnouncedAt", "paymentScheduleReviewRequired",
    "pendingClause", "pendingReversalOffset", "twRefSource", "previousTwRefs", "clauseDetails", "autoClauses",
}

LABELS = {
    "ae": "Account Executive", "aggregateLimit": "Aggregate Limit", "amount": "Amount", "address": "Address",
    "basisOfValuation": "Basis of Valuation", "basisOfValuationOther": "Basis of Valuation — Other",
    "cashLossLimit": "Cash Loss Limit", "category": "Category", "cause": "Cause",
    "cglAggregateMode": "Aggregate Limit Mode", "cglAnnual": "100% Premium (annual)", "cglInformation": "CGL Information",
    "choiceOfLaw": "Choice of Law", "classCode": "Class Code", "classOfBusiness": "Insurance Type", "claims": "Claim",
    "clauses": "Clauses", "manualClauses": "Manual Clauses", "code": "Code", "title": "Title",
    "coReinsuranceWarranty": "Co-Reinsurance Warranty", "conditions": "Conditions",
    "conditionsPrecedent": "Conditions Precedent", "construction": "Construction",
    "constructionSelections": "Construction Selections", "coverages": "Coverages", "coveragesOther": "Coverages — Other",
    "coveragesOtherItems": "Coverages — Other", "currency": "Currency", "date": "Date", "deductibles": "Deductibles",
    "deductionPct": "Deduction (%)", "endoEffectiveDate": "Endorsement Effective Date", "endoText": "Endorsement Wording",
    "endoTypes": "Endorsement Types", "estimatedTurnover": "Estimated Turnover", "eventLimit": "Event Limit",
    "exchRate": "Exchange Rate", "exclusions": "Exclusions", "expressWarranties": "Express Warranties",
    "extendedReportingApplies": "Extended Reporting Period", "extendedReportingPeriod": "Extended Reporting Period — Description",
    "foreignBroker": "Foreign RI Broker", "indemnityPeriod": "Indemnity Period", "installmentEnabled": "Premium Installments",
    "insuredBusiness": "Insured’s Business", "insuredProducts": "Insured’s Products", "insuredWebsite": "Insured’s Website",
    "interest": "Interest", "limitOfLiability": "Limit of Liability", "lossAdvisedDate": "Loss Record Advised Date",
    "lossPaid": "Loss Amount", "lossPayee": "Loss Payee", "lossRecord": "Loss Record",
    "lossRecordText": "Loss Record Wording", "lossRecordYears": "Loss Record Past Year(s)",
    "manualTwRef": "TW Ref. (for AUW)", "name": "Name", "newOrRenew": "New / Renew", "notices": "Notices",
    "occupation": "Occupation", "originalAssuredDescription": "Original Insured", "originalConditions": "Original Conditions",
    "originalExclusions": "Original Exclusions", "originalInsured": "Original Insured (EN)",
    "originalInsuredCn": "Original Insured (CN)", "originalPremium": "100% Premium", "ownerPersonnelName": "Case Owner",
    "parentTwRef": "Endorsement of", "paymentTermsDays": "Cedant Collection Days", "paymentBaseDate": "Payment Base Date",
    "pct": "Share (%)", "performanceInstallments": "Premium Installment", "performanceMonth": "Performance Month",
    "policyForm": "Policy Form", "policyFrom": "Effective Date", "policyFromTime": "Effective Time",
    "policyTo": "Expiration Date", "policyToTime": "Expiration Time", "postcode": "Postcode", "ppwDays": "PPW (days)",
    "premium": "Premium", "premiumAdjustment": "100% Premium Adjustment", "premiumPaymentTerms": "Premium Payment Terms",
    "premiumRates": "Premium Rates", "productRecall": "Product Recall", "ratio": "Ratio",
    "receiptPaymentDate": "Receipt / Payment Date", "reinstatementProvisions": "Reinstatement Provisions",
    "reinsuranceStructure": "Reinsurance Type", "reinsured": "Reinsured", "reinsuredLocation": "Reinsured Location",
    "reinsuredRetention": "Reinsured's Retention", "reinsurers": "Reinsurer", "remark": "Remark",
    "renewedFromTwRef": "Renewed from", "riCommPct": "Ceding Commission (%)",
    "selfInsuredRetention": "Self-Insured Retention", "settlementRef": "Settlement Reference", "sharePct": "Share (%)",
    "situations": "Situation", "specialAgreement": "Special Agreement", "splitEnabled": "Performance Split",
    "splitParties": "Performance Split", "statementNo": "Statement No.", "subLimits": "Sub-Limits",
    "subjectivities": "Subjectivities", "sumInsured": "Sum Insured", "taxPct": "Tax (%)", "taxesText": "Taxes",
    "territorialScope": "Territorial Scope", "type": "Type", "underlyingLimits": "Underlying Limits",
    "stpPremiumRate": "Premium Rate", "stpWebsite": "Insured’s Website", "stpTurnover": "Estimated Turnover",
    "stpHubs": "HUB List",
}

# 同一個欄位在再保人列的畫面名稱不同
REINSURER_LABELS = {"riCommPct": "Deductions (%)", "paymentTermsDays": "Payment Terms (Days)"}

# 內部編號與（理賠裡的）系統時間／經手人欄位
_ID_KEY = re.compile(r"^id$|(Id|Ids|Uid|ID)$")
_STAMP_KEY = re.compile(r"(At|By|ByName)$")
MAX_CHANGES = 200
MAX_TEXT = 20000


def label(key, path=()):
    if path and path[0] == LABELS["reinsurers"] and key in REINSURER_LABELS:
        return REINSURER_LABELS[key]
    if key in LABELS:
        return LABELS[key]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).replace("_", " ").strip()
    return words[:1].upper() + words[1:]


def _empty(value):
    return value is None or value is False or value == "" or value == [] or value == {}


def _same_scalar(a, b):
    if _empty(a) and _empty(b):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    # 數字欄位有時存成字串（"1000" 與 1000）：值相同就不算修改
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return float(str(a).replace(",", "")) == float(str(b).replace(",", ""))
        except ValueError:
            return False
    return a == b


def _text(value):
    if value is None or value == "" or value == [] or value == {}:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)[:MAX_TEXT]


def _hidden(key, in_claim):
    return bool(_ID_KEY.search(key) or (in_claim and _STAMP_KEY.search(key)))


def _summary(value, in_claim, path=()):
    """新增或刪除整筆資料時的一段摘要。"""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if _hidden(key, in_claim) or _empty(item):
                continue
            inner = _summary(item, in_claim, path)
            if inner is not None:
                parts.append(f"{label(key, path)}: {inner}")
        return "; ".join(parts)[:MAX_TEXT] or None
    if isinstance(value, list):
        parts = [s for s in (_summary(item, in_claim, path) for item in value) if s]
        return (" | " if any(isinstance(item, dict) for item in value) else ", ").join(parts)[:MAX_TEXT] or None
    return _text(value)


def _identity(rows_before, rows_after):
    """清單項目用哪個欄位對應：兩邊每一筆都有值且不重複才用，否則按順序。"""
    for key in ("id", "name", "code"):
        usable = True
        for rows in (rows_before, rows_after):
            values = [row.get(key) if isinstance(row, dict) else None for row in rows]
            if not all(isinstance(v, (str, int)) and v != "" for v in values) or len(set(values)) != len(values):
                usable = False
        if usable:
            return key
    return None


def _item_name(row, index):
    if isinstance(row, dict):
        for key in ("name", "code", "claimNo", "category", "description"):
            if isinstance(row.get(key), str) and row[key].strip():
                return row[key].strip()[:80]
    return f"#{index + 1}"


def _add(out, path, before, after, kind="changed"):
    if before != after:
        out.append({"field": " › ".join(path), "before": before, "after": after, "kind": kind})


def _walk(before, after, path, out, in_claim):
    if len(out) > MAX_CHANGES or (_empty(before) and _empty(after)):
        return
    if isinstance(before, dict) or isinstance(after, dict):
        if (isinstance(before, dict) or _empty(before)) and (isinstance(after, dict) or _empty(after)):
            before, after = before or {}, after or {}
            for key in list(after) + [k for k in before if k not in after]:
                if not _hidden(key, in_claim):
                    _walk(before.get(key), after.get(key), path + [label(key, path)], out, in_claim)
            return
    elif isinstance(before, list) or isinstance(after, list):
        if (isinstance(before, list) or _empty(before)) and (isinstance(after, list) or _empty(after)):
            before, after = before or [], after or []
            if any(isinstance(row, dict) for row in before + after):
                _walk_rows(before, after, path, out, in_claim)
            else:
                _add(out, path, _summary(before, in_claim, path), _summary(after, in_claim, path))
            return
    if isinstance(before, (dict, list)) or isinstance(after, (dict, list)):
        _add(out, path, _summary(before, in_claim, path), _summary(after, in_claim, path))
    elif not _same_scalar(before, after):
        _add(out, path, _text(before), _text(after))


def _walk_rows(before, after, path, out, in_claim):
    key = _identity(before, after)
    if key:
        old = {row[key]: row for row in before}
        new = {row[key] for row in after}
        for index, row in enumerate(after):
            name = path + [_item_name(row, index)]
            if row[key] in old:
                _walk(old[row[key]], row, name, out, in_claim)
            else:
                _add(out, name, None, _summary(row, in_claim, path), "added")
        for index, row in enumerate(before):
            if row[key] not in new:
                _add(out, path + [_item_name(row, index)], _summary(row, in_claim, path), None, "removed")
        return
    for index in range(max(len(before), len(after))):
        old = before[index] if index < len(before) else None
        new = after[index] if index < len(after) else None
        name = path + [_item_name(new if new is not None else old, index)]
        if old is None:
            _add(out, name, None, _summary(new, in_claim, path), "added")
        elif new is None:
            _add(out, name, _summary(old, in_claim, path), None, "removed")
        else:
            _walk(old, new, name, out, in_claim)


def _new_entries(before, after, key):
    old = before.get(key) if isinstance(before.get(key), list) else []
    new = after.get(key) if isinstance(after.get(key), list) else []
    return [row for row in new[len(old):] if isinstance(row, dict)]


def compare(reason, before, after):
    """回傳 (changes, comment)。before／after 是兩份 payload。"""
    out = []
    if reason in CLAIM_REASONS:
        _walk(before.get("claims"), after.get("claims"), [label("claims")], out, True)
        return out, None
    skip = SYSTEM_KEYS - ({"twRef"} if reason in REFERENCE_REASONS else set())
    for key in list(after) + [k for k in before if k not in after]:
        if key not in skip and not _hidden(key, False):
            _walk(before.get(key), after.get(key), [label(key)], out, False)
    comments = [str(row.get("reason") or "").strip() for row in _new_entries(before, after, "propertyEditHistory")]
    for row in _new_entries(before, after, "personnelIdentityHistory"):
        field = "Account Executive" if row.get("field") == "ae" else "Case Owner"
        _add(out, [f"{field} link"], _text(row.get("historicalName")), _text(row.get("personnelName")))
        comments.append(str(row.get("reason") or "").strip())
    return out, "; ".join(c for c in comments if c) or None
