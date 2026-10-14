"""Authoritative endorsement terms and explicitly requested legacy consolidation."""
import copy
import re

from audit.services import CLI_ACTOR, record_audit, record_snapshot
from coordination.services import PRODUCTION_SOURCES, serialized

from .models import Case


def apply_endorsement_terms(payload, root, *, announced_at=None):
    """The original policy owns Cedant days; the server owns Announce time."""
    from .calc.swiss_facility import applies as swiss_applies
    payload["paymentTermsDays"] = 90 if swiss_applies(payload) else (root.payload or {}).get("paymentTermsDays")
    payload["cedantTermsBasis"] = "case"
    payload["installmentEnabled"] = False
    payload["performanceInstallments"] = []
    payload["endorsementAnnouncedAt"] = announced_at.isoformat() if announced_at else ""


def consolidate_existing_endorsement(case_uid, performance_month, *, expected_version=None):
    """Consolidate only an explicitly identified, unbooked endorsement.

    Existing closed reports and cash/ledger history are never rewritten. Its chosen
    original performance month is retained, with the usual closed-month deferral.
    Repeating the same repair creates no versions, snapshots or deferrals.
    """
    if not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", performance_month):
        raise ValueError("A valid performance month is required.")
    from production.deferrals import defer_closed_production
    from production.models import ProductionExclusion, ProductionReport

    with serialized(PRODUCTION_SOURCES):
        case = Case.objects.select_for_update().get(case_uid=case_uid)
        if case.case_kind != "endorsement" or not case.parent_case_id or case.announced_at is None:
            raise ValueError("An announced endorsement with an original policy is required.")
        root = Case.objects.select_for_update().get(pk=case.parent_case_id, parent_case__isnull=True)
        original = copy.deepcopy(case.payload)
        payload = copy.deepcopy(original)
        apply_endorsement_terms(payload, root, announced_at=case.announced_at)
        payload["endorsementPerformanceMonth"] = performance_month
        if payload == original:
            return {"changedCaseCount": 0, "caseUid": str(case.case_uid), "rowVersion": case.row_version}
        if expected_version is not None and case.row_version != expected_version:
            raise ValueError("The endorsement changed since the approved inventory. Review again.")
        if case.status != "posted" or case.is_archived or case.recycled_at:
            raise ValueError("Only an active Announced endorsement can be consolidated.")
        if any(original.get(key) for key in ("paymentEntries", "transactions", "confirmedProductionKeys")):
            raise ValueError("Existing cash, ledger entries or confirmed production require separate handling.")
        for report in ProductionReport.objects.filter(status="closed"):
            if any(isinstance(row, dict) and str(row.get("caseUid")) == str(case.case_uid)
                   for row in report.rows):
                raise ValueError("The endorsement already appears in a closed production report.")
        if ProductionExclusion.objects.filter(case=case).exists():
            raise ValueError("Existing production exclusions require separate handling.")
        allowed = {"paymentTermsDays", "cedantTermsBasis", "installmentEnabled", "performanceInstallments",
                   "endorsementAnnouncedAt", "endorsementPerformanceMonth"}
        assert {k: v for k, v in original.items() if k not in allowed} == {
            k: v for k, v in payload.items() if k not in allowed}
        version = case.row_version
        case.payload = payload
        case.row_version += 1
        case.updated_by = CLI_ACTOR["id"]
        case.save(update_fields=["payload", "row_version", "updated_by", "updated_at"])
        deferrals = defer_closed_production(case, CLI_ACTOR)
        after = {"caseUid": str(case.case_uid), "twRef": case.tw_ref, "status": case.status,
                 "rowVersion": case.row_version, "payload": payload, "productionDeferrals": deferrals}
        record_snapshot(entity_type="case", entity_id=case.case_uid, version=case.row_version,
                        reason="endorsement_single_settlement", data=after, created_by=CLI_ACTOR["id"])
        record_audit(entity_type="case", entity_id=case.case_uid, action="endorsement_single_settlement",
                     before={"rowVersion": version, "payload": original}, after=after,
                     actor=CLI_ACTOR, source="cli", metadata={"performanceMonth": performance_month})
        return {"changedCaseCount": 1, "caseUid": str(case.case_uid), "twRef": case.tw_ref,
                "rowVersion": case.row_version, "performanceMonth": performance_month,
                "productionDeferrals": deferrals}
