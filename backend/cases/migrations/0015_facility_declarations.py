import django.core.serializers.json
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('cases', '0014_review_cancelled_members')]
    operations = [
        migrations.CreateModel(
            name='FacilityDeclaration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('declaration_uid', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('statement_no', models.CharField(max_length=160)),
                ('period_from', models.DateField()),
                ('period_to', models.DateField()),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('posted', 'Announced')], default='draft', max_length=16)),
                ('payload', models.JSONField(default=dict, encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ('row_version', models.PositiveBigIntegerField(default=1)),
                ('created_by', models.CharField(max_length=120)),
                ('updated_by', models.CharField(max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('announced_at', models.DateTimeField(blank=True, null=True)),
                ('announced_by', models.CharField(blank=True, max_length=120)),
                ('facility', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='facility_declarations', to='cases.case')),
            ],
            options={'db_table': 'ri_facility_declarations',
                     'indexes': [models.Index(fields=['facility', 'period_from', 'period_to'], name='facility_declaration_dates_idx')],
                     'constraints': [
                         models.UniqueConstraint(fields=('facility', 'statement_no'), name='facility_statement_unique'),
                         models.CheckConstraint(condition=models.Q(('period_to__gte', models.F('period_from'))), name='facility_declaration_period_valid'),
                         models.CheckConstraint(condition=models.Q(('row_version__gt', 0)), name='facility_declaration_version_valid'),
                         models.CheckConstraint(condition=models.Q(('status__in', ['draft', 'posted'])), name='facility_declaration_status_valid'),
                     ]},
        ),
    ]
