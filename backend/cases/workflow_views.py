"""
案件流程 API - 對應 Hatchable Alpha 的 api/case-announce.js 與 api/case-workflow.js。

  POST /api/case-announce    cases.announce  Draft → Announced（產生 TW Reference）
  GET  /api/case-workflow    cases.read.all  這個案件的流程狀態（案件鏈、可執行的動作、會計人員）
  POST /api/case-workflow    cases.write     action = create_endorsement | create_renewal | reverse_case | notify_accounting

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - Reverse 與「通知會計」補寫 Snapshot（Alpha 只寫 Audit，Snapshot 的版本號會有缺口）。
  - TW Reference 的流水號不截斷（Alpha 的 lpad 超過 999 會被截斷而重複）。
  - 同一個案件鏈的所有動作都先鎖住「根案件」那一列（Alpha 用 PostgreSQL 的 advisory lock 與事後檢查），
    所以檢查與寫入在同一個鎖之內，同時送出的兩個請求會依序處理。
"""
import uuid
from datetime import datetime, timezone as dt_timezone

from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from personnel.models import Personnel
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from . import workflow as wf
from .calc.jsnum import get, is_array, js_is_integer, js_or, js_to_number, js_to_string, js_trim
from .draft import text, validate_announce_ready
from .models import Case, CaseDocument, ReferenceSequence

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
            with transaction.atomic():
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

        payload = _payload(current)
        issues = validate_announce_ready(payload)
        if issues:
            n = len(issues)
            return _error(400, "case_not_ready", f"Complete {n} required field{'' if n == 1 else 's'} before Announce.", issues=issues)

        files = [
            {"id": d.pk, "kind": d.kind, "reinsurers": d.reinsurers, "is_selected": d.is_selected}
            for d in CaseDocument.objects.filter(case=current).order_by("uploaded_at", "id")
        ]
        coverage = wf.coverage_for(payload, files)
        if not coverage["ready"]:
            return _error(400, "documents_not_ready",
                          "Announce requires an Offer Slip plus a Signed Slip or Confirmation E-mail covering every reinsurer.",
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
        if not prefix:
            return _error(400, "effective_date_required", "A valid Effective date is required before Announce.")

        before = {"caseUid": case_uid, "twRef": current.tw_ref, "status": current.status,
                  "rowVersion": current.row_version, "payload": payload}
        review = {"confirmed": True, "documentIds": coverage["selected"], "confirmedBy": actor_info["id"]}
        was_endorsement = current.case_kind == "endorsement"

        # 流水號：同一個 prefix 的計數器，在同一個交易內加一（upsert 會鎖住該列直到交易結束）
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO ri_reference_sequences (prefix, `last_value`, updated_at) VALUES (%s, 1, %s) AS new "
                "ON DUPLICATE KEY UPDATE `last_value` = ri_reference_sequences.`last_value` + 1, updated_at = new.updated_at",
                [prefix, now])
            cursor.execute("SELECT `last_value` FROM ri_reference_sequences WHERE prefix = %s", [prefix])  # last_value 是 MySQL 8 的保留字
            sequence = cursor.fetchone()[0]

        current.tw_ref = prefix + str(sequence).zfill(digits)
        current.status = "posted"
        current.row_version += 1
        current.announced_by = actor_info["id"]
        current.announced_at = now
        current.updated_by = actor_info["id"]
        current.save()

        after = _snapshot_data(current, payload, documentReview=review)
        record_snapshot(entity_type="case", entity_id=current.case_uid, version=current.row_version,
                        reason="announced", data=after, created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=current.case_uid,
                     action="announce_endorsement" if was_endorsement else "announce",
                     before=before, after=after, actor=actor_info, request_id=request_id_from(request),
                     metadata={"displayVersion": DISPLAY_VERSION, "milestone": "review-announce",
                               "documentIds": coverage["selected"]})
        return Response({
            "ok": True, "displayVersion": DISPLAY_VERSION,
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
        notes = _payload(source).get("accountingNotifications")
        return Response({"ok": True, "workflow": {
            "root": case_view(root), "chain": chain, "latestCaseUid": latest["caseUid"],
            "accountingStaff": [{"id": p.pk, "name": p.name} for p in _accounting_staff()],
            "notifications": notes if is_array(notes) else [],
            "actions": {
                "canCreateEndorsement": str(source.case_uid) == latest["caseUid"] and source.status in ("posted", "closed"),
                "canRenew": source.status == "closed",
                "canEditAnnounced": source.status in ("posted", "reversed"),
                "canReverse": source.status == "closed",
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
            with transaction.atomic():
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
        if _live(Case.objects).filter(payload__renewedFromTwRef=source.tw_ref or "").exists():
            return _error(409, "renewal_already_exists",
                          "A renewal already exists for this case, or the source case changed. Reload and try again.")
        payload = wf.build_renewal_payload(_payload(source), source.tw_ref)
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
        return Case.objects.create(
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
        if source.status != "closed":
            return _error(409, "reverse_status", "Only a Confirmed case can be reversed.")
        expected = _integer_version(body.get("rowVersion"))
        if expected is None or expected != source.row_version:
            return _error(409, "version_conflict", "This case changed elsewhere. Reload before reversing.",
                          currentRowVersion=source.row_version)
        before = {"status": source.status, "rowVersion": source.row_version, "payload": _payload(source)}
        try:
            payload = wf.build_reversed_payload(_payload(source))
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
