"""
寫入 Audit Log 與 Snapshot 的共用入口（對應 Alpha 的 lib/audit.js）。

規則：
  - 必須在交易（transaction.atomic）內呼叫，讓「業務資料的變更」與「它的稽核紀錄」同生同滅：
    稽核寫入失敗，整筆業務變更一起回滾，不會出現沒有紀錄的變更。
  - AUDIT_LOG_ENABLED 關閉時直接拒絕，而不是默默略過（Alpha 的「暫停」只是測試階段，VM 不沿用）。
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


def request_id_from(request):
    """對應 Alpha 的 x-request-id（由 Nginx 產生並轉發）。"""
    value = request.headers.get("X-Request-ID") if request is not None else None
    return str(value)[:200] if value else None


def record_audit(*, entity_type, entity_id, action, actor, before=None, after=None,
                 request_id=None, source="application", metadata=None):
    _guard()
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
