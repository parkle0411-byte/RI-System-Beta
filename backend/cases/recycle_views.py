"""
Draft 回收桶 API - 對應 Hatchable Alpha 的 api/draft-recycle-bin.js。

  GET  /api/draft-recycle-bin    recycle.read   待還原的項目（最多 250 筆）
  POST /api/draft-recycle-bin    recycle.write  action = recycle {caseUid, rowVersion} | restore {recycleId}

規則（與 Alpha 相同）：只有 Draft 能丟進回收桶；5 年內可以還原；永久刪除一律禁止（沒有這個動作）。
與 Alpha 的差異（記在 MIGRATION-STATUS.md）：丟棄與還原都補寫 Snapshot（Alpha 只寫 Audit）。
"""
import uuid
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from .calc.jsnum import js_is_integer, js_slice, js_to_number, js_to_string, js_trim
from .models import RECYCLE_RETENTION_YEARS, Case, DraftRecycleBin
from .views import _first_text

LIST_LIMIT = 250
POLICY = {"retentionYears": RECYCLE_RETENTION_YEARS, "permanentDeleteAllowed": False}


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


def clean(value, max_len=100):
    """String(value == null ? '' : value).trim().slice(0, max)"""
    return js_slice(js_trim("" if value is None else js_to_string(value)), 0, max_len)


def _integer(value):
    number = js_to_number(value)
    return int(number) if js_is_integer(number) else None


def add_years_pg(moment, years):
    """PostgreSQL 的 timestamp + interval 'N years'：2/29 遇到平年變成 2/28（與 Alpha 相同）。"""
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:
        return moment.replace(year=moment.year + years, day=28)


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def row_snapshot(case):
    """對應 Alpha 的 to_jsonb(c)：案件這一列的所有欄位（資料庫欄位名稱）。"""
    return {field.column: _json_value(getattr(case, field.attname)) for field in Case._meta.concrete_fields}


def item_view(item, now):
    case = item.original_case
    payload = case.payload if isinstance(case.payload, dict) else {}
    return {
        "id": item.pk, "originalCaseId": item.original_case_id, "caseUid": str(case.case_uid),
        "rowVersion": case.row_version, "originalCaseVersion": item.original_case_version,
        "originalInsured": _first_text(payload, "originalInsured", "original_insured"),
        "caseKind": case.case_kind, "deletedBy": item.deleted_by, "deletedAt": item.deleted_at,
        "restoreDeadline": item.restore_deadline,
        "canRestore": item.restored_at is None and item.restore_deadline >= now,
    }


class DraftRecycleBinView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "recycle.read", "POST": "recycle.write"}

    def get(self, request):
        now = timezone.now()
        items = (
            DraftRecycleBin.objects.select_related("original_case")
            .filter(restored_at__isnull=True, permanently_deleted_at__isnull=True, original_case__recycled_at__isnull=False)
            .order_by("-deleted_at", "-id")[:LIST_LIMIT]
        )
        return Response({"ok": True, **POLICY, "items": [item_view(i, now) for i in items]})

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        action = clean(body.get("action"), 40)
        if action == "recycle":
            return self.recycle(request, body)
        if action == "restore":
            return self.restore(request, body)
        return _error(400, "unsupported_action",
                      "Only recycle and restore actions are supported. Permanent deletion is prohibited.")

    # ---- 丟進回收桶 ----
    def recycle(self, request, body):
        case_uid = clean(body.get("caseUid"), 80)
        expected = _integer(body.get("rowVersion"))
        if not case_uid or expected is None or expected < 1:
            return _error(400, "case_version_required", "caseUid and a valid rowVersion are required.")
        try:
            parsed = uuid.UUID(case_uid)
        except ValueError:
            parsed = None
        actor = actor_from(request.ri_principal)
        with transaction.atomic():
            case = Case.objects.select_for_update().filter(case_uid=parsed).first() if parsed else None
            if case is None:
                return _error(404, "case_not_found", "Case was not found.")
            if case.status != "draft":
                return _error(409, "draft_required", "Only Draft cases can be moved to the recycle bin.")
            if case.recycled_at:
                return _error(409, "already_recycled", "This Draft is already in the recycle bin.")
            if case.row_version != expected:
                return _error(409, "version_conflict", "This Draft changed. Refresh before recycling it.",
                              currentRowVersion=case.row_version)
            before = row_snapshot(case)
            now = timezone.now()
            item = DraftRecycleBin.objects.create(
                original_case=case, original_case_version=expected, case_snapshot=before,
                deleted_by=actor["id"], deleted_at=now,
                restore_deadline=add_years_pg(now, RECYCLE_RETENTION_YEARS),
            )
            case.recycled_by = actor["id"]
            case.recycled_at = now
            case.row_version += 1
            case.updated_by = actor["id"]
            case.save()
            record_snapshot(entity_type="case", entity_id=case.case_uid, version=case.row_version,
                            reason="draft_recycled", data=row_snapshot(case), created_by=actor["id"])
            record_audit(entity_type="case", entity_id=case.case_uid, action="recycle_draft", before=before,
                         after={"caseUid": str(case.case_uid), "status": "draft", "recycled": True, **POLICY},
                         actor=actor, request_id=request_id_from(request), metadata=POLICY)
        return Response({"ok": True, "recycleId": item.pk, "restoreDeadline": item.restore_deadline,
                         "rowVersion": case.row_version})

    # ---- 還原 ----
    def restore(self, request, body):
        recycle_id = _integer(body.get("recycleId"))
        if recycle_id is None or recycle_id < 1:
            return _error(400, "recycle_id_required", "A valid recycleId is required.")
        actor = actor_from(request.ri_principal)
        with transaction.atomic():
            item = DraftRecycleBin.objects.select_for_update().filter(pk=recycle_id).first()
            if item is None:
                return _error(404, "recycle_item_not_found", "Recycle-bin item was not found.")
            case = Case.objects.select_for_update().get(pk=item.original_case_id)
            if item.restored_at:
                return _error(409, "already_restored", "This Draft was already restored.")
            if not case.recycled_at:
                return _error(409, "case_not_recycled", "The Draft is not currently recycled.")
            now = timezone.now()
            if item.restore_deadline < now:
                return _error(409, "restore_window_expired",
                              "The five-year restore window has expired. The retained record cannot be restored through the application.")
            before = row_snapshot(case)
            after = {**before, "recycled_by": None, "recycled_at": None, "row_version": case.row_version + 1}
            item.restored_by = actor["id"]
            item.restored_at = now
            item.save(update_fields=["restored_by", "restored_at"])
            case.recycled_by = None
            case.recycled_at = None
            case.row_version += 1
            case.updated_by = actor["id"]
            case.save()
            record_snapshot(entity_type="case", entity_id=case.case_uid, version=case.row_version,
                            reason="draft_restored", data=row_snapshot(case), created_by=actor["id"])
            record_audit(entity_type="case", entity_id=case.case_uid, action="restore_draft", before=before,
                         after=after, actor=actor, request_id=request_id_from(request),
                         metadata={"recycleId": recycle_id, **POLICY})
        return Response({"ok": True, "caseUid": str(case.case_uid), "rowVersion": case.row_version,
                         "restoredAt": case.updated_at})

