from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("reminders", "0001_initial")]
    operations = [
        migrations.RemoveConstraint(model_name="signedslipalert",name="ri_signed_slip_alerts_days_check"),
        migrations.AddConstraint(model_name="signedslipalert",constraint=models.CheckConstraint(condition=models.Q(days_since_effective__gte=30),name="ri_signed_slip_alerts_days_check")),
    ]
