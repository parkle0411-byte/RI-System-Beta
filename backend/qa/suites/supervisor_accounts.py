"""Supervisor account creation scope, lifecycle, attribution and credential boundaries."""
import json
import os
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog, EntitySnapshot
from personnel.models import Personnel
from personnel import accounts
from ri_system.authz import actor_from

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
User = get_user_model()
checks = []
def check(name, ok):
    assert ok, name
    checks.append(name)
    print('PASS '+name, flush=True)
def person(name, dept, role, **kw):
    if kw.get('is_active') is False:
        kw.update(deactivated_by='qa',deactivated_at=timezone.now())
    if kw.get('account_status') == 'disabled':
        u=User.objects.create_user(username='qa.disabled.'+str(User.objects.count()),password='QA-Disabled-Password-9!',is_active=False)
        kw['auth_user_id']=str(u.pk)
    return Personnel.objects.create(name=name, department=dept, role_code=role, created_by='qa', updated_by='qa', **kw)
def client(p):
    u=User.objects.create_user(username='qa.supervisor.'+str(p.pk),password='Qa-Supervisor-Password-9!')
    p.auth_user_id=str(u.pk);p.account_status='active';p.save()
    c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost')
    c.force_login(u);c.get('/api/auth/csrf')
    return c
def post(c,path,body):
    return c.post(path,data=json.dumps(body),content_type='application/json',HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)
def create(c,p,**kw):
    return post(c,'/api/personnel-accounts',{'personnelId':p.pk,'username':'qa.subordinate.'+str(p.pk),**kw})
def state():
    return json.dumps({m.__name__:list(m.objects.order_by('pk').values()) for m in [Personnel,User,AuditLog,EntitySnapshot]},sort_keys=True,default=str)
class Rollback(Exception):pass
try:
 with transaction.atomic():
    for dept,role,staff in [('reinsurance','sales','sales'),('finance','accounting_manager','accounting'),('business_1','viewer','viewer'),('reinsurance','general_manager','sales')]:
        sup=person('QA Account Supervisor '+dept+' '+role,dept,role)
        c=client(sup)
        peer=person('QA Account Peer '+str(sup.pk),dept,staff)
        check(role+' no Supervisor assignment means no account privilege',create(c,peer).status_code==403)
        old=person('QA Existing Account Team '+str(sup.pk),dept,staff,supervisor_name=sup.name,email='saved.'+str(sup.pk)+'@example.test')
        ctx=c.get('/api/app-context').json()['principal']
        check(role+' has creation permission without lifecycle permission','accounts.create.subordinate' in ctx['permissions'] and 'accounts.manage' not in ctx['permissions'])
        forbidden=[peer,sup,
            person('QA High Team '+str(sup.pk),dept,'admin',supervisor_name=sup.name),
            person('QA Manager Team '+str(sup.pk),dept,'accounting_manager',supervisor_name=sup.name),
            person('QA Cross Team '+str(sup.pk),'admin' if dept!='admin' else 'finance','viewer',supervisor_name=sup.name),
            person('QA Inactive Team '+str(sup.pk),dept,staff,supervisor_name=sup.name,is_active=False),
            person('QA Disabled Team '+str(sup.pk),dept,staff,supervisor_name=sup.name,account_status='disabled')]
        before=state()
        for p in forbidden:
            check(role+' denies account outside allowed scope '+p.name,create(c,p).status_code==403)
        check(role+' cannot change saved Personnel Email',create(c,old,email='override@example.test').status_code==403)
        for password in ['short','password',' '*10,'Ab1!'*40]:
            check(role+' rejects weak or oversized custom password',create(c,old,initialPassword=password).status_code==400)
        check(role+' requires CSRF',c.post('/api/personnel-accounts',data=json.dumps({'personnelId':old.pk,'username':'qa.csrf'}),content_type='application/json').status_code==403)
        check(role+' rejected creation changes no records',before==state())
        roster={p['id']:p for p in c.get('/api/personnel').json()['personnel']}
        check(role+' eligible existing team has create action',roster[old.pk]['canCreateAccount'])
        check(role+' own account metadata remains private',not roster[sup.pk]['canCreateAccount'] and 'accountUsername' not in roster[sup.pk])
        if role=='general_manager':
            check('GM broad roster does not grant peer account metadata','accountUsername' not in roster[peer.pk] and not roster[peer.pk]['canCreateAccount'])
        made=create(c,old,email=old.email.upper(),roleCode='admin',department='admin',supervisorName='Injected')
        check(role+' creates existing direct subordinate account',made.status_code==201)
        data=made.json();secret=data.get('initialPassword','');old.refresh_from_db();u=User.objects.get(pk=int(old.auth_user_id))
        check(role+' response is no-store and generated password works','no-store' in made['Cache-Control'].split(', ') and len(secret)>=16 and u.check_password(secret))
        check(role+' target role department supervisor remain fixed',old.role_code==staff and old.department==dept and old.supervisor_name==sup.name)
        check(role+' account forces first password change and records Supervisor actor',old.must_change_password and old.account_status=='active' and old.account_invited_by==actor_from(sup)['id'])
        check(role+' Supervisor roster exposes team username and hides duplicate creation',next(p for p in c.get('/api/personnel').json()['personnel'] if p['id']==old.pk)['accountUsername']==u.username and not next(p for p in c.get('/api/personnel').json()['personnel'] if p['id']==old.pk)['canCreateAccount'])
        before=state()
        check(role+' cannot create duplicate account',create(c,old).status_code==403)
        for action in ['enable','disable','reset-password']:
            check(role+' cannot '+action+' subordinate account',post(c,'/api/personnel-accounts/'+action,{'personnelId':old.pk}).status_code==403)
        check(role+' denied lifecycle changes no records',before==state())
        signed=Client(HTTP_HOST='localhost');signed.force_login(u)
        check(role+' new account cannot access business data before password change',signed.get('/api/cases').status_code==403)
        ev=AuditLog.objects.get(entity_type='personnel',entity_id=str(old.pk),action='create_account')
        check(role+' account audit identifies Supervisor',ev.actor_id==actor_from(sup)['id'] and ev.metadata['passwordSource']=='generated')
        added=post(c,'/api/personnel',{'name':'QA Newly Added Account Team '+str(sup.pk)})
        check(role+' can add subordinate before creating login',added.status_code==201)
        new=Personnel.objects.get(pk=added.json()['person']['id'])
        custom='Supervisor-Custom-Password-9!'
        made=create(c,new,initialPassword=custom)
        check(role+' creates newly added subordinate with custom initial password',made.status_code==201 and made.json()['passwordSource']=='supervisor' and custom not in made.content.decode() and 'initialPassword' not in made.json())
        new.refresh_from_db()
        check(role+' custom password works',User.objects.get(pk=int(new.auth_user_id)).check_password(custom))
        dump=json.dumps(list(AuditLog.objects.values()),default=str)+json.dumps(list(EntitySnapshot.objects.values()),default=str)
        check(role+' credentials never appear in audit or snapshots',secret not in dump and custom not in dump)
        pending=person('QA Pending Account Team '+str(sup.pk),dept,staff,supervisor_name=sup.name)
        sup.must_change_password=True;sup.save()
        check(role+' forced password change blocks account creation',create(c,pending).status_code==403)
        sup.must_change_password=False;sup.save()
        # Exercise service rechecks with the identity previously authorized by the view.
        def delegated():
            return accounts.create_account(personnel_id=pending.pk,username='qa.service.'+str(pending.pk),email=None,actor=actor_from(sup),source='application',supervisor_personnel_id=sup.pk)
        for change in [{'supervisor_name':None},{'role_code':'admin'},{'department':'admin'}]:
            original={k:getattr(pending,k) for k in change};Personnel.objects.filter(pk=pending.pk).update(**change)
            try:delegated();denied=False
            except accounts.AccountError as e:denied=e.status==403
            check(role+' service rechecks reassignment promotion department '+str(change),denied)
            Personnel.objects.filter(pk=pending.pk).update(**original)
        Personnel.objects.filter(pk=sup.pk).update(account_status='disabled')
        try:delegated();denied=False
        except accounts.AccountError as e:denied=e.status==403
        check(role+' service rechecks Supervisor account revocation',denied)
        Personnel.objects.filter(pk=sup.pk).update(account_status='active')
        before=state()
        with patch('personnel.accounts.record_audit',side_effect=RuntimeError('QA rollback')):
            try:
                with transaction.atomic():delegated()
            except RuntimeError:pass
        check(role+' failed audit rolls back account creation',before==state())
        Personnel.objects.filter(supervisor_name=sup.name).update(supervisor_name=None)
        check(role+' removing Supervisor status immediately revokes account creation',create(c,pending).status_code==403 and 'accounts.create.subordinate' not in c.get('/api/app-context').json()['principal']['permissions'])
    # Same-name Supervisors must obey canonical same-department / lowest-ID resolution.
    first=person('QA Account Twin','business_2','viewer');first_c=client(first)
    second=person('QA Account Twin','reinsurance','general_manager');second_c=client(second)
    target=person('QA Twin Target','business_2','viewer',supervisor_name=first.name)
    check('ambiguous same-name assignment does not grant second person access',create(second_c,target).status_code==403)
    check('canonical same-name Supervisor can create account',create(first_c,target).status_code==201)
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} supervisor account checks passed; database changes rolled back')
