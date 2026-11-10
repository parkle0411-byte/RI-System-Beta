from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('cases', '0009_remove_treaty_structure')]
    operations = [migrations.CreateModel(
        name='FinanceReconciliationBatch',
        fields=[('id', models.UUIDField(primary_key=True, editable=False, serialize=False)),
            ('status', models.CharField(max_length=12, default='active')),
            ('review_date', models.DateField()), ('currency', models.CharField(max_length=3)),
            ('party_name', models.CharField(max_length=500)),
            ('reference', models.CharField(max_length=200, blank=True)),
            ('note', models.CharField(max_length=1000, blank=True)),
            ('members', models.JSONField(default=list)), ('created_at', models.DateTimeField(auto_now_add=True)),
            ('created_by', models.CharField(max_length=120)), ('created_by_name', models.CharField(max_length=240)),
            ('cancelled_at', models.DateTimeField(null=True)), ('cancelled_by', models.CharField(max_length=120, blank=True)),
            ('cancelled_by_name', models.CharField(max_length=240, blank=True)), ('cancel_reason', models.CharField(max_length=1000, blank=True))],
        options={'db_table': 'ri_finance_reconciliation_batches', 'constraints': [models.CheckConstraint(condition=models.Q(status__in=['active','cancelled']), name='finance_review_status_valid')]})]
