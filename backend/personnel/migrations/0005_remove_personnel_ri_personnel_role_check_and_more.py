from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('personnel', '0004_board_of_directors_president'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='personnel',
            name='ri_personnel_role_check',
        ),
        migrations.AlterField(
            model_name='personnel',
            name='role_code',
            field=models.CharField(choices=[('legacy_supervisor', 'Read-only Supervisor'), ('president', 'President'), ('sales', 'Sales'), ('accounting', 'Accounting'), ('accounting_manager', 'Accounting Manager'), ('general_manager', 'General Manager'), ('admin', 'Admin'), ('viewer', 'Viewer')], max_length=40),
        ),
        migrations.AddConstraint(
            model_name='personnel',
            constraint=models.CheckConstraint(condition=models.Q(('role_code__in', ['legacy_supervisor', 'president', 'sales', 'accounting', 'accounting_manager', 'general_manager', 'admin', 'viewer'])), name='ri_personnel_role_check'),
        ),
    ]
