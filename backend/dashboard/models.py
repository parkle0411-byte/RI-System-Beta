"""
業績目標 - 對應 Alpha migrations/0011_create_personnel_accounts.sql 裡的 ri_dashboard_targets（人員表當初已搬，這張表現在才搬）。
目標不實體刪除，只能停用（ri_runtime 沒有 DELETE）。
"""
from django.db import models
from django.db.models import Q


class DashboardTarget(models.Model):
    period_type = models.CharField(max_length=20)
    period_key = models.CharField(max_length=7)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    is_active = models.BooleanField(default=True)
    row_version = models.BigIntegerField(default=1)
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)
    deactivated_by = models.CharField(max_length=255, null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ri_dashboard_targets"
        constraints = [
            models.CheckConstraint(condition=Q(period_type__in=("annual", "monthly")), name="ri_dashboard_targets_type_check"),
            models.CheckConstraint(
                condition=Q(period_type="annual", period_key__regex=r"^[0-9]{4}$")
                | Q(period_type="monthly", period_key__regex=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
                name="ri_dashboard_targets_key_check"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="ri_dashboard_targets_amount_check"),
            models.CheckConstraint(
                condition=Q(is_active=True, deactivated_by__isnull=True, deactivated_at__isnull=True)
                | Q(is_active=False, deactivated_by__isnull=False, deactivated_at__isnull=False),
                name="ri_dashboard_targets_lifecycle_check"),
            models.UniqueConstraint(fields=["period_type", "period_key"], name="ri_dashboard_targets_period_unique"),
        ]
        indexes = [models.Index(fields=["-period_key", "period_type"], name="ri_dash_targets_period_idx")]
