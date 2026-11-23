import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('cases', '0016_facility_structure')]
    operations = [migrations.CreateModel(
        name='FacilityDeclarationDocument',
        fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('filename', models.CharField(max_length=255)),
            ('content_type', models.CharField(max_length=255)),
            ('byte_size', models.PositiveIntegerField()),
            ('sha256', models.CharField(max_length=64)),
            ('storage_key', models.CharField(max_length=255, unique=True)),
            ('uploaded_by', models.CharField(max_length=120)),
            ('uploaded_at', models.DateTimeField(default=django.utils.timezone.now)),
            ('declaration', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documents', to='cases.facilitydeclaration')),
        ],
        options={'db_table': 'ri_facility_declaration_documents', 'constraints': [
            models.CheckConstraint(condition=models.Q(('byte_size__gt', 0), ('byte_size__lte', 31457280)), name='facility_decl_document_size')
        ]},
    )]
