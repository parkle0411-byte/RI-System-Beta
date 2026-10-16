from .cgl_information import is_standard_cgl, information_issues
"""Word-only Cover Note, Debit Note and Endorsement generation authorization.

Word files are assembled in the browser. This API validates access and the
stored Case fields, then records generation metadata without document content.
The retired PDF route returns 410 for previously opened clients.
"""
import re
import uuid
from datetime import date

from django.db import transaction
from personnel.models import Personnel
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from .calc.jsnum import get, is_nullish, js_to_string, js_trim, js_to_number, js_is_finite
from .document_views import visible_cases
from .sum_insured import placement_issues


KINDS = ("cover", "endorsement", "debit")


def _error(status, code, message):
    return Response({"error": code, "message": message}, status=status)


def _text(body, key):
    value = get(body, key)
    return js_trim("" if is_nullish(value) else js_to_string(value))


def _valid_payment_terms(value):
    days = js_to_number(value)
    return js_is_finite(days) and days >= 15 and days == int(days)


def _valid_debit_installment_allocation(row):
    # Match the Word generator's premium-first weight selection exactly.
    raw_premium = get(row, "premium")
    premium = js_to_number(raw_premium)
    if js_is_finite(premium) and not is_nullish(raw_premium) and raw_premium != "":
        return premium > 0
    ratio = js_to_number(get(row, "ratio"))
    return js_is_finite(ratio) and ratio > 0


def _valid_installment_base_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _ae_email(payload):
    """Use Case email first, then the first active AE in personnel-options order."""
    email = _text(payload, "aeEmail")
    if email:
        return email
    name = _text(payload, "ae").lower()
    if not name:
        return ""
    for person in Personnel.objects.filter(is_active=True).order_by("name", "id").only("name", "email"):
        if _text({"name": person.name}, "name").lower() == name:
            return _text({"email": person.email}, "email")
    return ""


def _find_case(request, case_uid):
    """Alpha：case_uid::text = $1 AND recycled_at IS NULL AND is_archived = false（文字比對，所以大寫的 UUID 對不到）。"""
    try:
        parsed = uuid.UUID(case_uid)
    except ValueError:
        return None
    if str(parsed) != case_uid:
        return None
    return visible_cases(request.ri_principal).filter(case_uid=parsed, recycled_at__isnull=True, is_archived=False).first()


def _check_case(request, body):
    """回傳 (case, 錯誤回應)。"""
    kind = _text(body, "kind")
    if kind not in KINDS:
        return None, kind, _error(400, "invalid_document_kind", "Document kind must be cover, endorsement or debit.")
    case_uid = _text(body, "caseUid")
    if not case_uid:
        if kind == "debit":
            return None, kind, _error(400, "case_uid_required", "caseUid is required to render a Debit Note.")
        return None, kind, _error(400, "case_uid_required", "caseUid is required to generate a document.")
    case = _find_case(request, case_uid)
    if case is None:
        if kind == "debit":
            return None, kind, _error(409, "debit_requires_tw_ref", "Debit Note is only available after Announce assigns a TW Reference.")
        return None, kind, _error(404, "case_not_found", "Case was not found.")
    payload = case.payload if isinstance(case.payload, dict) else {}
    # Treaty document requirements are deferred until its workflow is defined.
    if _text(payload, "reinsuranceStructure") == "TREATY":
        return case, kind, None
    if kind == "debit" and not case.tw_ref:
        return None, kind, _error(409, "debit_requires_tw_ref", "Debit Note is only available after Announce assigns a TW Reference.")
    if kind == "cover" and not case.tw_ref:
        return None, kind, _error(409, "cover_requires_tw_ref", "Cover Note is only available after Announce assigns a TW Reference.")
    if kind in ("cover", "debit") and not _text(payload, "reinsured"):
        return None, kind, _error(409, "reinsured_required", "Complete Reinsured in the case before generating a Cover Note or Debit Note.")
    if kind in ("cover", "debit") and not _text(payload, "originalInsured"):
        return None, kind, _error(409, "original_insured_required", "Complete Original Insured in the case before generating a Cover Note or Debit Note.")
    if kind in ("cover", "debit") and not _text(payload, "type"):
        return None, kind, _error(409, "type_required", "Complete Type in the case before generating a Cover Note or Debit Note.")
    if kind in ("cover", "debit") and (not _text(payload, "policyFrom") or not _text(payload, "policyTo")):
        return None, kind, _error(409, "policy_period_required", "Complete the policy start and end dates in the case before generating a Cover Note or Debit Note.")
    if not _text(payload, "ae"):
        return None, kind, _error(409, "ae_required", "Select an AE in the case before generating a document.")
    if not _ae_email(payload):
        return None, kind, _error(409, "ae_email_required", "Complete the AE Email in the case or Personnel before generating a document.")
    if kind == "cover":
        cgl_issues = information_issues(payload)
        if cgl_issues:
            return None, kind, _error(409, "cgl_information_required", "Complete Information before generating a Cover Note: " + "; ".join(row["label"] for row in cgl_issues))
    if kind == "cover" and not _text(payload, "interest"):
        return None, kind, _error(409, "interest_required", "Complete Interest in the case before generating a Cover Note.")
    if kind == "cover" and not _text(payload, "limitOfLiability"):
        return None, kind, _error(409, "limit_of_liability_required", "Complete Limit of Liability in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") == "XOL" and not _text(payload, "underlyingLimits"):
        return None, kind, _error(409, "underlying_limits_required", "Complete Underlying Limits in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and not _text(payload, "deductibles"):
        return None, kind, _error(409, "deductibles_required", "Complete Deductibles in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and not _text(payload, "reinsuredRetention"):
        return None, kind, _error(409, "reinsured_retention_required", "Complete Reinsured’s Retention in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        situations = get(payload, "situations")
        if not isinstance(situations, list) or not situations or any(not isinstance(row, dict) or not _text(row, "address") for row in situations):
            return None, kind, _error(409, "situation_address_required", "Complete Risk Address for every Situation in the case before generating a Cover Note.")
        if any(not re.fullmatch(r"[0-9]{3,6}", _text(row, "postcode")) for row in situations):
            return None, kind, _error(409, "situation_postcode_required", "Complete a 3–6 digit Postcode for every Situation in the case before generating a Cover Note.")
    if kind in ("cover", "debit") and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and not _text(payload, "originalPremium"):
        return None, kind, _error(409, "original_premium_required", "Complete 100% Premium in the case before generating a Cover Note or Debit Note.")
    if kind in ("cover", "debit") and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        reinsurers = get(payload, "reinsurers")
        if not isinstance(reinsurers, list) or not reinsurers or any(not isinstance(row, dict) or not _text(row, "sharePct") for row in reinsurers):
            return None, kind, _error(409, "order_hereon_required", "Add at least one Reinsurer and complete Order hereon for every Reinsurer in the case before generating a Cover Note or Debit Note.")
    if kind == "cover" and not is_standard_cgl(payload) and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        sums = get(payload, "sumInsured")
        if not isinstance(sums, list) or not sums or any(not isinstance(row, dict) or not _text(row, "category") for row in sums):
            return None, kind, _error(409, "sum_insured_name_required", "Add at least one Sum Insured entry and complete Interest insured for every entry before generating a Cover Note.")
    if kind == "cover" and not is_standard_cgl(payload) and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        sums = get(payload, "sumInsured")
        if any(not js_is_finite(js_to_number(get(row, "amount"))) or js_to_number(get(row, "amount")) <= 0 for row in sums):
            return None, kind, _error(409, "sum_insured_amount_required", "Enter an Amount greater than 0 for every Sum Insured entry before generating a Cover Note.")
    if kind == "cover" and not is_standard_cgl(payload) and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        issues = placement_issues(payload)
        if any(issue["kind"] == "location" for issue in issues):
            return None, kind, _error(409, "sum_insured_locations_required", "Assign every Sum Insured entry to a valid Location and add at least one entry for every Location before generating a Cover Note.")
        if any(issue["kind"] == "duplicate" for issue in issues):
            return None, kind, _error(409, "sum_insured_duplicate_names", "Use unique Interest insured names within each Location or the Facility items before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and not _text(payload, "lossAdvisedDate"):
        return None, kind, _error(409, "loss_advised_date_required", "Complete the Loss Record advised date in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and not _text(payload, "lossRecordYears"):
        return None, kind, _error(409, "loss_record_years_required", "Complete Past year(s) in the Loss Record section of the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        losses = get(payload, "lossRecord")
        if isinstance(losses, list) and any(not isinstance(row, dict) or not _text(row, "date") for row in losses):
            return None, kind, _error(409, "loss_record_date_required", "Complete Date of Loss for every Loss Record entry in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        losses = get(payload, "lossRecord")
        if isinstance(losses, list) and any(not isinstance(row, dict) or not _text(row, "cause") for row in losses):
            return None, kind, _error(409, "loss_record_cause_required", "Complete Cause for every Loss Record entry in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        losses = get(payload, "lossRecord")
        if isinstance(losses, list) and any(not isinstance(row, dict) or not _text(row, "lossPaid") for row in losses):
            return None, kind, _error(409, "loss_record_paid_required", "Complete Loss Paid for every Loss Record entry in the case before generating a Cover Note.")
    if kind == "cover" and _text(payload, "reinsuranceStructure") in ("QS", "XOL"):
        reinsurers = get(payload, "reinsurers")
        if isinstance(reinsurers, list) and any(not isinstance(row, dict) or not _text(row, "name") for row in reinsurers):
            return None, kind, _error(409, "reinsurer_name_required", "Complete the Reinsurer name for every Schedule of Security entry in the case before generating a Cover Note.")
    if kind == "debit" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and get(payload, "installmentEnabled") is not True:
        reinsurers = get(payload, "reinsurers")
        from .calc.payment_terms import _resolved_terms
        if any(not _valid_payment_terms(_resolved_terms(payload, {}, row, index)) for index, row in enumerate(reinsurers)):
            return None, kind, _error(409, "debit_payment_terms_required", 'Complete valid Payment Terms Days (an integer of at least 15) independently for every Reinsurer, before generating a Debit Note.')
    if kind == "debit" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and get(payload, "installmentEnabled") is True:
        installments = get(payload, "performanceInstallments")
        if not isinstance(installments, list) or not installments or any(not _valid_installment_base_date(get(row, "paymentBaseDate")) for row in installments):
            return None, kind, _error(409, "debit_installment_base_date_required", 'Add at least one installment and complete a valid Payment Base Date for every installment before generating a Debit Note.')
    if kind == "debit" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and get(payload, "installmentEnabled") is True:
        for installment in get(payload, "performanceInstallments"):
            for index, reinsurer in enumerate(get(payload, "reinsurers")):
                from .calc.payment_terms import _resolved_terms
                sources = (_resolved_terms(payload, installment, reinsurer, index),)
                if not any(_valid_payment_terms(value) for value in sources):
                    return None, kind, _error(409, "debit_installment_payment_terms_required", 'Complete valid Payment Terms Days (an integer of at least 15) for every Reinsurer in every installment before generating a Debit Note.')
    if kind == "debit" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and get(payload, "installmentEnabled") is True:
        if any(not _text(row, "premium") and not _text(row, "ratio") for row in get(payload, "performanceInstallments")):
            return None, kind, _error(409, "debit_installment_allocation_required", 'Complete Premium or Ratio for every installment before generating a Debit Note.')
        if any(not _valid_debit_installment_allocation(row) for row in get(payload, "performanceInstallments")):
            return None, kind, _error(409, "debit_installment_allocation_positive_required", 'Use a Premium or Ratio greater than 0 for every installment before generating a Debit Note.')
    if kind == "debit" and _text(payload, "reinsuranceStructure") in ("QS", "XOL") and _text(payload, "currency").upper() not in ("USD", "TWD"):
        return None, kind, _error(409, "debit_bank_currency_unsupported", 'Debit Note generation is available only for USD and TWD. The receiving bank account for other currencies is pending confirmation.')
    return case, kind, None


def _audit(request, case, kind, fmt):
    with transaction.atomic():   # 專案規則：Audit 一律在交易內寫入（audit.services._guard）
        record_audit(entity_type="case", entity_id=case.case_uid, action="generate_document",
                     after={"kind": kind, "format": fmt, "twRef": case.tw_ref, "rowVersion": case.row_version},
                     actor=actor_from(request.ri_principal), request_id=request_id_from(request),
                     metadata={"kind": kind, "format": fmt})


class RenderDocumentPdfView(NoStoreMixin, APIView):
    """Retired compatibility endpoint; no markup is rendered or logged."""
    permission_classes = [RIPermission]
    permission_map = {"POST": "documents.read"}

    def post(self, request):
        return _error(410, "pdf_generation_retired", "PDF generation is no longer available. Download Word (.docx) and export it to PDF in Word.")


class DocumentGenerationLogView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"POST": "documents.read"}

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        if _text(body, "format") != "docx":
            return _error(400, "invalid_document_format", "Only Word (docx) generation is available.")
        case, kind, err = _check_case(request, body)
        if err:
            return err
        _audit(request, case, kind, "docx")
        return Response(status=204)
