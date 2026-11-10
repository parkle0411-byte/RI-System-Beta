"""Standalone business transactions. None of these models creates a Case."""
import uuid
from django.db import models
from django.db.models import Q


class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=255)
    status = models.CharField(max_length=20, default='preview')
    manifest = models.JSONField(default=dict)
    created_by = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)
    imported_at = models.DateTimeField(null=True)
    withdrawn_at = models.DateTimeField(null=True)
    withdrawal = models.JSONField(default=dict)

    class Meta:
        db_table = 'ri_legacy_import_batches'
        constraints = [models.CheckConstraint(condition=Q(status__in=['preview','imported','withdrawn']), name='legacy_batch_status')]


class LegacyTransaction(models.Model):
    uid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=80, null=True, unique=True)
    original_serial = models.CharField(max_length=80, null=True, unique=True)
    reference = models.CharField(max_length=192, db_index=True)
    currency = models.CharField(max_length=3, default='TWD')
    revenue_month = models.CharField(max_length=7, blank=True, db_index=True)
    status = models.CharField(max_length=20, default='draft', db_index=True)
    operation = models.CharField(max_length=24, default='normal')
    historical = models.BooleanField(default=False)
    batch = models.ForeignKey(ImportBatch, null=True, on_delete=models.PROTECT, related_name='transactions')
    reference_transaction = models.ForeignKey('self', null=True, on_delete=models.PROTECT, related_name='referenced_by')
    corrects = models.ForeignKey('self', null=True, on_delete=models.PROTECT, related_name='corrections')
    correction_group = models.UUIDField(null=True, db_index=True)
    owner_id = models.BigIntegerField(null=True)
    created_by_id = models.BigIntegerField(null=True)
    data = models.JSONField(default=dict)
    original = models.JSONField(default=dict)
    financial = models.JSONField(default=dict)
    fx_snapshot = models.JSONField(default=dict)
    version = models.PositiveBigIntegerField(default=1)
    first_confirmed_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ri_legacy_transactions'
        constraints = [models.CheckConstraint(condition=Q(status__in=['draft','confirmed','withdrawn','cancelled']), name='legacy_transaction_status'),
                       models.CheckConstraint(condition=Q(version__gt=0), name='legacy_transaction_version')]


class NumberCounter(models.Model):
    year = models.PositiveIntegerField(primary_key=True)
    value = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = 'ri_legacy_number_counters'


class LegacyReason(models.Model):
    code = models.CharField(max_length=40, primary_key=True)
    label = models.CharField(max_length=200)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'ri_legacy_reasons'


class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValueError('Legacy audit records are permanent and append-only.')

    def delete(self):
        raise ValueError('Legacy audit records are permanent and append-only.')


class LegacyAudit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.CharField(max_length=100, db_index=True)
    action = models.CharField(max_length=80)
    actor_id = models.BigIntegerField(null=True)
    actor_name = models.CharField(max_length=160)
    reason = models.TextField(blank=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableQuerySet.as_manager()

    class Meta:
        db_table = 'ri_legacy_audit'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError('Legacy audit records are permanent and append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('Legacy audit records are permanent and append-only.')
