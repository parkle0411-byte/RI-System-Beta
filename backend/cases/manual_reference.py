"""Additional manually entered TW reference for the 0609 AUW Facility."""
MANUAL_TW_REF_REINSURER = "Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)"
MANUAL_TW_REF_MAX_LENGTH = 160
AUW_FOREIGN_BROKER = "Howden Specialty Limited"


def is_auw_reinsurer(name):
    return isinstance(name, str) and " ".join(name.split()).lower() == MANUAL_TW_REF_REINSURER.lower()


def requires_manual_tw_ref(payload):
    if not isinstance(payload, dict):
        return False
    rows = payload.get("reinsurers")
    if not isinstance(rows, list):
        return False
    return any(isinstance(row, dict) and is_auw_reinsurer(row.get("name")) for row in rows)


def manual_tw_ref_fields(payload):
    fields = {"manualTwRef": payload.get("manualTwRef") or ""} if requires_manual_tw_ref(payload) else {}
    if payload.get("previousTwRefs"):
        fields["previousTwRefs"] = payload["previousTwRefs"]
    return fields


def normalize_manual_tw_ref(value):
    """Use the same text and UTF-16 limits for normal and workflow-created drafts."""
    from .calc.jsnum import js_len, js_trim
    errors = []
    if value is not None and not isinstance(value, str):
        errors.append("TW Ref. (for AUW) must be text.")
        value = ""
    reference = js_trim(value or "")
    if not reference:
        errors.append("TW Ref. (for AUW) is required before saving an AUW Draft.")
    if js_len(reference) > MANUAL_TW_REF_MAX_LENGTH:
        errors.append(f"TW Ref. (for AUW) must not exceed {MANUAL_TW_REF_MAX_LENGTH} characters.")
    if any(ord(char) < 32 or ord(char) == 127 for char in reference):
        errors.append("TW Ref. (for AUW) must be a single line without control characters.")
    return reference, errors


def prepare_auw_workflow_draft(payload, body):
    """Require the new AUW reference before inserting a renewal or endorsement."""
    if not requires_manual_tw_ref(payload):
        return []
    payload["manualTwRef"], errors = normalize_manual_tw_ref(body.get("manualTwRef"))
    for row in payload["reinsurers"]:
        if isinstance(row, dict) and is_auw_reinsurer(row.get("name")):
            row["foreignBroker"] = AUW_FOREIGN_BROKER
    return errors



def is_pure_auw_case(payload):
    rows = payload.get("reinsurers") if isinstance(payload, dict) else None
    named = [r for r in rows if isinstance(r, dict) and str(r.get("name") or "").strip()] if isinstance(rows, list) else []
    return bool(named) and all(is_auw_reinsurer(r.get("name")) for r in named)


def reference_in_use(reference, *, exclude_case_uid=None):
    """Reserve primary, AUW and prior references, including archived/recycled cases.

    Writers call this inside the shared PRODUCTION_SOURCES transaction guard.
    """
    from django.db.models import Q
    from .models import Case
    reference = str(reference or "").strip()
    if not reference:
        return False
    qs = Case.objects.all()
    if exclude_case_uid is not None:
        qs = qs.exclude(case_uid=exclude_case_uid)
    if qs.filter(Q(tw_ref__iexact=reference) | Q(payload__manualTwRef__iexact=reference)).exists():
        return True
    # JSON array containment is case-sensitive on MySQL. Compare each historical
    # reference as text so an old reference cannot be reused by changing its case.
    folded = reference.casefold()
    histories = qs.filter(payload__previousTwRefs__isnull=False).exclude(payload__previousTwRefs=[])
    return any(isinstance(refs, list) and any(isinstance(ref, str) and ref.casefold() == folded for ref in refs)
               for refs in histories.values_list("payload__previousTwRefs", flat=True).iterator(chunk_size=512))


def manual_reference_error(payload, *, exclude_case_uid=None):
    if requires_manual_tw_ref(payload) and reference_in_use(payload.get("manualTwRef"), exclude_case_uid=exclude_case_uid):
        return "TW Ref. (for AUW) is already used by another case. Enter a different reference."
    return ""
