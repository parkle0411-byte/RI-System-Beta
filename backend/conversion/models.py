"""
資料轉換的批次紀錄 - 對應 Alpha migrations/0018_create_data_migration_controls.sql。

每次執行匯入（含 dry-run）都有一筆 batch；每一筆來源資料都有一筆 item，記錄 Alpha 的 ID（source_key）、
VM 的 ID（target_key）、內容雜湊與狀態。VM 還沒有的資料表（提醒信紀錄）也以 item 保存原始內容，之後依對照表匯入。
ri_runtime 對 items 只有 SELECT／INSERT（見 scripts/db_harden.sh）。
"""
import uuid

from django.db import models
from django.db.models import Q

BATCH_STATUSES = ("dry_run", "approved", "completed", "failed")
ITEM_STATUSES = ("validated", "converted", "reconciled", "excluded", "error")


class MigrationBatch(models.Model):
    batch_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source_system = models.CharField(max_length=120)
    source_version = models.CharField(max_length=120, null=True, blank=True)
    source_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    source_counts = models.JSONField(default=dict)
    target_counts = models.JSONField(default=dict)
    control_totals = models.JSONField(default=dict)
    errors = models.JSONField(default=list)
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.CharField(max_length=255, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ri_data_migration_batches"
        constraints = [models.CheckConstraint(condition=Q(status__in=BATCH_STATUSES), name="ri_data_migration_batches_status")]


class MigrationItem(models.Model):
    batch = models.ForeignKey(MigrationBatch, on_delete=models.PROTECT, related_name="items")
    entity_type = models.CharField(max_length=80)
    source_key = models.CharField(max_length=160)
    target_table = models.CharField(max_length=80, null=True, blank=True)
    target_key = models.CharField(max_length=160, null=True, blank=True)
    source_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16)
    issue = models.TextField(null=True, blank=True)
    source_summary = models.JSONField(default=dict)
    target_summary = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ri_data_migration_items"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ITEM_STATUSES), name="ri_data_migration_items_status"),
            models.UniqueConstraint(fields=["batch", "entity_type", "source_key"], name="ri_data_migration_items_unique"),
        ]
        indexes = [models.Index(fields=["batch", "status", "entity_type"], name="ri_dm_items_status_idx")]
