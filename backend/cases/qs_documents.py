"""QS Property document checks. These never mutate underwriting/accounting data."""
from datetime import date, timedelta

from .calc.jsnum import get, is_nullish, js_is_finite, js_to_number, js_to_string, js_trim
from .calc.payment_terms import _resolved_terms
from .property_original import POSTCODE, scope as property_scope, totals
from .sum_insured import placement_issues

GENERATED_KINDS = ("generated_cover", "generated_debit")


def scope(payload, kind=None):
    return property_scope(payload) and (kind is None or kind in ("cover", "debit"))


def text(value):
    return js_trim("" if is_nullish(value) else js_to_string(value))


def valid_terms(value):
    n = js_to_number(value)
    return js_is_finite(n) and n >= 15 and n == int(n)


def valid_date(value):
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def effective_cover_days(payload, installment):
    raw = get(installment, "paymentTermsDays")
    # Only blank values may use the Case fallback. Zero is an explicit invalid value.
    return get(payload, "paymentTermsDays") if not text(raw) else raw


def printable_deadline(base, days):
    if not valid_date(base) or not valid_terms(days):
        return False
    try:
        date.fromisoformat(base) + timedelta(days=int(js_to_number(days)) - 15)
        return True
    except (OverflowError, ValueError):
        return False


def readiness_issues(payload, kind, ae_email):
    """Collect all document-data issues; status/access gates remain in the caller."""
    issues = []

    def add(field, code, message):
        if not any(row["field"] == field and row["code"] == code for row in issues):
            issues.append({"field": field, "code": code, "message": message})

    def missing(field, code, message):
        if not text(get(payload, field)):
            add(field, code, message)

    missing("reinsured", "reinsured_required",
            "Complete Reinsured in the case before generating a Cover Note or Debit Note.")
    missing("originalInsured", "original_insured_required",
            "Complete Original Insured in the case before generating a Cover Note or Debit Note.")
    missing("type", "type_required",
            "Complete Type in the case before generating a Cover Note or Debit Note.")
    for field in ("policyFrom", "policyTo"):
        if not text(get(payload, field)):
            add(field, "policy_period_required", "Complete the policy start and end dates in the case before generating a Cover Note or Debit Note.")
    missing("ae", "ae_required", "Select an AE in the case before generating a document.")
    if not ae_email:
        add("aeEmail", "ae_email_required", "Complete the AE Email in the case or Personnel before generating a document.")
    missing("originalPremium", "original_premium_required",
            "Complete 100% Premium in the case before generating a Cover Note or Debit Note.")

    reinsurers = payload.get("reinsurers")
    reinsurers = reinsurers if isinstance(reinsurers, list) else []
    if not reinsurers:
        add("reinsurers", "order_hereon_required", "Add at least one Reinsurer and complete Order hereon for every Reinsurer before generating a document.")
    for i, row in enumerate(reinsurers):
        if not isinstance(row, dict) or not text(get(row, "sharePct")):
            add(f"reinsurers.{i}.sharePct", "order_hereon_required", f"Complete Order hereon for Reinsurer {i + 1}.")
        if kind == "cover" and (not isinstance(row, dict) or not text(get(row, "name"))):
            add(f"reinsurers.{i}.name", "reinsurer_name_required", f"Complete the name for Reinsurer {i + 1}.")

    installments = payload.get("performanceInstallments")
    installments = installments if isinstance(installments, list) else []
    split = payload.get("installmentEnabled") is True
    if kind == "cover":
        missing("interest", "interest_required", "Complete Interest in the case before generating a Cover Note.")
        missing("limitOfLiability", "limit_of_liability_required", "Complete Limit of Liability in the case before generating a Cover Note.")
        missing("deductibles", "deductibles_required", "Complete Deductibles in the case before generating a Cover Note.")
        # Retention is optional here: the document prints its confirmed fixed sentence.
        situations = payload.get("situations")
        situations = situations if isinstance(situations, list) else []
        if not situations:
            add("situations", "situation_address_required", "Add at least one Situation with its Risk Address before generating a Cover Note.")
        for i, row in enumerate(situations):
            if not isinstance(row, dict) or not text(get(row, "address")):
                add(f"situations.{i}.address", "situation_address_required", f"Complete Risk Address for Situation {i + 1}.")
            if not isinstance(row, dict) or not POSTCODE.fullmatch(text(get(row, "postcode"))):
                add(f"situations.{i}.postcode", "situation_postcode_required", f"Complete a valid Postcode for Situation {i + 1}.")
        sums = payload.get("sumInsured")
        sums = sums if isinstance(sums, list) else []
        if not sums:
            add("sumInsured", "sum_insured_name_required", "Add at least one Sum Insured entry before generating a Cover Note.")
        for i, row in enumerate(sums):
            if not isinstance(row, dict) or not text(get(row, "category")):
                add(f"sumInsured.{i}.category", "sum_insured_name_required", f"Complete Interest insured for Sum Insured entry {i + 1}.")
            amount = js_to_number(get(row, "amount"))
            if not js_is_finite(amount) or amount <= 0:
                add(f"sumInsured.{i}.amount", "sum_insured_amount_required", f"Enter an Amount greater than 0 for Sum Insured entry {i + 1}.")
        for issue in placement_issues(payload):
            code = "sum_insured_locations_required" if issue["kind"] == "location" else "sum_insured_duplicate_names"
            add(issue["field"], code, issue["label"])
        missing("lossAdvisedDate", "loss_advised_date_required", "Complete the Loss Record advised date in the case before generating a Cover Note.")
        missing("lossRecordYears", "loss_record_years_required", "Complete Past year(s) in the Loss Record section before generating a Cover Note.")
        losses = payload.get("lossRecord")
        for i, row in enumerate(losses if isinstance(losses, list) else []):
            if not isinstance(row, dict) or not text(get(row, "date")):
                add(f"lossRecord.{i}.date", "loss_record_date_required", f"Complete Date of Loss for Loss Record entry {i + 1}.")
            if not isinstance(row, dict) or not text(get(row, "cause")):
                add(f"lossRecord.{i}.cause", "loss_record_cause_required", f"Complete Cause for Loss Record entry {i + 1}.")
            amount = js_to_number(get(row, "lossPaid"))
            if not js_is_finite(amount) or amount <= 0:
                add(f"lossRecord.{i}.lossPaid", "loss_record_paid_required", f"Enter a Loss Amount greater than 0 for Loss Record entry {i + 1}.")
        if split:
            if not installments:
                add("performanceInstallments", "cover_installment_terms_required", "Complete the installment payment conditions before generating a Cover Note.")
            for i, row in enumerate(installments):
                if not valid_terms(effective_cover_days(payload, row)):
                    add(f"performanceInstallments.{i}.paymentTermsDays", "cover_payment_terms_required",
                        f"Complete valid Cedant Collection Days (an integer of at least 15) for Instalment {i + 1}. Only blank days may use valid Case days.")
        elif not valid_terms(get(payload, "paymentTermsDays")):
            add("paymentTermsDays", "cover_payment_terms_required", "Complete valid Case Cedant Collection Days (an integer of at least 15) before generating a Cover Note.")
        return issues

    if text(payload.get("currency")).upper() not in ("USD", "TWD"):
        add("currency", "debit_bank_currency_unsupported", "Debit Note generation is available only for USD and TWD. The receiving bank account for other currencies is pending confirmation.")
    periods = installments if split else [{}]
    if split and not installments:
        add("performanceInstallments", "debit_installment_base_date_required", "Add installments and complete a valid Payment Base Date for every installment.")
    for i, row in enumerate(periods):
        row = row if isinstance(row, dict) else {}
        prefix = f"performanceInstallments.{i}" if split else ""
        label = f"Instalment {i + 1}" if split else "the payment"
        if split:
            if not valid_date(row.get("paymentBaseDate")):
                add(prefix + ".paymentBaseDate", "debit_installment_base_date_required", f"Complete a valid Payment Base Date for {label}.")
            if not text(row.get("premium")) and not text(row.get("ratio")):
                add(prefix + ".premium", "debit_installment_allocation_required", f"Complete Premium or Ratio for {label}.")
            raw_premium = get(row, "premium")
            premium = js_to_number(raw_premium)
            basis = premium if js_is_finite(premium) and not is_nullish(raw_premium) and raw_premium != "" else js_to_number(get(row, "ratio"))
            if not js_is_finite(basis) or basis <= 0:
                add(prefix + ".premium", "debit_installment_allocation_positive_required", f"Use a Premium or Ratio greater than 0 for {label}.")
        for r_index, reinsurer in enumerate(reinsurers):
            if not valid_terms(_resolved_terms(payload, row, reinsurer, r_index)):
                field = prefix + f".reinsurerPaymentTerms.r{r_index + 1}" if split else f"reinsurers.{r_index}.paymentTermsDays"
                code = "debit_installment_payment_terms_required" if split else "debit_payment_terms_required"
                add(field, code, f"Complete valid Payment Terms Days for Reinsurer {r_index + 1} in {label} (an integer of at least 15).")
        # Match the existing Word date source and calculation, without replacing it.
        base = row.get("paymentBaseDate") or payload.get("policyFrom")
        days = row.get("paymentTermsDays") if split else payload.get("paymentTermsDays")
        if not printable_deadline(base, days):
            add(prefix + ".paymentTermsDays" if split else "paymentTermsDays",
                "debit_payment_deadline_required", f"Complete a valid payment deadline for {label}; check its Payment Base Date and Cedant Collection Days.")
    # Read the same shared amount engine as accounting; never recalculate or write a Case.
    if reinsurers and all(isinstance(row, dict) for row in reinsurers) and text(payload.get("originalPremium")):
        try:
            if totals(payload)["leg1"] == 0:
                add("netDue", "debit_zero_net_due", "There is no amount due. A Debit Note cannot be generated when total Net Due is zero.")
        except (ValueError, TypeError, ArithmeticError, KeyError):
            add("netDue", "debit_amount_unavailable", "Complete valid premium data before generating a Debit Note.")
    return issues
