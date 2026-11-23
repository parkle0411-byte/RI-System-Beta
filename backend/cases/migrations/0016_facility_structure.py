from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('cases', '0015_facility_declarations')]
    operations = [
        migrations.RemoveConstraint(model_name='case', name='ri_cases_reinsurance_structure_check'),
        migrations.AlterField(model_name='case', name='reinsurance_structure', field=models.CharField(
            blank=True, null=True, max_length=20,
            choices=[('FACULTATIVE', 'Facultative'), ('QS', 'Quota Share'), ('XOL', 'Excess of Loss'),
                     ('OVERSEA', 'Oversea Business'), ('FACILITY', 'Facility')])),
        migrations.AddConstraint(model_name='case', constraint=models.CheckConstraint(
            condition=models.Q(reinsurance_structure__isnull=True) | models.Q(reinsurance_structure__in=['FACULTATIVE', 'QS', 'XOL', 'OVERSEA', 'FACILITY']),
            name='ri_cases_reinsurance_structure_check')),
    ]
