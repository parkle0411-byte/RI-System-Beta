from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cases", "0003_draftrecyclebin")]
    operations = [
        migrations.AlterField(model_name="case", name="tw_ref", field=models.CharField(blank=True, max_length=192, null=True, unique=True)),
        migrations.AlterField(model_name="referencesequence", name="prefix", field=models.CharField(max_length=192, primary_key=True, serialize=False)),
    ]
