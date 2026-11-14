from masterdata.models import MasterRecord
from personnel.models import Personnel
for typ,name,code in [('class','Fine Art','FA'),('class','Terrorism','TR'),('foreign_broker','Oversea UI Broker',None),('reinsured','Oversea UI Cedant',None),('ae','Oversea UI AE',None)]:
 MasterRecord.objects.get_or_create(entity_type=typ,name=name,defaults=dict(code=code,payload={},created_by='seed',updated_by='seed'))
Personnel.objects.get_or_create(name='Oversea UI AE', defaults=dict(department='reinsurance', role_code='sales', email='oversea-ui-ae@example.test', created_by='seed', updated_by='seed'))
print('Oversea UI masters seeded')
