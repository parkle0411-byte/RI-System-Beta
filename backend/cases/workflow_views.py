"""
案件流程 API - 對應 Hatchable Alpha 的 api/case-announce.js 與 api/case-workflow.js。

  POST /api/case-announce    cases.announce  Draft → Announced（產生 TW Reference）
  GET  /api/case-workflow    cases.read.all  這個案件的流程狀態（案件鏈、可執行的動作、會計人員）
  POST /api/case-workflow    cases.write     action = create_endorsement | create_renewal | reverse_case | notify_accounting

Reverse 與「通知會計」補寫 Snapshot、TW Reference 的流水號不截斷、Reverse 遇到空交易項目回 409：
原本是與 Alpha v53 的差異，2026-09-29 已同步回 Alpha v59（兩邊相同，見 VM-RULES.md）。
仍然與 Alpha 不同：
  - 同一個案件鏈的所有動作都先鎖住「根案件」那一列（Alpha 用 PostgreSQL 的 advisory lock 與事後檢查），
    所以檢查與寫入在同一個鎖之內，同時送出的兩個請求會依序處理。
"""
from .facility_selection import selection_issues as facility_selection_issues

import copy
from .accounting_rules import premium_activity
import uuid
from datetime import datetime, timezone as dt_timezone

from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from coordination.services import PRODUCTION_SOURCES, serialized
from production.deferrals import defer_closed_production
from audit.services import record_audit, record_snapshot, request_id_from
from personnel.models import Personnel
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from . import workflow as wf
from .calc.jsnum import get, is_array, js_is_integer, js_or, js_to_number, js_to_string, js_trim
from .draft import text, validate_announce_ready
from .sum_insured import limit_warning
from .models import Case, CaseDocument, ReferenceSequence
from .manual_reference import prepare_auw_workflow_draft, is_pure_auw_case, manual_reference_error, reference_in_use
from .renewal_premiums import RenewalPremiumError, calculate_renewal_premiums, renewal_installment_issues

DISPLAY_VERSION = "V 0.003"
ACCOUNTING_DEPARTMENTS = ("accounting", "finance")
ACCOUNTING_ROLES = ("accounting_staff", "accounting_manager")


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _live(qs):
    return qs.filter(recycled_at__isnull=True, is_archived=False)


def _find_case(case_uid, lock=False):
    parsed = _parse_uuid(case_uid)
    if parsed is None:
        return None
    qs = _live(Case.objects.select_for_update() if lock else Case.objects).filter(case_uid=parsed)
    return qs.first()


def _integer_version(value):
    number = js_to_number(value)
    return int(number) if js_is_integer(number) else None


def _payload(case):
    return case.payload if isinstance(case.payload, dict) else {}


def _time(value):
    return "00:00" if value == "00:00" else "12:00"


def case_view(case, payload=None):
    p = _payload(case) if payload is None else payload
    text_of = lambda key: js_or(p.get(key), "")
    return {
        "id": case.pk, "caseUid": str(case.case_uid), "twRef": case.tw_ref, "status": case.status,
        "caseKind": case.case_kind, "rowVersion": case.row_version, "parentCaseId": case.parent_case_id,
        "originalInsured": text_of("originalInsured"),
        "policyFrom": text_of("policyFrom"), "policyFromTime": _time(p.get("policyFromTime")),
        "policyTo": text_of("policyTo"), "policyToTime": _time(p.get("policyToTime")),
        "endoEffectiveDate": text_of("endoEffectiveDate"),
        "endoTypes": p["endoTypes"] if is_array(p.get("endoTypes")) else [],
        "endoText": text_of("endoText"),
        "createdAt": case.created_at, "updatedAt": case.updated_at,
    }


def _snapshot_data(case, payload, **extra):
    return {"caseUid": str(case.case_uid), "twRef": case.tw_ref, "status": case.status,
            "rowVersion": case.row_version, "payload": payload, **extra}


# ------------------------------------------------------------------ Announce

class AnnounceView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"POST": "cases.announce"}

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        case_uid = js_trim(js_to_string(js_or(body.get("caseUid"), "")))
        expected_version = _integer_version(body.get("rowVersion"))
        if not case_uid:
            return _error(400, "case_uid_required", "caseUid is required.")
        if expected_version is None or expected_version < 1:
            return _error(400, "row_version_required", "A valid rowVersion is required.")
        if body.get("confirmed") is not True:
            return _error(400, "confirmation_required",
                          "Confirm that the selected documents and e-mails match the latest case terms.")

        actor_info = actor_from(request.ri_principal)
        conflict = None
        try:
            with serialized(PRODUCTION_SOURCES):
                response = self._announce(request, case_uid, expected_version, body, actor_info)
        except IntegrityError:
            conflict = _error(409, "reference_conflict", "The TW Reference is already in use. Reload and try again.")
        return conflict or response

    def _announce(self, request, case_uid, expected_version, body, actor_info):
        current = _find_case(case_uid, lock=True)
        if current is None:
            return _error(404, "case_not_found", "Case was not found.")
        if current.status != "draft":
            return _error(409, "only_draft_can_announce", "Only a Draft case can be Announced.")
        if current.row_version != expected_version:
            return _error(409, "version_conflict", "This Draft changed after the review opened. Reload and review it again.",
                          currentRowVersion=current.row_version)
        if not current.owner_personnel_id:
            return _error(400, "case_owner_required", "Assign a Case Owner before Announce.")

        from .data_integrity import financial_issues
        integrity=financial_issues(current.payload)
        if integrity:
            return _error(400,'case_not_ready','Case data is invalid. Amounts are pending confirmation.',issues=integrity)
        payload = copy.deepcopy(_payload(current))
        from .draft_input import validate as validate_draft_input
        payload, draft_errors = validate_draft_input(payload)
        if draft_errors:
            return _error(400, 'case_not_ready', 'Correct invalid Draft input before Announce.', issues=draft_errors)
        now = timezone.now()
        if current.case_kind == "endorsement":
            from .endorsement_terms import apply_endorsement_terms
            root = _live(Case.objects).filter(pk=current.parent_case_id, parent_case__isnull=True).first()
            if root is None:
                return _error(409, "root_reference_required", "The root policy is required before endorsement Announce.")
            latest = _live(Case.objects).filter(parent_case_id=root.pk).order_by('-id').first()
            if latest is not None and latest.pk != current.pk:
                return _error(409, 'latest_endorsement_required', 'A newer endorsement exists. Continue from the latest case in the chain.', latestCaseUid=str(latest.case_uid))
            if payload.get("installmentEnabled") is True or payload.get("performanceInstallments"):
                return _error(400, "endorsement_installments_not_allowed", "Endorsements must use a single premium settlement.")
            from .endorsement_rules import context_for, apply_fixed
            apply_fixed(payload, context_for(current))
            apply_endorsement_terms(payload, root, announced_at=now)
        from .resolve import resolve_personnel_splits, resolve_case_owner
        historical_split_ids = [p.get('personnelId') for p in (payload.get('endorsementSource', {}).get('fixed', {}).get('splitParties') or []) if isinstance(p, dict) and isinstance(p.get('personnelId'), int) and p['personnelId'] > 0] if current.case_kind == 'endorsement' else []
        personnel_error = resolve_personnel_splits(payload, historical_split_ids)
        if current.case_kind == 'endorsement':
            apply_fixed(payload, payload['endorsementSource'])
        owner_error = resolve_case_owner(payload,current.owner_personnel_id)
        if personnel_error:
            return Response(personnel_error,status=400)
        if "error" in owner_error:
            return Response(owner_error,status=400)
        issues = validate_announce_ready(payload, allow_zero_loss_years=True, case_kind=current.case_kind)
        if current.case_kind == "renewal":
            issues.extend(renewal_installment_issues(payload))
        if issues:
            n = len(issues)
            return _error(400, "case_not_ready", f"Complete {n} required field{'' if n == 1 else 's'} before Announce.", issues=issues)

        ref_error = manual_reference_error(payload, exclude_case_uid=current.case_uid)
        if ref_error:
            return _error(409, "manual_reference_conflict", ref_error)
        pure_auw = is_pure_auw_case(payload)
        files = [
            {"id": d.pk, "kind": d.kind, "reinsurers": d.reinsurers, "is_selected": d.is_selected}
            for d in CaseDocument.objects.filter(case=current).order_by("uploaded_at", "id")
        ]
        coverage = wf.coverage_for(payload, files)
        if not coverage["ready"]:
            return _error(400, "documents_not_ready",
                          ("Announce requires an Endorsement plus a Signed Slip or Confirmation E-mail covering every reinsurer." if current.case_kind == "endorsement" else "Announce requires an Offer Slip plus a Signed Slip or Confirmation E-mail covering every reinsurer."),
                          coverage=coverage)
        if not wf.same_ids(body.get("documentIds"), coverage["selected"]):
            return _error(409, "document_review_outdated",
                          "The selected documents changed after the review opened. Reload and review them again.",
                          coverage=coverage)

        prefix, digits = wf.reference_prefix(payload), 3
        if current.case_kind == "endorsement":
            root = _live(Case.objects).filter(pk=current.parent_case_id, parent_case__isnull=True).first()
            if root is None or not root.tw_ref:
                return _error(409, "root_reference_required", "The root case must have a TW Reference before endorsement Announce.")
            prefix, digits = f"{root.tw_ref}-E", 2
            from .manual_reference import requires_manual_tw_ref
            auw_base = (root.payload or {}).get('manualTwRef') or (root.tw_ref if (root.payload or {}).get('twRefSource') == 'auw_manual' else '')
            if requires_manual_tw_ref(payload) and not auw_base:
                return _error(409, "source_auw_reference_required", "The Original AUW reference is required to derive the endorsement reference.")
        if not pure_auw and not prefix:
            return _error(400, "effective_date_required", "A valid Effective date is required before Announce.")

        from . import insured_master
        try:
            current.insured_master=insured_master.sync(current,payload,actor_info,body)
        except insured_master.MergeRequired as exc:
            return Response(exc.data,status=409)
        if payload.get(insured_master.KEY) and not current.insured_master_id:
            return _error(400,'insured_master_required','Link an insured master before Announce.')

        before = {"caseUid": case_uid, "twRef": current.tw_ref, "status": current.status,
                  "rowVersion": current.row_version, "payload": _payload(current)}
        review = {"confirmed": True, "documentIds": coverage["selected"], "confirmedBy": actor_info["id"]}
        was_endorsement = current.case_kind == "endorsement"

        from .property_original import enabled as property_enabled, refresh_transactions, persist_settlements
        correcting_original = property_enabled(payload) and bool(current.tw_ref)
        if correcting_original:
            pass  # Corrected Original reuses its immutable reference.
        elif current.case_kind == "endorsement":
            while True:
                with connection.cursor() as cursor:
                    cursor.execute("INSERT INTO ri_reference_sequences (prefix, `last_value`, updated_at) VALUES (%s, 1, %s) AS new ON DUPLICATE KEY UPDATE `last_value` = ri_reference_sequences.`last_value` + 1, updated_at = new.updated_at", [prefix, now])
                    cursor.execute("SELECT `last_value` FROM ri_reference_sequences WHERE prefix = %s", [prefix])
                    sequence = cursor.fetchone()[0]
                suffix = "-E" + str(sequence).zfill(2)
                primary = str(root.tw_ref) + suffix
                auw = str(auw_base) + suffix if requires_manual_tw_ref(payload) else ""
                if not reference_in_use(primary) and (not auw or auw == primary or not reference_in_use(auw)):
                    current.tw_ref = primary
                    payload["endorsementSeq"] = sequence
                    if auw:
                        payload["manualTwRef"] = auw
                    payload["twRefSource"] = "auw_manual" if pure_auw and primary == auw else "system"
                    break
        elif pure_auw:
            # No sequence row is read, created or consumed for a pure AUW original/renewal.
            current.tw_ref = payload["manualTwRef"]
            payload["twRefSource"] = "auw_manual"
        else:
            # Avoid references already reserved by a manual AUW Draft or history.
            while True:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO ri_reference_sequences (prefix, `last_value`, updated_at) VALUES (%s, 1, %s) AS new "
                        "ON DUPLICATE KEY UPDATE `last_value` = ri_reference_sequences.`last_value` + 1, updated_at = new.updated_at",
                        [prefix, now])
                    cursor.execute("SELECT `last_value` FROM ri_reference_sequences WHERE prefix = %s", [prefix])
                    sequence = cursor.fetchone()[0]
                candidate = prefix + str(sequence).zfill(digits)
                if not reference_in_use(candidate):
                    current.tw_ref = candidate
                    break
            payload["twRefSource"] = "system"
        if property_enabled(payload):
            payload.update(twRef=current.tw_ref,announcedAt=now.isoformat(),postedAt=now.isoformat())
            refresh_transactions(payload,now.isoformat())
            persist_settlements(payload,now.isoformat(),actor_info)
        from .endorsement_rules import all_zero
        current.status = "closed" if was_endorsement and all_zero(payload) else "posted"
        if was_endorsement:
            payload["status"] = current.status
        current.row_version += 1
        current.announced_by = actor_info["id"]
        current.announced_at = now
        current.payload = payload
        current.updated_by = actor_info["id"]
        current.save()
        deferrals = defer_closed_production(current, actor_info, request_id_from(request))

        after = _snapshot_data(current, payload, documentReview=review, productionDeferrals=deferrals)
        record_snapshot(entity_type="case", entity_id=current.case_uid, version=current.row_version,
                        reason="announced", data=after, created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=current.case_uid,
                     action="announce_endorsement" if was_endorsement else "announce",
                     before=before, after=after, actor=actor_info, request_id=request_id_from(request),
                     metadata={"displayVersion": DISPLAY_VERSION, "milestone": "review-announce",
                               "documentIds": coverage["selected"]})
        warning = limit_warning(payload)
        return Response({
            "ok": True, "displayVersion": DISPLAY_VERSION, "productionDeferrals": deferrals,
            "warnings": [warning] if warning else [],
            "case": {"caseUid": str(current.case_uid), "twRef": current.tw_ref, "status": current.status,
                     "rowVersion": current.row_version, "announcedAt": current.announced_at},
        })


# ------------------------------------------------------------------ Workflow

def _accounting_staff():
    people = [
        p for p in Personnel.objects.filter(is_active=True)
        if (p.department or "").lower() in ACCOUNTING_DEPARTMENTS or (p.role_code or "").lower() in ACCOUNTING_ROLES
    ]
    return sorted(people, key=lambda p: ((p.name or "").lower(), p.pk))


def _root_for(case):
    if not case.parent_case_id:
        return case
    return _live(Case.objects).filter(pk=case.parent_case_id).first()


class WorkflowView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "cases.read.all", "POST": "cases.write"}

    def get(self, request):
        case_uid = text(request.query_params.get("caseUid"), 80)
        if not case_uid:
            return _error(400, "case_uid_required", "caseUid is required.")
        source = _find_case(case_uid)
        if source is None:
            return _error(404, "case_not_found", "Case was not found.")
        root = _root_for(source)
        if root is None:
            return _error(404, "root_case_not_found", "The root case was not found.")
        children = list(_live(Case.objects).filter(parent_case_id=root.pk).order_by("id"))
        chain = [case_view(c) for c in [root, *children]]
        latest = chain[-1]
        from .property_original import enabled as property_enabled
        notes = _payload(source).get("accountingNotifications")
        # 2026-10-14：續保只能從「最新且已確認」的案件建立，而且鏈上的批單都要處理完；畫面據此說明按鈕為什麼不見
        renewal_notice = ""
        if source.status == "closed":
            if str(source.case_uid) != latest["caseUid"]:
                renewal_notice = "Renewal is not available because a newer endorsement exists. Complete or discard it, then renew from the latest Confirmed case."
            elif any(child.status not in ("posted", "closed") for child in children):
                renewal_notice = "Renewal is not available until every endorsement in this policy chain is Announced or Confirmed."
        return Response({"ok": True, "workflow": {
            "root": case_view(root), "chain": chain, "latestCaseUid": latest["caseUid"],
            "accountingStaff": [{"id": p.pk, "name": p.name} for p in _accounting_staff()],
            "notifications": notes if is_array(notes) else [],
            "actions": {
                "canCreateEndorsement": str(source.case_uid) == latest["caseUid"] and source.status in ("posted", "closed"),
                "canRenew": str(source.case_uid) == latest["caseUid"] and source.status == "closed",
                "renewalNotice": renewal_notice,
                "canEditAnnounced": source.status in ("posted", "reversed"),
                "canReverse": (source.status == "closed" or source.status == "posted" and property_enabled(_payload(source))) and not premium_activity(_payload(source)) and not any(t.get("settlement")=="settled" and t.get("source")!="claim" and not t.get("reversed") and not t.get("isReversalEntry") for t in (_payload(source).get("transactions") or []) if isinstance(t,dict)),
                "canNotifyAccounting": source.status in ("posted", "reversed"),
            },
        }})

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        case_uid = text(body.get("caseUid"), 80)
        if not case_uid:
            return _error(400, "case_uid_required", "caseUid is required.")
        action = text(body.get("action"), 60)
        handlers = {
            "create_endorsement": self.create_endorsement, "create_renewal": self.create_renewal,
            "reverse_case": self.reverse_case, "notify_accounting": self.notify_accounting,
        }
        actor_info = actor_from(request.ri_principal)
        try:
            with serialized(PRODUCTION_SOURCES):
                first = _find_case(case_uid)
                if first is None:
                    return _error(404, "case_not_found", "Case was not found.")
                # 同一個案件鏈的動作依序處理：先鎖根案件，再鎖要操作的案件
                _live(Case.objects.select_for_update()).filter(pk=first.parent_case_id or first.pk).first()
                source = _find_case(case_uid, lock=True)
                if source is None:
                    return _error(404, "case_not_found", "Case was not found.")
                if action not in handlers:
                    return _error(400, "unsupported_action", "Unsupported case workflow action.")
                from .data_integrity import response_error
                invalid=response_error(source.payload)
                if invalid is not None:return invalid
                return handlers[action](source, request, body, actor_info)
        except IntegrityError:
            return _error(409, "version_conflict", "This case changed while the action was being applied. Reload and try again.")

    # ---- Endorsement ----
    def create_endorsement(self, source, request, body, actor_info):
        expected = _integer_version(body.get("rowVersion"))
        if expected is None or expected != source.row_version:
            return _error(409, "version_conflict", "This case changed elsewhere. Reload before creating the endorsement.",
                          currentRowVersion=source.row_version)
        if source.status not in ("posted", "closed"):
            return _error(409, "endorsement_source_status", "Create an endorsement from an Announced or Confirmed case.")
        root = _root_for(source)
        if root is None or not root.tw_ref:
            return _error(409, "root_reference_required", "The root case must have a TW Reference before endorsement.")
        newest_child = _live(Case.objects).filter(parent_case_id=root.pk).order_by("-id").first()
        latest = newest_child or root
        if latest.pk != source.pk:
            return _error(409, "latest_endorsement_required",
                          "A newer endorsement already exists. Continue from the latest case in the chain.",
                          latestCaseUid=str(latest.case_uid))
        count = _live(Case.objects).filter(parent_case_id=root.pk).count()
        payload = wf.build_endorsement_payload(_payload(source), root.tw_ref, count)
        from .endorsement_terms import apply_endorsement_terms
        apply_endorsement_terms(payload, root)
        from .endorsement_rules import attach_source
        attach_source(payload, source)
        scope_issues = facility_selection_issues(payload)
        if scope_issues:
            return _error(400, "validation_failed", scope_issues[0]["label"], issues=scope_issues)
        errors = prepare_auw_workflow_draft(payload, body)
        ref_error = manual_reference_error(payload)
        if ref_error:
            return _error(409, "manual_reference_conflict", ref_error)
        if errors:
            return _error(400, "validation_failed", errors[0], errors=errors)
        case_uid = uuid.uuid4()
        created = self._insert_child(source, case_uid, "endorsement", root.pk, payload, actor_info,
                                     source.effective_date, source.expiration_date)
        after = {"caseUid": str(case_uid), "rootCaseUid": str(root.case_uid), "parentCaseId": root.pk,
                 "status": "draft", "rowVersion": 1, "payload": payload}
        record_snapshot(entity_type="case", entity_id=case_uid, version=1, reason="endorsement_created",
                        data=after, created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=case_uid, action="create_endorsement",
                     before={"sourceCaseUid": str(source.case_uid), "sourceRowVersion": source.row_version},
                     after={k: v for k, v in after.items() if k != "rowVersion"}, actor=actor_info,
                     request_id=request_id_from(request), metadata={"endorsementSequence": payload["endorsementSeq"]})
        return Response({"ok": True, "case": {**case_view(created, payload), "payload": payload}}, status=201)

    # ---- Renewal ----
    def create_renewal(self, source, request, body, actor_info):
        expected = _integer_version(body.get("rowVersion"))
        if expected is None or expected != source.row_version:
            return _error(409, "version_conflict", "This case changed elsewhere. Reload before creating the renewal.",
                          currentRowVersion=source.row_version)
        if source.status != "closed":
            return _error(409, "renewal_source_status", "Renewal is available only from a Confirmed case.")
        root = _root_for(source)
        if root is None:
            return _error(409, "root_case_not_found", "The original policy is unavailable for renewal.")
        children = list(_live(Case.objects.select_for_update()).filter(parent_case_id=root.pk).order_by("id"))
        latest = children[-1] if children else root
        if source.pk != latest.pk:
            return _error(409, "latest_endorsement_required",
                          "A newer endorsement exists. Create the renewal from the latest Confirmed case.",
                          latestCaseUid=str(latest.case_uid))
        if any(child.status not in ("posted", "closed") for child in children):
            return _error(409, "renewal_chain_review_required",
                          "This policy chain contains an unfinished or reversed endorsement. Review it before renewal.")
        if _live(Case.objects).filter(payload__renewedFromTwRef=source.tw_ref or "").exists():
            return _error(409, "renewal_already_exists",
                          "A renewal already exists for this case, or the source case changed. Reload and try again.")
        payload = wf.build_renewal_payload(_payload(source), source.tw_ref)
        from .renewal_premiums import seed_renewal_premiums
        seed_renewal_premiums(payload, _payload(root), [_payload(child) for child in children], _payload(source))
        scope_issues = facility_selection_issues(payload)
        if scope_issues:
            return _error(400, "validation_failed", scope_issues[0]["label"], issues=scope_issues)
        errors = prepare_auw_workflow_draft(payload, body)
        ref_error = manual_reference_error(payload)
        if ref_error:
            return _error(409, "manual_reference_conflict", ref_error)
        if errors:
            return _error(400, "validation_failed", errors[0], errors=errors)
        case_uid = uuid.uuid4()
        created = self._insert_child(source, case_uid, "renewal", None, payload, actor_info,
                                     payload["policyFrom"] or None, payload["policyTo"] or None)
        after = {"caseUid": str(case_uid), "renewedFromTwRef": payload["renewedFromTwRef"], "status": "draft",
                 "rowVersion": 1, "payload": payload}
        record_snapshot(entity_type="case", entity_id=case_uid, version=1, reason="renewal_created",
                        data=after, created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=case_uid, action="create_renewal",
                     before={"sourceCaseUid": str(source.case_uid), "sourceTwRef": source.tw_ref,
                             "sourceRowVersion": source.row_version},
                     after={k: v for k, v in after.items() if k != "rowVersion"}, actor=actor_info,
                     request_id=request_id_from(request), metadata={"workflow": "renewal"})
        return Response({"ok": True, "case": {**case_view(created, payload), "payload": payload}}, status=201)

    @staticmethod
    def _insert_child(source, case_uid, kind, parent_id, payload, actor_info, effective_date, expiration_date):
        from .placing_rules import promote
        promote(payload, source.payload)
        from .construction import adopt as adopt_construction
        adopt_construction(payload,source.payload)
        payload["cedantTermsBasis"] = "case"
        from .property_original import adopt, SERVER_FIELDS
        for key in SERVER_FIELDS:payload.pop(key,None)
        if kind == "renewal":
            adopt(payload)
        from . import insured_master
        insured=insured_master.sync(None,payload,actor_info,new=True,inherit_id=source.insured_master_id)
        return Case.objects.create(
            insured_master=insured,
            case_uid=case_uid, parent_case_id=parent_id, case_kind=kind, status="draft",
            reinsurance_structure=source.reinsurance_structure,
            class_master_id=source.class_master_id, class_code_snapshot=source.class_code_snapshot,
            class_name_snapshot=source.class_name_snapshot,
            reinsured_master_id=source.reinsured_master_id, reinsured_name_snapshot=source.reinsured_name_snapshot,
            ae_master_id=source.ae_master_id, ae_name_snapshot=source.ae_name_snapshot,
            currency=source.currency, effective_date=effective_date, expiration_date=expiration_date,
            payload=payload, owner_personnel_id=source.owner_personnel_id,
            created_by=actor_info["id"], updated_by=actor_info["id"],
        )

    # ---- Reverse ----
    def reverse_case(self, source, request, body, actor_info):
        from .property_original import enabled as property_enabled, reverse_payload
        if source.status != "closed" and not (property_enabled(_payload(source)) and source.status == "posted"):
            return _error(409, "reverse_status", "Only an Announced or Confirmed eligible Original case can be reversed.")
        expected = _integer_version(body.get("rowVersion"))
        if expected is None or expected != source.row_version:
            return _error(409, "version_conflict", "This case changed elsewhere. Reload before reversing.",
                          currentRowVersion=source.row_version)
        before = {"status": source.status, "rowVersion": source.row_version, "payload": _payload(source)}
        try:
            if property_enabled(_payload(source)):
                from production.models import ProductionReport
                from production.calc import next_production_month
                now=timezone.now()
                month=timezone.localtime(now).strftime("%Y-%m")
                while ProductionReport.objects.filter(year_month=month,status="closed").exists():month=next_production_month(month)
                payload=reverse_payload(_payload(source),month,now.isoformat(),actor_info,str(body.get("reason") or "Case Reverse"))
            else:
                payload = wf.build_reversed_payload(_payload(source))
        except ValueError as error:
            return _error(409, "accounting_activity_locked", str(error))
        except wf.TransactionsCorrupt:
            return _error(409, "transactions_corrupt",
                          "The transaction records of this case are damaged (an empty entry was found). Contact the system administrator.")
        source.payload = payload
        source.status = "reversed"
        source.row_version += 1
        source.updated_by = actor_info["id"]
        source.save()
        after = {"status": "reversed", "rowVersion": source.row_version, "payload": payload}
        record_snapshot(entity_type="case", entity_id=source.case_uid, version=source.row_version,
                        reason="case_reversed", data=_snapshot_data(source, payload), created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=source.case_uid, action="reverse_case", before=before, after=after,
                     actor=actor_info, request_id=request_id_from(request),
                     metadata={"reversalCycle": payload["reversalCycle"]})
        return Response({
            "ok": True,
            "case": {"caseUid": str(source.case_uid), "status": source.status, "rowVersion": source.row_version,
                     "updatedAt": source.updated_at},
            "reversalCycle": payload["reversalCycle"],
        })

    # ---- 通知會計 ----
    def notify_accounting(self, source, request, body, actor_info):
        if source.status not in ("posted", "reversed"):
            return _error(409, "notification_status", "Accounting notification is available for Announced or Reversed cases.")
        expected = _integer_version(body.get("rowVersion"))
        if expected is None or expected != source.row_version:
            return _error(409, "version_conflict", "This case changed elsewhere. Reload before recording the notification.",
                          currentRowVersion=source.row_version)
        number = js_to_number(body.get("accountingPersonnelId"))
        staff = next((p for p in _accounting_staff() if js_is_integer(number) and p.pk == int(number)), None)
        if staff is None:
            return _error(400, "accounting_staff_required", "Select an active Finance Staff or Finance Manager Personnel record.")
        now = datetime.now(dt_timezone.utc)
        notification = {
            "id": str(uuid.uuid4()), "accountingPersonnelId": staff.pk, "accountingStaffName": staff.name,
            "notifiedByName": actor_info["name"],
            "notifiedAt": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
            "note": text(body.get("note"), 2000),
        }
        old_notes = _payload(source).get("accountingNotifications")
        payload = wf.append_notification(_payload(source), notification)
        source.payload = payload
        source.row_version += 1
        source.updated_by = actor_info["id"]
        source.save()
        record_snapshot(entity_type="case", entity_id=source.case_uid, version=source.row_version,
                        reason="accounting_notified", data=_snapshot_data(source, payload), created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=source.case_uid, action="notify_accounting",
                     before={"rowVersion": expected, "accountingNotifications": old_notes if is_array(old_notes) else []},
                     after={"rowVersion": source.row_version, "accountingNotifications": payload["accountingNotifications"]},
                     actor=actor_info, request_id=request_id_from(request),
                     metadata={"accountingPersonnelId": staff.pk, "notificationId": notification["id"]})
        return Response({"ok": True, "notification": notification, "rowVersion": source.row_version,
                         "updatedAt": source.updated_at})
