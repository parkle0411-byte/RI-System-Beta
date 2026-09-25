from django.db import migrations, models


class Migration(migrations.Migration):
    """案件文件單檔上限 5 MB → 10 MB（2026-09-25 的決定；Alpha 仍是 5 MB）。"""

    dependencies = [
        ("cases", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="casedocument",
            name="ri_case_documents_byte_size_check",
        ),
        migrations.AddConstraint(
            model_name="casedocument",
            constraint=models.CheckConstraint(
                condition=models.Q(("byte_size__gt", 0), ("byte_size__lte", 10485760)),
                name="ri_case_documents_byte_size_check",
            ),
        ),
    ]
