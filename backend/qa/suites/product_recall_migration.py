"""Verify safe reuse of the existing PR master and the paused audit policy."""
import importlib, os
from types import SimpleNamespace
from django.apps import apps
from django.db import transaction
from django.test import override_settings
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case
from masterdata.models import MasterRecord

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
seed = importlib.import_module('masterdata.migrations.0005_product_recall_class').seed_product_recall
schema = SimpleNamespace(connection=SimpleNamespace(alias='default'))
checks = []
def check(label, condition):
    checks.append(bool(condition))
    print(('PASS ' if condition else 'FAIL ') + label)

with transaction.atomic():
    master = MasterRecord.objects.get(entity_type='class', code='PR')
    master.name = 'Products Recall'
    master.row_version = 20
    master.save(update_fields=['name', 'row_version'])
    audit_before = AuditLog.objects.filter(entity_type='master_record', entity_id=str(master.pk)).count()
    with override_settings(AUDIT_LOG_PAUSED=True):
        seed(apps, schema)
    master.refresh_from_db()
    check('existing unused PR master is reused and renamed', master.name == 'Product Recall' and master.row_version == 21)
    check('paused audit creates no event but retains a master snapshot',
          AuditLog.objects.filter(entity_type='master_record', entity_id=str(master.pk)).count() == audit_before
          and EntitySnapshot.objects.filter(entity_type='master_record', entity_id=str(master.pk), entity_version=21).exists())
    master.name = 'Products Recall'
    master.save(update_fields=['name'])
    Case.objects.create(class_master=master, created_by='qa', updated_by='qa', payload={})
    try:
        seed(apps, schema)
    except RuntimeError:
        blocked = True
    else:
        blocked = False
    master.refresh_from_db()
    check('referenced PR master is not modified', blocked and master.name == 'Products Recall')
    transaction.set_rollback(True)
print(f'{sum(checks)}/{len(checks)} Product Recall migration checks passed')
