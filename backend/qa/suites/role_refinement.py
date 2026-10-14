"""Finance Staff Production reads / mutation denial and President Personnel scope."""
import json
import os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from audit.models import AuditLog,EntitySnapshot
from cases.models import Case
from production.models import ProductionReport,ProductionExclusion
from personnel.models import Personnel
from personnel import accounts
from ri_system.authz import actor_from

assert os.environ.get('RI_DISPOSABLE_QA')=='true'
User=get_user_model()
checks=[]
def check(name,ok):
    assert ok,name
    checks.append(name);print('PASS '+name,flush=True)
def person(name,department,role,**kw):
    return Personnel.objects.create(name=name,department=department,role_code=role,created_by='qa',updated_by='qa',**kw)
def client(p):
    u=User.objects.create_user(username='qa.refinement.'+str(p.pk),password='QA-Refinement-Password-9!')
    p.auth_user_id=str(u.pk);p.account_status='active';p.save()
    c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(u);c.get('/api/auth/csrf');return c
def post(c,path,body):
    return c.post(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
def state():
    return json.dumps({m.__name__:list(m.objects.order_by('pk').values()) for m in [User,Personnel,ProductionReport,ProductionExclusion,Case,AuditLog,EntitySnapshot]},sort_keys=True,default=str)
class Rollback(Exception):pass
try:
 with transaction.atomic():
    staff=person('QA Report Reader','finance','accounting');c=client(staff)
    manager=person('QA Report Manager','finance','accounting_manager');mc=client(manager)
    admin=person('QA Report Admin','admin','admin');ac=client(admin)
    report=ProductionReport.objects.create(year_month='2032-01',version=1,status='valid',rows=[{'originalInsured':'QA Existing Report','premium':5000,'income':250}],excluded_rows=[],source_signature='qa',created_by='qa')
    r=c.get('/api/production-report?month=2032-01');check('Finance Staff can inspect preview and saved versions',r.status_code==200 and r.json()['versions'][0]['rows']==report.rows)
    scope=r.json()['scope'];check('Finance Staff advertises read-only, no generate exclude or close',scope['readOnly'] and not any(scope[k] for k in ['canOperate','canGenerate','canClose','canCloseLatest']))
    before=state()
    # No monthly lock or source evaluation is needed for a forbidden mutation.
    with patch('production.views.monthly_operation',side_effect=AssertionError('Forbidden caller acquired monthly lock')),patch('production.views.load_month',side_effect=AssertionError('Forbidden caller calculated sources')):
        for action in ['generate','exclude','close']:
            r=post(c,'/api/production-report',{'action':action,'month':'2032-01','scope':'case','reason':'QA','rowId':'missing','reportUid':str(report.report_uid),'rowVersion':1,'sourceSignature':'qa'})
            check('Finance Staff direct '+action+' denied before acquiring locks',r.status_code==403)
    check('Finance Staff rejected Production writes change nothing',before==state())
    check('Finance Staff retains Accounting writes and all-case reads',c.get('/api/accounting').json()['scope']['canEdit'] and 'cases.read.all' in c.get('/api/app-context').json()['principal']['permissions'])
    for tag,cc in [('Finance Manager',mc),('Administrator',ac)]:
        scope=cc.get('/api/production-report?month=2032-01').json()['scope']
        check(tag+' retains generate exclude and close capability',not scope['readOnly'] and scope['canOperate'] and scope['canClose'])
        r=post(cc,'/api/production-report',{'action':'generate','month':'2032-02','sourceSignature':cc.get('/api/production-report?month=2032-02').json()['sourceSignature']})
        check(tag+' can generate a real new report',r.status_code==201)
    president=person('QA Personnel President','board_of_directors','president');pc=client(president)
    peer=person('QA Other Department Personnel','business_2','viewer')
    for assigned in [False,True]:
        if assigned:
            subordinate=person('QA President Direct Subordinate','board_of_directors','viewer',supervisor_name=president.name)
        roster=pc.get('/api/personnel');scope=roster.json()['scope'];ctx=pc.get('/api/app-context').json()['principal']
        check('President sees all departments '+str(assigned),roster.status_code==200 and {p.pk for p in [president,peer,staff,manager,admin]} <= {p['id'] for p in roster.json()['personnel']})
        check('President roster is read-only '+str(assigned),scope['readAll'] and not scope['canCreate'] and not scope['canEdit'] and not scope['subordinateCreationOnly'])
        check('President never receives Personnel creation or write '+str(assigned),'personnel.create.subordinate' not in ctx['permissions'] and 'personnel.write' not in ctx['permissions'])
        before=state()
        check('President cannot add Personnel even as Supervisor '+str(assigned),post(pc,'/api/personnel',{'name':'QA Denied President Personnel'}).status_code==403)
        r=pc.put('/api/personnel',data=json.dumps({'id':peer.pk,'rowVersion':peer.row_version,'roleCode':'admin'}),content_type='application/json',HTTP_X_CSRFTOKEN=pc.cookies['csrftoken'].value)
        check('President cannot edit or promote Personnel '+str(assigned),r.status_code==403)
        check('President forbidden Personnel writes leave records unchanged '+str(assigned),before==state())
        check('President receives no Supervisor write grants '+str(assigned),not any(p in ctx['permissions'] for p in ['accounts.manage','accounts.create.subordinate','personnel.create.subordinate']))
        for action in ['', '/enable','/disable','/reset-password']:
            r=post(pc,'/api/personnel-accounts'+action,{'personnelId':peer.pk,'username':'qa.denied.president'})
            check('President cannot manage accounts '+action+' '+str(assigned),r.status_code==403)
        check('President roster never offers account creation '+str(assigned),all(not p['canCreateAccount'] for p in roster.json()['personnel']))
        if assigned:
            check('President Supervisor status is independent of login grants',ctx['isSupervisor'])
            try:
                accounts.create_account(personnel_id=subordinate.pk,username='qa.president.service',email=None,actor=actor_from(president),source='application',supervisor_personnel_id=president.pk)
                denied=False
            except accounts.AccountError as e:denied=e.status==403
            check('Account service rechecks President restriction on locked records',denied)
        check('President denied account writes leave records unchanged '+str(assigned),before==state())
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} role refinement checks passed; database changes rolled back')
