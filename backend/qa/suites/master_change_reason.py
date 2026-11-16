import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from masterdata.models import MasterRecord
from personnel.models import Personnel

results = []
def check(label, condition):
    results.append(condition)
    print(('PASS ' if condition else 'FAIL ') + label)
class Rollback(Exception): pass
try:
    with transaction.atomic():
        p = Personnel.objects.create(name='ZZ Reason Admin', department='admin', role_code='admin', created_by='t', updated_by='t')
        u = get_user_model().objects.create_user(username='zz.reason.admin', password='Reason-Test-Pass-1')
        p.auth_user_id = str(u.pk); p.account_status = 'active'; p.save()
        c = Client(enforce_csrf_checks=True, HTTP_HOST='localhost'); cache.clear(); c.get('/api/auth/csrf')
        assert c.post('/api/auth/login', data=json.dumps({'username':'zz.reason.admin','password':'Reason-Test-Pass-1'}), content_type='application/json', HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value).status_code == 200
        def call(method, body):
            return getattr(c, method)('/api/master-data', data=json.dumps(body), content_type='application/json', HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
        for t in ('reinsurer', 'reinsured', 'foreign_broker', 'class', 'clause'):
            base = {'entityType':t, 'name':'ZZ Reason '+t, 'code': 'ZZ_'+t.upper()}
            r = call('post', base); assert r.status_code == 201, r.content
            record = r.json()['record']; ident = record['id']
            update = {**base, 'id':ident, 'rowVersion':record['rowVersion'], 'name':base['name']+' edited'}
            for reason in ('', '   '):
                r = call('put', {**update, 'changeReason':reason})
                check(t+' rejects blank edit reason', r.status_code == 400 and r.json().get('error') == 'reason_required')
            r = call('put', {**update, 'changeReason':'  correction  '})
            check(t+' accepts edit', r.status_code == 200)
            snap = EntitySnapshot.objects.get(entity_type='master_record', entity_id=str(ident), entity_version=2)
            audit = AuditLog.objects.filter(entity_type='master_record', entity_id=str(ident), action='update_master').latest('id')
            check(t+' records reason', snap.snapshot_data.get('changeReason') == 'correction' and audit.metadata.get('changeReason') == 'correction')
            updated = {**update, 'rowVersion':2, 'isActive':False}
            r = call('put', updated); check(t+' rejects deactivate without reason', r.status_code == 400 and r.json().get('error') == 'reason_required')
            r = call('put', {**updated, 'changeReason':'inactive'}); check(t+' accepts deactivate', r.status_code == 200)
            r = call('put', {**updated, 'rowVersion':3, 'isActive':True, 'name':base['name']+' bypass'}); check(t+' rejects edit disguised as reactivation', r.status_code == 400)
            r = call('put', {**updated, 'rowVersion':3, 'isActive':True}); check(t+' permits unchanged reactivation', r.status_code == 200)
        raise Rollback()
except Rollback: pass
print(f'\n{sum(results)}/{len(results)} passed; database changes rolled back')
