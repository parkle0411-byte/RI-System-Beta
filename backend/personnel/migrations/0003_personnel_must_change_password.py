from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("personnel", "0002_alter_personnel_name_alter_personnel_supervisor_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="personnel",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
    ]
