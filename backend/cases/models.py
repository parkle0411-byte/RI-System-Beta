import uuid

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

CASE_KIND_CHOICES = [
    ("original", "Original"),
    ("endorsement", "Endorsement"),
    ("renewal", "Renewal"),
]

CASE_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("posted", "Posted"),
    ("closed", "Closed"),
    ("reversed", "Reversed"),
    ("archived", "Archived"),
]

REINSURANCE_STRUCTURE_CHOICES = [
    ("FACULTATIVE", "Facultative"),
    ("QS", "Quota Share"),
    ("XOL", "Excess of Loss"),
    ("TREATY", "Treaty"),
]

DOCUMENT_KIND_CHOICES = [
    ("offer", "Offer"),
    ("signed", "Signed"),
    ("confirmation", "Confirmation"),
]

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024


class Case(models.Model):
    """
    對應 Hatchable Alpha 的 ri_cases 表。

    業務欄位大多存在 payload（JSON）；主檔以 FK + snapshot 名稱欄位並存，
    讓主檔日後改名時舊案件仍保留當時的名稱。
    """

    case_uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    legacy_case_id = models.BigIntegerField(null=True, blank=True, unique=True)
    parent_case = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="child_cases",
    )
    tw_ref = models.CharField(max_length=64, null=True, blank=True, unique=True)
    case_kind = models.CharField(
        max_length=20, choices=CASE_KIND_CHOICES, default="original"
    )
    status = models.CharField(max_length=20, choices=CASE_STATUS_CHOICES, default="draft")
    reinsurance_structure = models.CharField(
        max_length=20, choices=REINSURANCE_STRUCTURE_CHOICES, null=True, blank=True
    )

    class_master = models.ForeignKey(
        "masterdata.MasterRecord",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    class_code_snapshot = models.CharField(max_length=80, null=True, blank=True)
    class_name_snapshot = models.CharField(max_length=240, null=True, blank=True)
    reinsured_master = models.ForeignKey(
        "masterdata.MasterRecord",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    reinsured_name_snapshot = models.CharField(max_length=240, null=True, blank=True)
    ae_master = models.ForeignKey(
        "masterdata.MasterRecord",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    ae_name_snapshot = models.CharField(max_length=240, null=True, blank=True)
    owner_personnel = models.ForeignKey(
        "personnel.Personnel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )

    currency = models.CharField(max_length=3, null=True, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    row_version = models.BigIntegerField(default=1)

    is_archived = models.BooleanField(default=False)
    archived_by = models.CharField(max_length=120, null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    recycled_by = models.CharField(max_length=120, null=True, blank=True)
    recycled_at = models.DateTimeField(null=True, blank=True)

    announced_by = models.CharField(max_length=120, null=True, blank=True)
    announced_at = models.DateTimeField(null=True, blank=True)

    # TODO: VM 尚未接上登入系統，created_by / updated_by 先由 view 端填入固定值
    # （對應 Alpha 的 actor.id），登入機制完成後改為實際使用者。
    created_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.CharField(max_length=120)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ri_cases"
        constraints = [
            models.CheckConstraint(
                condition=Q(case_kind__in=[c for c, _ in CASE_KIND_CHOICES]),
                name="ri_cases_case_kind_check",
            ),
            models.CheckConstraint(
                condition=Q(status__in=[c for c, _ in CASE_STATUS_CHOICES]),
                name="ri_cases_status_check",
            ),
            models.CheckConstraint(
                condition=(
                    Q(reinsurance_structure__isnull=True)
                    | Q(reinsurance_structure__in=[c for c, _ in REINSURANCE_STRUCTURE_CHOICES])
                ),
                name="ri_cases_reinsurance_structure_check",
            ),
            models.CheckConstraint(
                condition=Q(row_version__gt=0),
                name="ri_cases_row_version_check",
            ),
            models.CheckConstraint(
                condition=(
                    Q(effective_date__isnull=True)
                    | Q(expiration_date__isnull=True)
                    | Q(expiration_date__gte=F("effective_date"))
                ),
                name="ri_cases_policy_period_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_archived=False, archived_at__isnull=True, archived_by__isnull=True)
                    | Q(is_archived=True, archived_at__isnull=False, archived_by__isnull=False)
                ),
                name="ri_cases_archive_consistent",
            ),
            models.CheckConstraint(
                condition=Q(recycled_at__isnull=True) | Q(status="draft"),
                name="ri_cases_recycle_draft_only",
            ),
        ]
        indexes = [
            models.Index(fields=["owner_personnel"], name="ri_cases_owner_idx"),
        ]

    def __str__(self):
        return self.tw_ref or f"case:{self.pk}"


class CaseDocument(models.Model):
    """
    對應 Alpha 的 ri_case_documents 表（只有 metadata）。
    檔案本體的存放位置（storage_key 指向哪裡）尚未決定，上傳／下載留待後續步驟。
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        Case, on_delete=models.PROTECT, related_name="documents"
    )
    kind = models.CharField(max_length=20, choices=DOCUMENT_KIND_CHOICES)
    reinsurers = models.JSONField(default=list, blank=True)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    byte_size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=255, unique=True)
    is_selected = models.BooleanField(default=True)
    uploaded_by = models.CharField(max_length=120)
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "ri_case_documents"
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=[c for c, _ in DOCUMENT_KIND_CHOICES]),
                name="ri_case_documents_kind_check",
            ),
            models.CheckConstraint(
                condition=Q(byte_size__gt=0, byte_size__lte=MAX_DOCUMENT_BYTES),
                name="ri_case_documents_byte_size_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["case", "uploaded_at", "id"], name="ri_case_documents_case_id_idx"
            ),
        ]

    def __str__(self):
        return f"{self.kind}:{self.filename}"


class ReferenceSequence(models.Model):
    """對應 Alpha 的 ri_reference_sequences：Announce 時產生 TW Reference 的流水號。"""

    prefix = models.CharField(max_length=64, primary_key=True)
    last_value = models.PositiveIntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ri_reference_sequences"
        constraints = [
            models.CheckConstraint(
                condition=Q(last_value__gt=0),
                name="ri_reference_sequences_last_value_check",
            ),
        ]

    def __str__(self):
        return f"{self.prefix}:{self.last_value}"
