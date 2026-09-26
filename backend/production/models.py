"""
Production Report 的資料表 - 對應 Alpha migrations/0016_create_production_report_lifecycle.sql。

MySQL 沒有 PostgreSQL 的「部分唯一索引」與 COALESCE 唯一索引，改用函式索引（MySQL 8.0.13+）表達同樣的限制：
  - 每個月最多一份 closed 報表：UNIQUE((CASE WHEN status = 'closed' THEN year_month END))
  - 同一個排除對象只能排除一次：UNIQUE(case_id, year_month, scope, installment_key, COALESCE(reinsurer_key, ''))
排除紀錄只新增、不修改也不刪除（ri_runtime 只有 SELECT／INSERT，見 scripts/db_harden.sh）。
"""
import uuid

from django.db import models
from django.db.models import Case as SqlCase, F, Q, Value, When
from django.db.models.functions import Coalesce

MONTH_REGEX = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
REPORT_STATUSES = ("valid", "invalid", "closed", "failed")


class ProductionReport(models.Model):
    report_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    year_month = models.CharField(max_length=7)
    version = models.IntegerField()
    status = models.CharField(max_length=16, default="valid", choices=[(s, s) for s in REPORT_STATUSES])
    rows = models.JSONField(default=list)
    excluded_rows = models.JSONField(default=list)
    source_signature = models.TextField()
    row_version = models.BigIntegerField(default=1)
    close_token = models.UUIDField(null=True, blank=True)
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    closed_by = models.CharField(max_length=255, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ri_production_reports"
        constraints = [
            models.CheckConstraint(condition=Q(year_month__regex=MONTH_REGEX), name="ri_production_reports_month_format"),
            models.CheckConstraint(condition=Q(version__gt=0), name="ri_production_reports_version_positive"),
            models.CheckConstraint(condition=Q(status__in=REPORT_STATUSES), name="ri_production_reports_status_check"),
            models.UniqueConstraint(fields=["year_month", "version"], name="ri_production_reports_month_version_unique"),
            models.CheckConstraint(
                condition=(Q(status="closed", closed_by__isnull=False, closed_at__isnull=False, close_token__isnull=False)
                           | (~Q(status="closed") & Q(closed_by__isnull=True, closed_at__isnull=True, close_token__isnull=True))),
                name="ri_production_reports_close_fields",
            ),
            models.UniqueConstraint(SqlCase(When(status="closed", then=F("year_month"))),
                                    name="ri_production_reports_one_closed_month"),
        ]
        indexes = [models.Index(fields=["-year_month", "-version"], name="ri_prod_reports_month_ver_idx")]


class ProductionExclusion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, db_column="case_id", related_name="+")
    year_month = models.CharField(max_length=7)
    scope = models.CharField(max_length=16)
    installment_key = models.CharField(max_length=255)
    reinsurer_key = models.CharField(max_length=255, null=True, blank=True)
    deferred_to = models.CharField(max_length=7)
    reason = models.TextField()
    created_by = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ri_production_exclusions"
        constraints = [
            models.CheckConstraint(condition=Q(year_month__regex=MONTH_REGEX), name="ri_production_exclusions_month_format"),
            models.CheckConstraint(condition=Q(deferred_to__regex=MONTH_REGEX), name="ri_production_exclusions_deferred_format"),
            models.CheckConstraint(condition=Q(scope="case", reinsurer_key__isnull=True) | Q(scope="reinsurer", reinsurer_key__isnull=False),
                                   name="ri_production_exclusions_scope_check"),
            models.UniqueConstraint(F("case"), F("year_month"), F("scope"), F("installment_key"), Coalesce(F("reinsurer_key"), Value("")),
                                    name="ri_production_exclusions_target_unique"),
        ]
        indexes = [models.Index(fields=["deferred_to", "case"], name="ri_prod_excl_deferred_idx")]
        ordering = ["created_at", "id"]
