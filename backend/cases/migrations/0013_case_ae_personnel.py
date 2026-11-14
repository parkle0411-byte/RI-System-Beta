from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('cases', '0012_oversea_broker_notes'), ('personnel', '0005_remove_personnel_ri_personnel_role_check_and_more')]
    operations = [
        migrations.AddField(
            model_name='case', name='ae_personnel',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='personnel.personnel'),
        ),
    ]
