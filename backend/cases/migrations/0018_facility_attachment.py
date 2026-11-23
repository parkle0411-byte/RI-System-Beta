from django.db import migrations, models

KINDS = [('offer', 'Offer'), ('signed', 'Signed'), ('confirmation', 'Confirmation'),
         ('broker_credit', 'RI Broker Credit Note'), ('broker_debit', 'RI Broker Debit Note'),
         ('generated_cover', 'Generated Cover Note'), ('generated_debit', 'Generated Debit Note'),
         ('facility_attachment', 'Facility attachment')]

class Migration(migrations.Migration):
    dependencies = [('cases', '0017_facility_declaration_documents')]
    operations = [
        migrations.RemoveConstraint(model_name='casedocument', name='ri_case_documents_kind_check'),
        migrations.AlterField(model_name='casedocument', name='kind', field=models.CharField(max_length=20, choices=KINDS)),
        migrations.AddConstraint(model_name='casedocument', constraint=models.CheckConstraint(
            condition=models.Q(kind__in=[key for key, _ in KINDS]), name='ri_case_documents_kind_check')),
    ]
