from django.db import models


class MasterRecord(models.Model):
    """
    對應 Hatchable Alpha 的 ri_master_records 表。
    共用表，entity_type 區分六種主檔類型：
    ae / reinsurer / reinsured / class / foreign_broker / clause
    """

    ENTITY_TYPE_CHOICES = [
        ("ae", "AE"),
        ("reinsurer", "Reinsurer"),
        ("reinsured", "Reinsured"),
        ("class", "Class"),
        ("foreign_broker", "Foreign RI Broker"),
        ("clause", "Clause"),
    ]

    entity_type = models.CharField(max_length=40, choices=ENTITY_TYPE_CHOICES)
    code = models.CharField(max_length=80, null=True, blank=True)
    name = models.CharField(max_length=240)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    payload = models.JSONField(default=dict, blank=True)
    row_version = models.BigIntegerField(default=1)

    # TODO: VM 尚未接上登入系統，created_by / updated_by 先由 view 端填入固定值
    # （對應 Alpha 的 actor.id），登入機制完成後改為實際使用者。
    created_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.CharField(max_length=120)
    updated_at = models.DateTimeField(auto_now=True)

    deactivated_by = models.CharField(max_length=120, null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ri_master_records"
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "code"],
                name="ri_master_records_type_code_unique",
            ),
            # 對應 Alpha migration 0033（#18）：資料庫層是重複名稱的最終防線。
            # MySQL utf8mb4_0900_ai_ci 本身不分大小寫（也不分重音），效果等同 Alpha 的 lower(name)。
            models.UniqueConstraint(
                fields=["entity_type", "name"],
                name="ri_master_records_type_name_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["entity_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.entity_type}:{self.name}"
