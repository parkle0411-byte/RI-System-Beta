"""
提醒信紀錄 - 對應 Alpha migrations/0017_create_signed_slip_alerts.sql、0029_create_payment_alerts.sql、0030_index_payment_alerts.sql。

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - status 多一個 suppressed：VM 尚未啟用寄信時記成 suppressed（算「已提醒」，與 sent、simulated 相同；2026-09-26 你的決定）。
    Alpha 的 ri_payment_alerts.status 沒有 CHECK；VM 兩張表都加上同樣的 CHECK。
  - 多存信件的主旨與內文（subject、body_html、body_text），產生當下存下，案件明細的 Reminders 分頁顯示（2026-09-26 你的決定）。
  - 0031（補 payload.paymentScheduleReviewRequired）不需要：VM 的 normalize_draft 本來就會設定，切換匯入的是 Alpha 已補過的資料。
ri_runtime 沒有 DELETE（預設規則）：提醒紀錄只會新增與更新狀態。
"""
import uuid

from django.db import models
from django.db.models import Q

STATUSES = ("pending", "sent", "simulated", "suppressed", "failed")
SUCCESS_STATUSES = ("sent", "simulated", "suppressed")   # 算「已提醒」


class SignedSlipAlert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, db_column="case_id", related_name="signed_slip_alerts")
    alert_on = models.DateField()
    policy_from = models.DateField()
    days_since_effective = models.IntegerField()
    missing_reinsurers = models.JSONField(default=list)
    recipients = models.JSONField(default=list)
    status = models.CharField(max_length=20)
    message_id = models.TextField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    subject = models.TextField(null=True, blank=True)
    body_html = models.TextField(null=True, blank=True)
    body_text = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ri_signed_slip_alerts"
        constraints = [
            models.CheckConstraint(condition=Q(days_since_effective__gte=60), name="ri_signed_slip_alerts_days_check"),
            models.CheckConstraint(condition=Q(status__in=STATUSES), name="ri_signed_slip_alerts_status_check"),
            models.UniqueConstraint(fields=["case", "alert_on"], name="ri_signed_slip_alerts_case_date_unique"),
        ]
        indexes = [models.Index(fields=["case", "-alert_on"], name="ri_signed_slip_alerts_case_idx")]


class PaymentAlert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, db_column="case_id", related_name="payment_alerts")
    alert_date = models.DateField()
    alert_kind = models.CharField(max_length=40)
    schedule_keys = models.JSONField(default=list)
    recipients = models.JSONField(default=list)
    status = models.CharField(max_length=20, default="pending")
    error_message = models.TextField(null=True, blank=True)
    subject = models.TextField(null=True, blank=True)
    body_html = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ri_payment_alerts"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=STATUSES), name="ri_payment_alerts_status_check"),
            models.UniqueConstraint(fields=["case", "alert_date", "alert_kind"], name="ri_payment_alerts_case_date_kind_unique"),
        ]
        indexes = [models.Index(fields=["case", "-alert_date"], name="ri_payment_alerts_case_idx")]
