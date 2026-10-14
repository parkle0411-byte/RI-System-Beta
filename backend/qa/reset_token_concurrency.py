"""Real one-time tokens and committed concurrent API requests. Disposable DB only."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
from unittest import mock
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.models import Session
from django.contrib.sessions.backends.db import SessionStore
from django.db import connections
from django.test import override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIRequestFactory
from audit.models import AuditLog
from personnel.models import Personnel
from personnel import accounts
from ri_system import password_reset as reset

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
User=get_user_model();tag=uuid4().hex[:8];factory=APIRequestFactory();results=[]
actor={'id':'qa-reset-concurrency','name':'QA','role':'admin'}
def check(name,ok,detail=''):
    results.append(bool(ok));print(('PASS ' if ok else 'FAIL ')+name+(' '+str(detail) if not ok else ''),flush=True)
def fixture(label):
    user=User.objects.create_user(username='zz.token.'+tag+'.'+label,password='Token-Initial-902!')
    p=Personnel.objects.create(name='ZZ Token '+tag+' '+label,department='reinsurance',role_code='sales',
        auth_user_id=str(user.pk),account_status='active',is_active=True,must_change_password=True,created_by='qa',updated_by='qa')
    return user,p,dict(uid=urlsafe_base64_encode(force_bytes(user.pk)),token=default_token_generator.make_token(user))
def call(body,password,ip='127.0.0.91'):
    req=factory.post('/',dict(body,newPassword=password),format='json',REMOTE_ADDR=ip)
    return reset.PasswordResetConfirmView.as_view()(req)
def thread_call(fn):
    try:return fn()
    finally:connections.close_all()
def prepared_overlap(body,password,second,ip):
    held,release=threading.Event(),threading.Event()
    original=reset.validate_password
    def hook(*a,**kw):
        result=original(*a,**kw);held.set();assert release.wait(20);return result
    with mock.patch.object(reset,'validate_password',side_effect=hook),ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(thread_call,lambda:call(body,password,ip));assert held.wait(15)
        try:other=second()
        finally:release.set()
        return future.result(timeout=30),other

with override_settings(AUDIT_LOG_PAUSED=True),mock.patch.object(reset,'send_reset_email') as email:
    audit_before=AuditLog.objects.count()
    user,p,body=fixture('once')
    session_key='zz-token-'+uuid4().hex[:20]
    Session.objects.create(session_key=session_key,session_data=SessionStore().encode({'_auth_user_id':str(user.pk)}),
        expire_date=timezone.now()+timedelta(hours=1))
    barrier=threading.Barrier(2);original=reset.validate_password
    def hook(*a,**kw):
        value=original(*a,**kw);barrier.wait(timeout=15);return value
    passwords=['Token-First-902!','Token-Second-902!']
    with mock.patch.object(reset,'validate_password',side_effect=hook),ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(thread_call,lambda pw=pw:call(body,pw)) for pw in passwords]
        responses=[f.result(timeout=30) for f in futures]
    statuses=[r.status_code for r in responses];winner=[i for i,r in enumerate(responses) if r.status_code==200]
    check('same token concurrent reset permits exactly one request',sorted(statuses)==[200,400],statuses)
    check('losing reset returns invalid_reset_link',sum(r.status_code==400 and r.data.get('error')=='invalid_reset_link' for r in responses)==1)
    user.refresh_from_db();p.refresh_from_db()
    check('stored password matches the successful request',len(winner)==1 and user.check_password(passwords[winner[0]]))
    check('successful reset clears temporary-password flag',not p.must_change_password)
    check('successful reset ends existing sessions',not Session.objects.filter(session_key=session_key).exists())
    replay=call(body,'Token-Replay-902!')
    check('sequential reuse is still refused',replay.status_code==400 and replay.data.get('error')=='invalid_reset_link',replay.data)

    user,p,body=fixture('disabled');old=user.password
    response,_=prepared_overlap(body,'Token-After-Disable-902!',lambda:accounts.disable_account(personnel_id=p.pk,
        actor=actor,source='application'),'127.0.0.92')
    user.refresh_from_db();p.refresh_from_db()
    check('account disabled after initial checks refuses pending token',response.status_code==400 and response.data.get('error')=='invalid_reset_link',response.data)
    check('pending reset does not change disabled account password',user.password==old and not user.is_active and p.account_status=='disabled')
    check('pending reset does not clear disabled account temporary flag',p.must_change_password)

    user,p,body=fixture('admin-reset')
    response,admin_result=prepared_overlap(body,'Token-After-Admin-Reset-902!',lambda:accounts.reset_password(personnel_id=p.pk,
        actor=actor,source='application'),'127.0.0.93')
    user.refresh_from_db();p.refresh_from_db()
    check('administrator password reset invalidates pending self reset',response.status_code==400 and response.data.get('error')=='invalid_reset_link',response.data)
    check('pending self reset preserves administrator password and temporary flag',user.check_password(admin_result[2]) and p.must_change_password)
    check('no outbound reset email called',email.call_count==0)
    check('Audit remains paused',AuditLog.objects.count()==audit_before)
print(f'{sum(results)}/{len(results)} passed',flush=True)
assert all(results),results
