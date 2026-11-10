from django.db import migrations,models

REASONS=[('late_entry','Historical endorsement entry'),('premium_adjustment','Premium settlement / retrospective adjustment'),
         ('refund_entry','Refund / cancellation endorsement entry'),('other','Other')]

def seed(apps,schema_editor):
    reason=apps.get_model('legacy','LegacyReason')
    for order,(code,label) in enumerate(REASONS):
        reason.objects.get_or_create(code=code,defaults={'label':label,'sort_order':order})

class Migration(migrations.Migration):
    dependencies=[('legacy','0001_initial')]
    operations=[
        migrations.CreateModel(name='NumberCounter',fields=[('year',models.PositiveIntegerField(primary_key=True,serialize=False)),('value',models.PositiveBigIntegerField(default=0))],options={'db_table':'ri_legacy_number_counters'}),
        migrations.CreateModel(name='LegacyReason',fields=[('code',models.CharField(max_length=40,primary_key=True,serialize=False)),('label',models.CharField(max_length=200)),('active',models.BooleanField(default=True)),('sort_order',models.PositiveIntegerField(default=0))],options={'db_table':'ri_legacy_reasons'}),
        migrations.RunPython(seed,migrations.RunPython.noop),
    ]
