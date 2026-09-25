"""
Audit Log 與 Entity Snapshot（對應 Alpha 的 ri_audit_log / ri_entity_snapshots）。

保存與防護要求（見 MIGRATION-VM-NOTES.md）：
  - Audit Log 至少保存二十年，只能新增（append-only）。
  - Entity Snapshot 是不可變的歷史版本。
防護分三層，任何一層失守都不會單獨造成資料被改寫：
  1. 應用層（本檔）：model 與 QuerySet 拒絕 UPDATE / DELETE。
  2. 資料庫 trigger：BEFORE UPDATE / DELETE 一律拒絕（由 scripts/db_harden.sh 以 root 建立）。
  3. 資料庫權限：網站使用的 ri_runtime 帳號對這兩張表只有 SELECT、INSERT（同一支腳本設定）。
"""
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

RETENTION_YEARS = 20


def add_years(moment, years):
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:  # 2/29 → 沒有閏年的那一年，順延到 3/1（較晚，保存期只會更長）
        return moment.replace(year=moment.year + years, month=3, day=1)


class AppendOnlyError(RuntimeError):
    pass


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError(f"{self.model.__name__} is append-only; update is not allowed.")

    def delete(self):
        raise AppendOnlyError(f"{self.model.__name__} is append-only; delete is not allowed.")

    def bulk_update(self, *args, **kwargs):
        raise AppendOnlyError(f"{self.model.__name__} is append-only; update is not allowed.")


class AppendOnlyModel(models.Model):
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError(f"{type(self).__name__} is append-only; existing rows cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError(f"{type(self).__name__} is append-only; delete is not allowed.")


class AuditLog(AppendOnlyModel):
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=120)
    action = models.CharField(max_length=80)
    before_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    actor_id = models.CharField(max_length=120)
    actor_name = models.CharField(max_length=120, null=True, blank=True)
    actor_role = models.CharField(max_length=40, null=True, blank=True)
    request_id = models.CharField(max_length=200, null=True, blank=True)
    source = models.CharField(max_length=40, default="application")
    occurred_at = models.DateTimeField(default=timezone.now)
    retention_until = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)

    class Meta:
        db_table = "ri_audit_log"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(before_data__isnull=False) | models.Q(after_data__isnull=False),
                name="ri_audit_log_has_change",
            ),
        ]
        indexes = [
            models.Index(fields=["entity_type", "entity_id"], name="ri_audit_entity_idx"),
            models.Index(fields=["occurred_at"], name="ri_audit_occurred_idx"),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and self.retention_until is None:
            self.retention_until = add_years(self.occurred_at, RETENTION_YEARS)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.occurred_at:%Y-%m-%d %H:%M} {self.entity_type}:{self.entity_id} {self.action}"


class EntitySnapshot(AppendOnlyModel):
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=120)
    entity_version = models.BigIntegerField()
    snapshot_reason = models.CharField(max_length=80)
    snapshot_data = models.JSONField(encoder=DjangoJSONEncoder)
    created_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "ri_entity_snapshots"
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "entity_id", "entity_version"],
                name="ri_entity_snapshots_version_unique",
            ),
            models.CheckConstraint(condition=models.Q(entity_version__gt=0), name="ri_entity_snapshots_version_check"),
        ]

    def __str__(self):
        return f"{self.entity_type}:{self.entity_id} v{self.entity_version}"
