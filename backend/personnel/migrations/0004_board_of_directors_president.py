from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("personnel", "0003_personnel_must_change_password")]

    operations = [
        migrations.RemoveConstraint(model_name="personnel", name="ri_personnel_department_check"),
        migrations.RemoveConstraint(model_name="personnel", name="ri_personnel_role_check"),
        migrations.AlterField(model_name="personnel", name="department",
                              field=models.CharField(max_length=40, choices=[('board_of_directors', 'Board of Directors'), ('business_1', 'Business 1'), ('business_2', 'Business 2'), ('special_risk', 'Special Risk'), ('reinsurance', 'Reinsurance'), ('finance', 'Finance'), ('admin', 'Admin'), ('business_development', 'Business Development')])),
        migrations.AlterField(model_name="personnel", name="role_code",
                              field=models.CharField(max_length=40, choices=[('president', 'President'), ('sales', 'Sales'), ('accounting', 'Accounting'), ('accounting_manager', 'Accounting Manager'), ('general_manager', 'General Manager'), ('admin', 'Admin'), ('viewer', 'Viewer')])),
        migrations.AddConstraint(model_name="personnel",
            constraint=models.CheckConstraint(condition=models.Q(department__in=['board_of_directors', 'business_1', 'business_2', 'special_risk', 'reinsurance', 'finance', 'admin', 'business_development']), name="ri_personnel_department_check")),
        migrations.AddConstraint(model_name="personnel",
            constraint=models.CheckConstraint(condition=models.Q(role_code__in=['president', 'sales', 'accounting', 'accounting_manager', 'general_manager', 'admin', 'viewer']), name="ri_personnel_role_check")),
    ]
