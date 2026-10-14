"""Three-hour idle boundary, explicit activity, security and independent browser sessions."""
import json
import os
import time
from datetime import timedelta
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.db import transaction
from django.test import Client
from django.utils import timezone
from personnel.models import Personnel
from ri_system.session_idle import LAST_ACTIVITY, SESSION_ID

assert os.environ.get('RI_DISPOSABLE_QA')=='true'
User=get_user_model();checks=[]
def check(name,ok):
    assert ok,name
    checks.append(name);print('PASS '+name,flush=True)
def person(role,dept):
    p=Personnel.objects.create(name='QA Idle '+role,department=dept,role_code=role,created_by='qa',updated_by='qa')
    u=User.objects.create_user(username='qa.idle.'+role,password='QA-Idle-Password-9!')
    p.auth_user_id=str(u.pk);p.account_status='active';p.save()
    return p,u
def client(u):
    c=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');c.force_login(u);c.get('/api/auth/csrf');return c
def post(c,path,body,csrf=True):
    kw={'HTTP_X_CSRFTOKEN':c.cookies['csrftoken'].value} if csrf else {}
    return c.post(path,data=json.dumps(body),content_type='application/json',**kw)
def data(c):return c.get('/api/auth/session').json()['session']
def save_value(c,key,value):
    s=c.session;s[key]=value;s.save()
class Rollback(Exception):pass
try:
 with transaction.atomic():
    check('Production default idle timeout is exactly 3 hours',settings.SESSION_IDLE_TIMEOUT_SECONDS==10800 and settings.SESSION_COOKIE_AGE==10800)
    check('Production warning is 5 minutes and reads do not save every request',settings.SESSION_IDLE_WARNING_SECONDS==300 and not settings.SESSION_SAVE_EVERY_REQUEST)
    for role,dept in [('admin','admin'),('sales','reinsurance'),('accounting','finance'),('accounting_manager','finance'),('general_manager','reinsurance'),('viewer','business_1'),('president','board_of_directors')]:
        p,u=person(role,dept);c=client(u);initial=data(c);start=c.session[LAST_ACTIVITY]
        check(role+' adopts three-hour policy with a public non-cookie ID',len(initial['id'])==32 and initial['id']!=c.cookies[settings.SESSION_COOKIE_NAME].value and initial['expiresAt']==round((start+10800)*1000))
        snapshot=c.session[LAST_ACTIVITY]
        with patch('ri_system.session_idle.now_seconds',return_value=start+600):
            for path in ['/api/app-context','/api/auth/session','/api/auth/csrf','/api/dashboard']:
                r=c.get(path)
                check(role+' background read does not extend expiry '+path,c.session[LAST_ACTIVITY]==snapshot)
        with patch('ri_system.session_idle.now_seconds',return_value=start+7200):
            response=post(c,'/api/auth/activity',{'sessionId':initial['id'],'timestamp':start+99999999})
        check(role+' genuine activity renews from server time',response.status_code==200 and c.session[LAST_ACTIVITY]==start+7200 and response.json()['session']['expiresAt']==round((start+7200+10800)*1000))
        check(role+' activity response never caches and secure cookie flags remain',response['Cache-Control'].startswith('no-store') and c.cookies[settings.SESSION_COOKIE_NAME]['httponly'] and c.cookies[settings.SESSION_COOKIE_NAME]['samesite']=='Lax')
        refreshed=c.session[LAST_ACTIVITY]
        with patch('ri_system.session_idle.now_seconds',return_value=start+7201):
            check(role+' wrong public Session ID cannot renew',post(c,'/api/auth/activity',{'sessionId':'another-session'}).status_code==409 and c.session[LAST_ACTIVITY]==refreshed)
            check(role+' missing CSRF cannot renew',post(c,'/api/auth/activity',{'sessionId':initial['id']},csrf=False).status_code==403 and c.session[LAST_ACTIVITY]==refreshed)
        with patch('ri_system.session_idle.now_seconds',return_value=refreshed+10799.9):
            check(role+' remains authenticated immediately before 3 hours',c.get('/api/app-context').status_code==200)
        old_cookie=c.cookies[settings.SESSION_COOKIE_NAME].value
        with patch('ri_system.session_idle.now_seconds',return_value=refreshed+10800):
            r=c.get('/api/app-context')
        check(role+' expires exactly at the 3-hour boundary',r.status_code==401 and r.json()['error']=='SESSION_IDLE_TIMEOUT')
        check(role+' expired session is removed from the DB and cookie cleared',not Session.objects.filter(session_key=old_cookie).exists() and not c.cookies[settings.SESSION_COOKIE_NAME].value)
        check(role+' expired cookie cannot be replayed to revive activity',post(c,'/api/auth/activity',{'sessionId':initial['id']}).status_code==401)
        check(role+' expired user cannot write business data',post(c,'/api/cases',{}).status_code==401)
    admin=Personnel.objects.get(role_code='admin');au=User.objects.get(pk=int(admin.auth_user_id))
    fresh=Client(enforce_csrf_checks=True,HTTP_HOST='localhost');fresh.get('/api/auth/csrf')
    r=post(fresh,'/api/auth/login',{'username':au.username,'password':'QA-Idle-Password-9!'})
    check('Real login initializes an idle session',r.status_code==200 and r.json()['session']['timeoutSeconds']==10800)
    first=data(fresh)['id'];other=client(au)
    check('Different browser logins have independent public IDs',first!=data(other)['id'])
    initial=fresh.session[LAST_ACTIVITY]
    with patch('ri_system.session_idle.now_seconds',return_value=initial+10800):r=fresh.get('/api/app-context')
    check('One browser expiring does not sign out another',r.status_code==401 and other.get('/api/app-context').status_code==200)
    key=other.cookies[settings.SESSION_COOKIE_NAME].value
    check('Read-only admin includes activity tracker and warning initializer',other.get('/admin/').status_code==200 and b'admin-session-idle.js' in other.get('/admin/').content)
    before=data(other)
    r=post(other,'/api/auth/change-password',{'currentPassword':'QA-Idle-Password-9!','newPassword':'QA-Idle-New-Password-9!'})
    after=data(other)
    check('Password change rotates the cookie while preserving idle Session ID and deadline',r.status_code==200 and other.cookies[settings.SESSION_COOKIE_NAME].value!=key and before['id']==after['id'] and before['expiresAt']==after['expiresAt'])
    admin.must_change_password=True;admin.save()
    state=data(other)
    check('Forced password change dialog can report activity',post(other,'/api/auth/activity',{'sessionId':state['id']}).status_code==200)
    check('Activity cannot bypass forced password change business guard',other.get('/api/dashboard').status_code==403)
    admin.must_change_password=False;admin.save()
    admin.account_status='disabled';admin.save()
    before=other.session[LAST_ACTIVITY]
    check('Disabled Personnel cannot renew a session',post(other,'/api/auth/activity',{'sessionId':state['id']}).status_code==403 and other.session[LAST_ACTIVITY]==before)
    anon=Client(HTTP_HOST='localhost')
    check('Anonymous status and activity are denied',anon.get('/api/auth/session').status_code==401 and post(anon,'/api/auth/activity',{},csrf=False).status_code==401)
    check('Anonymous CSRF and manual logout remain usable',anon.get('/api/auth/csrf').status_code==200 and post(anon,'/api/auth/logout',{},csrf=False).status_code==200)
    raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} idle session checks passed; database changes rolled back')
