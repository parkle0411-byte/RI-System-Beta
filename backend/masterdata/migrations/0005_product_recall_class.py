"""Register the owner-approved Product Recall insurance type without overwriting data."""
from django.db import migrations
from django.conf import settings
from django.utils import timezone


def seed_product_recall(apps, schema_editor):
    MasterRecord = apps.get_model('masterdata', 'MasterRecord')
    AuditLog = apps.get_model('audit', 'AuditLog')
    EntitySnapshot = apps.get_model('audit', 'EntitySnapshot')
    db = schema_editor.connection.alias
    records = MasterRecord.objects.using(db).filter(entity_type='class')
    named = records.filter(name__iexact='Product Recall').first()
    coded = records.filter(code__iexact='PR').first()
    if named:
        if not named.is_active or str(named.code or '').upper() != 'PR' or coded and coded.pk != named.pk:
            raise RuntimeError('Product Recall class conflicts with an existing class name or PR code. Review the master data before migration.')
        return
    actor = 'system:product-recall-class'
    before = None
    if coded:
        Case = apps.get_model('cases', 'Case')
        if (str(coded.name or '').casefold() != 'products recall' or not coded.is_active
                or Case.objects.using(db).filter(class_master_id=coded.pk).exists()
                or Case.objects.using(db).filter(class_name_snapshot__iexact='Products Recall').exists()
                or Case.objects.using(db).filter(payload__classOfBusiness__iexact='Products Recall').exists()):
            raise RuntimeError('The PR class code is already assigned or referenced. Review the master data before migration.')
        before = {'id':coded.pk, 'entityType':'class', 'name':coded.name, 'code':coded.code, 'isActive':coded.is_active, 'payload':coded.payload}
        coded.name = 'Product Recall'
        coded.row_version += 1
        coded.updated_by = actor
        coded.save(using=db, update_fields=['name', 'row_version', 'updated_by', 'updated_at'])
        row = coded
    else:
        row = records.create(entity_type='class', name='Product Recall', code='PR', is_active=True, payload={}, created_by=actor, updated_by=actor)
    now = timezone.now()
    try:
        retention = now.replace(year=now.year + 20)
    except ValueError:
        retention = now.replace(year=now.year + 20, month=3, day=1)
    state = {'id':row.pk, 'entityType':'class', 'name':row.name, 'code':row.code, 'isActive':True, 'payload':row.payload}
    if not settings.AUDIT_LOG_PAUSED:
        AuditLog.objects.using(db).create(entity_type='master_record', entity_id=str(row.pk), action='update_master' if before else 'create_master',
            before_data=before, after_data=state, actor_id=actor, actor_name='Product Recall migration', actor_role='system',
            source='migration', occurred_at=now, retention_until=retention, metadata={'insuranceType':'Product Recall'})
    EntitySnapshot.objects.using(db).create(entity_type='master_record', entity_id=str(row.pk), entity_version=row.row_version,
        snapshot_reason='master_updated' if before else 'master_created', snapshot_data=state, created_by=actor)


class Migration(migrations.Migration):
    dependencies = [('masterdata', '0004_insured_type'), ('audit', '0001_initial'), ('cases', '0001_initial')]
    operations = [migrations.RunPython(seed_product_recall, migrations.RunPython.noop)]
