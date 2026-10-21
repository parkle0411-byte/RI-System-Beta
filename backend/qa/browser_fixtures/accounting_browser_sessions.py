import json,os
from django.test import Client
from django.contrib.auth import get_user_model
from cases.models import Case
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
sessions={}
for role,user in [('finance','ar92.browserfin'),('sales','ar92.browsersales')]:
 c=Client(HTTP_HOST='localhost');c.force_login(get_user_model().objects.get(username=user));sessions[role]=c.cookies['ri_sessionid'].value
refs={k:Case.objects.get(tw_ref__startswith='AR92-UI-'+v).tw_ref for k,v in [('premium','PREMIUM'),('claim','CLAIM'),('pending','PENDING'),('refund','REFUND'),('swiss','SWISS')]}
print('BROWSER_SEED '+json.dumps({'sessions':sessions,'refs':refs}))
