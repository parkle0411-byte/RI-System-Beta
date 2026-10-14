from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="OperationLock",
            fields=[("key", models.CharField(max_length=80, primary_key=True, serialize=False))],
            options={"db_table": "ri_operation_locks"},
        ),
    ]
