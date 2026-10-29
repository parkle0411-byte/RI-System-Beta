from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("cases", "0004_auw_primary_reference_length")]
    operations = [
        migrations.RemoveConstraint(model_name="casedocument", name="ri_case_documents_byte_size_check"),
        migrations.AddConstraint(model_name="casedocument",constraint=models.CheckConstraint(condition=models.Q(byte_size__gt=0,byte_size__lte=31457280),name="ri_case_documents_byte_size_check")),
    ]
