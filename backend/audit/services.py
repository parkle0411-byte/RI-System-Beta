"""
寫入 Audit Log 與 Snapshot 的共用入口（對應 Alpha 的 lib/audit.js）。

規則：
  - 必須在交易（transaction.atomic）內呼叫，讓「業務資料的變更」與「它的稽核紀錄」同生同滅：
    稽核寫入失敗，整筆業務變更一起回滾，不會出現沒有紀錄的變更。
  - AUDIT_LOG_ENABLED 關閉時直接拒絕；AUDIT_LOG_PAUSED 是業主明確要求的暫停記錄開關。
  - 暫停只略過 Audit Log，業務寫入與 Entity Snapshot 照常；重新啟用不補寫暫停期間的事件。
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from .models import AuditLog, EntitySnapshot

SYSTEM_ACTOR = {"id": "system", "name": "System", "role": "system"}
CLI_ACTOR = {"id": "cli", "name": "CLI", "role": "system"}


def _guard():
    if not settings.AUDIT_LOG_ENABLED:
        raise ImproperlyConfigured("AUDIT_LOG_ENABLED must be true; writes without an audit trail are refused.")
    if not connection.in_atomic_block:
        raise RuntimeError("Audit writes must happen inside transaction.atomic() together with the change they record.")


def audit_recording_enabled():
    return settings.AUDIT_LOG_ENABLED and not settings.AUDIT_LOG_PAUSED


def request_id_from(request):
    """對應 Alpha 的 x-request-id（由 Nginx 產生並轉發）。"""
    value = request.headers.get("X-Request-ID") if request is not None else None
    return str(value)[:200] if value else None


def record_audit(*, entity_type, entity_id, action, actor, before=None, after=None,
                 request_id=None, source="application", metadata=None):
    _guard()
    if settings.AUDIT_LOG_PAUSED:
        return None
    if before is None and after is None:
        raise ValueError("An audit event needs before or after data.")
    actor = actor or SYSTEM_ACTOR
    return AuditLog.objects.create(
        entity_type=str(entity_type),
        entity_id=str(entity_id),
        action=str(action),
        before_data=before,
        after_data=after,
        actor_id=str(actor.get("id") or "system"),
        actor_name=str(actor.get("name") or "System"),
        actor_role=str(actor.get("role") or "system"),
        request_id=request_id,
        source=str(source or "application"),
        metadata=metadata or {},
    )


def record_snapshot(*, entity_type, entity_id, version, reason, data, created_by):
    _guard()
    return EntitySnapshot.objects.create(
        entity_type=str(entity_type),
        entity_id=str(entity_id),
        entity_version=int(version),
        snapshot_reason=str(reason),
        snapshot_data=data,
        created_by=str(created_by),
    )


DRAFT_SNAPSHOT_REASON = "draft_updated"


def record_draft_snapshot(*, entity_id, version, data, created_by):
    """未 Announce 的草稿只保留一份最新副本（業主決定 2026-11-13：草稿不受 20 年保存限制）。

    每次草稿儲存（含自動儲存）覆蓋該案件最新的一筆 draft_updated 副本；還沒有就新增。
    這是 append-only 規則唯一的例外，三層防護同步放寬到最小範圍：
      1. 應用層：只有這個函式會更新，且只更新 entity_type='case'、reason='draft_updated' 的那一筆。
      2. 資料庫 trigger：只允許「案件目前仍是 Draft」的 draft_updated 副本被更新（scripts/db_harden.sh）；
         案件 Announce 之後，它的所有副本（含草稿時期的）恢復不可修改。DELETE 仍一律禁止。
      3. 資料庫權限：ri_runtime 對 ri_entity_snapshots 增加 UPDATE，沒有 DELETE。
    2026-11-13 之前累積的舊草稿副本不刪除，只覆蓋最新的一筆。
    """
    _guard()
    from django.db.models import QuerySet
    from django.utils import timezone
    rows = QuerySet(EntitySnapshot).filter(entity_type="case", entity_id=str(entity_id), snapshot_reason=DRAFT_SNAPSHOT_REASON)
    latest = rows.order_by("-entity_version", "-pk").values_list("pk", flat=True).first()
    if latest is None:
        return record_snapshot(entity_type="case", entity_id=entity_id, version=version, reason=DRAFT_SNAPSHOT_REASON,
                               data=data, created_by=created_by)
    rows.filter(pk=latest).update(entity_version=int(version), snapshot_data=data, created_by=str(created_by),
                                  created_at=timezone.now())
    return EntitySnapshot.objects.get(pk=latest)
