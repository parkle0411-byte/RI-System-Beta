from django.db import models
from django.db.models import Q

DEPARTMENT_CHOICES = [
    ("business_1", "Business 1"),
    ("business_2", "Business 2"),
    ("special_risk", "Special Risk"),
    ("reinsurance", "Reinsurance"),
    ("finance", "Finance"),
    ("admin", "Admin"),
    ("business_development", "Business Development"),
]

ROLE_CODE_CHOICES = [
    ("sales", "Sales"),
    ("accounting", "Accounting"),
    ("accounting_manager", "Accounting Manager"),
    ("general_manager", "General Manager"),
    ("admin", "Admin"),
    ("viewer", "Viewer"),
]

ACCOUNT_STATUS_CHOICES = [
    ("not_configured", "Not configured"),
    ("pending", "Pending"),
    ("active", "Active"),
    ("disabled", "Disabled"),
]


class Personnel(models.Model):
    """
    對應 Hatchable Alpha 的 ri_personnel 表。

    RI 登入尚未在 VM 啟用：email、account_*、auth_user_id 欄位先保留但不填值
    （見 MIGRATION-VM-NOTES 的登入決策），待 Django 帳號機制完成後再接上。
    """

    name = models.CharField(max_length=160)  # Alpha 的 cleanText(name, 160)
    email = models.CharField(max_length=254, null=True, blank=True)
    department = models.CharField(max_length=40, choices=DEPARTMENT_CHOICES)
    role_code = models.CharField(max_length=40, choices=ROLE_CODE_CHOICES)
    is_active = models.BooleanField(default=True)
    is_split_eligible = models.BooleanField(default=True)
    account_status = models.CharField(
        max_length=20, choices=ACCOUNT_STATUS_CHOICES, default="not_configured"
    )
    supervisor_name = models.CharField(max_length=160, null=True, blank=True)
    supervisor_email = models.CharField(max_length=254, null=True, blank=True)
    row_version = models.BigIntegerField(default=1)

    created_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.CharField(max_length=120)
    updated_at = models.DateTimeField(auto_now=True)

    deactivated_by = models.CharField(max_length=120, null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    auth_user_id = models.CharField(max_length=120, null=True, blank=True, unique=True)
    account_invited_by = models.CharField(max_length=120, null=True, blank=True)
    account_invited_at = models.DateTimeField(null=True, blank=True)
    account_activated_at = models.DateTimeField(null=True, blank=True)
    account_disabled_by = models.CharField(max_length=120, null=True, blank=True)
    account_disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ri_personnel"
        constraints = [
            # Alpha 以 lower(name) 判斷唯一；MySQL utf8mb4_0900_ai_ci 本身不分大小寫。
            models.UniqueConstraint(
                fields=["name", "department"], name="ri_personnel_name_department_unique"
            ),
            # email 為 NULL 時 MySQL 的 UNIQUE 允許重複，等同 Alpha 的 partial index。
            models.UniqueConstraint(fields=["email"], name="ri_personnel_email_unique"),
            models.CheckConstraint(
                condition=Q(department__in=[c for c, _ in DEPARTMENT_CHOICES]),
                name="ri_personnel_department_check",
            ),
            models.CheckConstraint(
                condition=Q(role_code__in=[c for c, _ in ROLE_CODE_CHOICES]),
                name="ri_personnel_role_check",
            ),
            models.CheckConstraint(
                condition=Q(account_status__in=[c for c, _ in ACCOUNT_STATUS_CHOICES]),
                name="ri_personnel_account_status_check",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, deactivated_by__isnull=True, deactivated_at__isnull=True)
                    | Q(is_active=False, deactivated_by__isnull=False, deactivated_at__isnull=False)
                ),
                name="ri_personnel_lifecycle_check",
            ),
        ]
        indexes = [
            models.Index(fields=["is_active", "is_split_eligible"], name="ri_personnel_active_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.department})"
