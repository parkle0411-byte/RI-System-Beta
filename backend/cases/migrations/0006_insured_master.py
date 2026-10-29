from django.db import migrations, models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('cases','0005_case_document_limit_30mb'),('masterdata','0004_insured_type')]
    operations=[migrations.AddField(model_name='case',name='insured_master',field=models.ForeignKey(blank=True,null=True,limit_choices_to={'entity_type':'insured'},on_delete=django.db.models.deletion.PROTECT,related_name='insured_cases',to='masterdata.masterrecord'))]
