from django.db import migrations, models
class Migration(migrations.Migration):
    dependencies=[('masterdata','0003_marketratingprofile')]
    operations=[migrations.AlterField(model_name='masterrecord',name='entity_type',field=models.CharField(max_length=40,choices=[('ae','AE'),('reinsurer','Reinsurer'),('reinsured','Reinsured'),('class','Class'),('foreign_broker','Foreign RI Broker'),('clause','Clause'),('insured','Original Insured')]))]
