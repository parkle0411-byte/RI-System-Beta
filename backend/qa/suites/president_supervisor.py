"""Active President can supervise every department without a login account."""
import json
import os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from personnel.models import Personnel
from personnel.views import DEPARTMENTS

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(name, ok):
    assert ok,name
    checks.append(name)
    print('PASS '+name)

class Rollback(Exception): pass

try:
    with transaction.atomic():
        user=get_user_model().objects.create_user(username='qa.supervisor.admin',password='Qa-Supervisor-Password-9!')
        admin_person=Personnel.objects.create(name='QA Supervisor Administrator',department='admin',role_code='admin',
            auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
        david=Personnel.objects.create(name='David Kao',email='david.kao@tw-insure.com',department='board_of_directors',
            role_code='president',is_active=True,is_split_eligible=False,created_by='qa',updated_by='qa')
        c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(user);c.get('/api/auth/csrf')
        def call(method,body):
            return getattr(c,method)('/api/personnel',data=json.dumps(body),content_type='application/json',
                HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
        rows=[]
        for dept in sorted(DEPARTMENTS):
            body={'name':'QA President Supervised '+dept,'department':dept,'roleCode':'viewer',
                  'isActive':True,'supervisorName':'David Kao','supervisorEmail':'client-wrong@example.invalid'}
            response=call('post',body)
            check('President accepted as Supervisor for '+dept,response.status_code==201)
            p=response.json()['person'];rows.append(p)
            check('President email resolved on server for '+dept,
                p['supervisorName']=='David Kao' and p['supervisorEmail']=='david.kao@tw-insure.com')
        david.refresh_from_db()
        check('choosing President never enables login or split',not david.auth_user_id
            and david.account_status=='not_configured' and not david.is_split_eligible)

        p=rows[0]
        response=call('put',{**p,'supervisorName':'David Kao','supervisorEmail':'wrong@example.invalid'})
        check('editing Personnel preserves chosen President and resolves email',response.status_code==200
            and response.json()['person']['supervisorEmail']=='david.kao@tw-insure.com')
        p=response.json()['person']
        response=call('put',{**p,'supervisorName':''})
        check('optional Supervisor can be cleared',response.status_code==200
            and response.json()['person']['supervisorName']=='' and response.json()['person']['supervisorEmail']=='')
        response=call('put',{'id':david.pk,'rowVersion':david.row_version,'name':david.name,'email':david.email,
            'department':david.department,'roleCode':'president','isActive':True,'isSplitEligible':False,
            'supervisorName':'David Kao'})
        check('President cannot select himself as Supervisor',response.status_code==400
            and response.json()['error']=='invalid_supervisor')

        david.is_active=False;david.deactivated_by='qa';from django.utils import timezone
        david.deactivated_at=timezone.now();david.save()
        response=call('post',{'name':'QA Reject Inactive President','department':'finance',
                             'supervisorName':'David Kao'})
        check('inactive President is rejected even across departments',response.status_code==400
            and response.json()['error']=='invalid_supervisor')
        david.is_active=True;david.deactivated_at=None;david.deactivated_by=None;david.save()

        for name,dept,role in [('QA General Manager','reinsurance','general_manager'),
                               ('QA Finance Supervisor','finance','accounting'),
                               ('QA Ordinary Sales','reinsurance','sales')]:
            Personnel.objects.create(name=name,department=dept,role_code=role,created_by='qa',updated_by='qa')
        for name,ok in [('QA General Manager',True),('QA Finance Supervisor',True),('QA Ordinary Sales',False)]:
            response=call('post',{'name':'QA Test Existing Rule '+name,'department':'finance','supervisorName':name})
            check('existing eligibility unchanged for '+name,response.status_code==(201 if ok else 400))
        check('Supervisor selection never creates user accounts',get_user_model().objects.count()==1)
        raise Rollback()
except Rollback:
    pass
print(f'{len(checks)}/{len(checks)} President Supervisor API checks passed; database changes rolled back')
