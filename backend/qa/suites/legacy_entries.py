"""Standalone entry/lifecycle contracts in disposable MySQL, including negative claims."""
import os,json,uuid
from django.test import Client
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from legacy.models import LegacyTransaction,LegacyAudit,NumberCounter
from cases.models import Case
from personnel.models import Personnel
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,ok,detail=''):
    assert ok,(name,detail)
    checks.append(name);print('PASS '+name,flush=True)
def send(c,body,method='PATCH'):
    r=getattr(c,method.lower())('/api/legacy',json.dumps(body),content_type='application/json')
    return r.status_code,r.json()
clients={};people={}
for role in ['sales','admin','accounting','accounting_manager','general_manager','president','legacy_supervisor','viewer']:
    u=get_user_model().objects.create_user(username='entry-'+role,password='Qa-Test-9!')
    p=Personnel.objects.create(name='Entry '+role,department='reinsurance',role_code=role,
        auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
    c=Client(HTTP_HOST='localhost');c.force_login(u);clients[role]=c;people[role]=p
def make_source(reference,currency='TWD',**data):
    """A confirmed historical premium row. Since 2026-11-12 Cedant, party, currency, Share and the
    AE/Sub AE split follow the source, so scenarios needing other values use their own source."""
    base=dict(reference=reference,currency=currency,insured='Test insured',insuredCn='',cedant='Test cedant',party='Test reinsurer',
        ae='Entry sales',effectiveDate='2020-01-01',expiryDate='2020-12-31',rule='ordinary',cedantDays=90,reinsurerDays=90,share=25,
        kind='premium',amounts=dict(premium=100,commission=0,tax=0,brokerage=5,claim=0,cedantNet=100,reinsurerNet=95))
    base.update(data)
    return LegacyTransaction.objects.create(number='F-'+reference,reference=reference,historical=True,status='confirmed',
        currency=currency,data=base,first_confirmed_at=timezone.now())
source=make_source('OLD-REF')
history=json.dumps(source.data,sort_keys=True);cases=Case.objects.count()

def create(kind='endorsement',role='sales',src=None):
    code,t=send(clients[role],dict(referenceTransaction=str((src or source).pk),kind=kind),method='POST')
    check('create '+kind+' draft',code==201,t)
    check('draft has no final number',t['number'] is None)
    return t

def save(t,data):
    code,t=send(clients['sales'],dict(id=t['uid'],version=t['version'],action='save',data=data))
    check('save draft',code==200,t);return t

def confirm(t,want=200):
    code,value=send(clients['sales'],dict(id=t['uid'],version=t['version'],action='confirm'))
    check('confirm expected '+str(want),code==want,value)
    return value

for role in ('accounting','accounting_manager','president','legacy_supervisor','viewer'):
    code,r=send(clients[role],dict(referenceTransaction=str(source.pk),kind='claim'),method='POST')
    check(role+' cannot create',code==403,r)
for action in ('save','confirm','correct','void'):
    code,r=send(clients['admin'],dict(id=str(source.pk),version=1,action=action,data={}))
    check('historical '+action+' denied',code==403,r)
t=create();code,r=send(clients['admin'],dict(id=t['uid'],version=t['version'],action='save',data={'remark':'other owner'}))
check('another business user cannot edit owner draft',code==403,r)
confirm(t,400)
for locked in ({'reference':'ANOTHER-OLD-REF'},{'party':'Other reinsurer'},{'cedant':'Other cedant'},{'currency':'USD'},{'share':50},{'revenueMonth':'2026-11'},{'rule':'swiss'}):
    code,r=send(clients['sales'],dict(id=t['uid'],version=t['version'],action='save',data=locked))
    check('endorsement keeps source '+next(iter(locked)),code==400 and 'cannot be changed' in r.get('message',''),r)
check('draft keeps source linkage',t['reference']=='OLD-REF' and t['referenceTransaction']==str(source.pk),t)
t=save(t,dict(gross=1000,commissionRate=15,taxRate=1,brokerage=10,endorsementNo='E01',effectiveDate='2020-06-01',oldReason='late_entry'))
code,r=send(clients['sales'],dict(id=t['uid'],version=t['version']-1,action='confirm'))
check('stale version rejected',code==409,r)
t=confirm(t);check('number uses confirmation year',t['number'].startswith('LTX-'+str(timezone.localdate().year)+'-'))
check('Revenue Month is automatic (later of effective and confirmation month)',t['revenueMonth']==timezone.localdate().strftime('%Y-%m'),t['revenueMonth'])
a=t['data']['amounts'];check('step-rounded endorsement amounts',a['premium']==250 and a['commission']==38 and a['tax']==3 and a['cedantNet']==209 and a['reinsurerNet']==199,a)
for bad in (dict(effectiveDate='2021-01-01'),dict(endorsementNo=''),dict(endorsementNo='e01'),dict(claim=50),dict(expiryDate='2028-01-01'),
            dict(gross=100.5),dict(gross=0,brokerage=0),dict(effectiveDate='2020-03-01')):
    d=create();d=save(d,dict(gross=100,commissionRate=0,taxRate=0,brokerage=1,endorsementNo='E2',effectiveDate='2020-07-01',oldReason='late_entry'))
    d=save(d,bad);confirm(d,400)
for claim in (50000,-5000):
    d=create('claim');d=save(d,dict(lossDate='2020-03-01',lossNo='LOSS-1',claim=claim,claimReason='Return overpayment' if claim<0 else ''))
    d=confirm(d);check('claim has no performance',d['performance']=={} and d['revenueMonth']=='',d)
    check('equal signed claim obligations',d['data']['amounts']['cedantNet']==-claim and d['data']['amounts']['reinsurerNet']==-claim,d)
for bad in (dict(lossDate=''),dict(lossDate='2019-12-31'),dict(lossDate='2021-01-01'),dict(claim=0),dict(claim=-1,claimReason=''),dict(lossNo=''),dict(claim=100.5)):
    d=create('claim');d=save(d,dict(lossDate='2020-03-01',lossNo='LOSS-1',claim=100));d=save(d,bad);confirm(d,400)
for bad in (dict(revenueMonth='2026-11'),dict(brokerage=1),dict(insured='Renamed'),dict(effectiveDate='2020-02-01'),dict(currency='USD')):
    d=create('claim');code,r=send(clients['sales'],dict(id=d['uid'],version=d['version'],action='save',data=bad))
    check('claim keeps source '+next(iter(bad)),code==400 and 'cannot be changed' in r.get('message',''),r)
source.refresh_from_db();check('history preserved',json.dumps(source.data,sort_keys=True)==history)
check('standalone entries never create Cases',Case.objects.count()==cases)
check('entry audit exists',LegacyAudit.objects.filter(action='transaction_confirmed').count()==3)
# Retraction has no financial side effects; reconfirmation retains the first number/year.
first=LegacyTransaction.objects.get(pk=t['uid']);original_number=first.number;first_stamp=first.first_confirmed_at
code,retracted=send(clients['sales'],dict(id=t['uid'],version=first.version,action='retract'))
check('owner can retract an untouched transaction',code==200 and retracted['status']=='draft',retracted)
from unittest.mock import patch
with patch('legacy.entries.timezone',wraps=timezone) as clock:
    clock.now.return_value=timezone.now().replace(year=timezone.now().year+1)
    restored=confirm(retracted)
first.refresh_from_db()
check('cross-year reconfirm keeps number and first confirmation',first.number==original_number and first.first_confirmed_at==first_stamp)
# Administrator-only reason maintenance remains audited and has no delete endpoint.
for role in ('sales','accounting','legacy_supervisor'):
    r=clients[role].post('/api/legacy/options',json.dumps(dict(code='qa_reason',label='QA reason',active=True)),content_type='application/json')
    check(role+' cannot maintain reason list',r.status_code==403)
r=clients['admin'].post('/api/legacy/options',json.dumps(dict(code='qa_reason',label='QA reason',active=True)),content_type='application/json')
check('administrator can maintain reasons',r.status_code==200,r.content)
check('reason changes append permanent audit',LegacyAudit.objects.filter(entity='reason:qa_reason',action='reason_saved').count()==1)
handoff=create()
def transfer_body(**kw):
    return dict(id=handoff['uid'],version=handoff['version'],action='transfer',ownerId=people['general_manager'].pk,reason='Owner departed',**kw)
code,value=send(clients['admin'],transfer_body())
check('administrator cannot take over an eligible owners draft',code==403,value)
Personnel.objects.filter(pk=people['sales'].pk).update(is_active=False,deactivated_by='qa',deactivated_at=timezone.now())
body=transfer_body();body['reason']='';code,value=send(clients['admin'],body)
check('transfer requires a reason',code==400,value)
body=transfer_body();body['ownerId']=people['accounting'].pk;code,value=send(clients['admin'],body)
check('transfer rejects a Finance-only recipient',code==400,value)
code,transferred=send(clients['admin'],transfer_body())
check('departed owner draft can be transferred',code==200 and transferred['ownerId']==people['general_manager'].pk,transferred)
code,edited=send(clients['general_manager'],dict(id=transferred['uid'],version=transferred['version'],action='save',data={'remark':'New owner edit'}))
check('new owner may edit transferred draft',code==200,edited)
check('transfer retains original creator',LegacyTransaction.objects.get(pk=handoff['uid']).created_by_id==people['sales'].pk)
Personnel.objects.filter(pk=people['sales'].pk).update(is_active=True,deactivated_by=None,deactivated_at=None)
print(f'{len(checks)}/{len(checks)} passed')
