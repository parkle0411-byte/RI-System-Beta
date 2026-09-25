import django.core.serializers.json
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Draft 回收桶（對應 Alpha 0005、0019、0032）。"""

    dependencies = [
        ("cases", "0002_case_document_limit_10mb"),
    ]

    operations = [
        migrations.CreateModel(
            name="DraftRecycleBin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("original_case_version", models.BigIntegerField()),
                ("case_snapshot", models.JSONField(encoder=django.core.serializers.json.DjangoJSONEncoder)),
                ("deleted_by", models.CharField(max_length=120)),
                ("deleted_at", models.DateTimeField()),
                ("restore_deadline", models.DateTimeField()),
                ("restored_by", models.CharField(blank=True, max_length=120, null=True)),
                ("restored_at", models.DateTimeField(blank=True, null=True)),
                ("permanently_deleted_by", models.CharField(blank=True, max_length=120, null=True)),
                ("permanently_deleted_at", models.DateTimeField(blank=True, null=True)),
                ("original_case", models.ForeignKey(db_column="original_case_id", on_delete=django.db.models.deletion.PROTECT,
                                                    related_name="recycle_entries", to="cases.case")),
            ],
            options={
                "db_table": "ri_draft_recycle_bin",
                "indexes": [models.Index(fields=["-deleted_at"], name="ri_draft_recycle_bin_pending")],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("original_case_version__gt", 0)), name="ri_draft_recycle_bin_version_check"),
                    models.CheckConstraint(condition=models.Q(models.Q(("restored_at__isnull", True), ("restored_by__isnull", True)),
                                                              models.Q(("restored_at__isnull", False), ("restored_by__isnull", False)), _connector="OR"),
                                           name="ri_draft_recycle_bin_restore_actor"),
                    models.CheckConstraint(condition=models.Q(("permanently_deleted_at__isnull", True), ("permanently_deleted_by__isnull", True)),
                                           name="ri_draft_recycle_bin_no_permanent_delete"),
                ],
            },
        ),
    ]
