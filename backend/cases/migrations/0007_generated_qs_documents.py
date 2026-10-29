from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cases", "0006_insured_master")]
    operations = [
        migrations.RemoveConstraint(model_name="casedocument", name="ri_case_documents_kind_check"),
        migrations.AlterField(
            model_name="casedocument", name="kind",
            field=models.CharField(max_length=20, choices=[
                ("offer", "Offer"), ("signed", "Signed"), ("confirmation", "Confirmation"),
                ("generated_cover", "Generated Cover Note"), ("generated_debit", "Generated Debit Note"),
            ]),
        ),
        migrations.AddConstraint(
            model_name="casedocument",
            constraint=models.CheckConstraint(
                condition=models.Q(kind__in=["offer", "signed", "confirmation", "generated_cover", "generated_debit"]),
                name="ri_case_documents_kind_check"),
        ),
    ]
