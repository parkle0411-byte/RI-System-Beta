"""Synthetic password reset edge cases; run only in the disposable DB."""
import os, json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import transaction
from django.test import Client, override_settings
from django.utils.http import urlsafe_base64_encode
from django.contrib.auth.tokens import default_token_generator
from personnel.models import Personnel
from ri_system import password_reset as reset

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
User = get_user_model()
results = []
R = '/api/auth/password-reset'
C = R + '/confirm'
def check(name, ok, detail=''):
    results.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ((' '+str(detail)) if not ok else ''), flush=True)
def call(path, body):
    cache.clear()
    return Client(HTTP_HOST='localhost', raise_request_exception=False).post(path, data=json.dumps(body), content_type='application/json')
def fixture(label, username=None, ref=None, user_active=True):
    user = User.objects.create_user(username=username or 'zz.reset.'+label, password='Reset-Initial-982!', is_active=user_active) if ref is None else None
    person = Personnel.objects.create(name='ZZ Reset '+label, department='reinsurance', role_code='sales',
        email=label+'@reset.example', auth_user_id=str(user.pk) if user else ref,
        account_status='active', created_by='qa', updated_by='qa')
    return person, user
class Rollback(Exception): pass
try:
    with transaction.atomic(), override_settings(EMAIL_ENABLED=True, EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', AUDIT_LOG_PAUSED=True):
        p, user = fixture('atname', username='zz.reset@account')
        mail.outbox=[]
        response = call(R, {'identifier':' ZZ.RESET@ACCOUNT '})
        check('username containing @ sends to its Personnel email', response.status_code==200 and len(mail.outbox)==1 and mail.outbox[0].to==[p.email])
        for label, ref in [('orphan','999999999'), ('badref','not-an-id'), ('huge','99999999999999999999999999999999999999999999999999999999')]:
            p,_=fixture(label, ref=ref)
            mail.outbox=[]
            response=call(R, {'identifier':p.email})
            check(label+' account reference returns generic response without sending', response.status_code==200 and response.json().get('message')==reset.GENERIC and not mail.outbox, response.status_code)
        p,_=fixture('authinactive',user_active=False)
        mail.outbox=[]
        response=call(R, {'identifier':p.email})
        check('inactive Django user receives no reset email', response.status_code==200 and not mail.outbox, len(mail.outbox))
        for path in (R,C):
            for label,body in [('array',[]),('null',None),('string','bad')]:
                response=call(path,body)
                check(path+' rejects '+label+' JSON body',response.status_code==400 and response.json().get('error')=='invalid_body',response.status_code)
        p,user=fixture('typed')
        parts={'uid':urlsafe_base64_encode(str(user.pk).encode()), 'token':default_token_generator.make_token(user)}
        previous=user.password
        response=call(C,dict(parts,newPassword=['Letters-And-123']))
        user.refresh_from_db()
        check('non-string password is rejected without changing credentials',response.status_code==400 and user.password==previous,response.status_code)
        mail.outbox=[]
        with patch.object(reset,'send_reset_email',side_effect=RuntimeError('synthetic SMTP failure')):
            response=call(R,{'identifier':user.username})
        check('SMTP failure keeps generic response',response.status_code==200 and response.json().get('message')==reset.GENERIC and not mail.outbox)
        response=call(R,{'identifier':{'username':user.username}})
        check('non-string identifier returns invalid_body',response.status_code==400 and response.json().get('error')=='invalid_body',response.status_code)
        raise Rollback()
except Rollback: pass
cache.clear()
print(f'{sum(results)}/{len(results)} passed; synthetic changes rolled back',flush=True)
if not all(results): raise SystemExit(1)
