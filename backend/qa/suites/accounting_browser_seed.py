"""Commit synthetic fixtures only in this task's disposable QA database."""
"""Integration regression of the owner's 92 accounting decisions; disposable DB only."""
import copy,json,os
from datetime import datetime,timedelta,timezone as dtz
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client,override_settings
from django.utils import timezone
from cases.models import Case
from personnel.models import Personnel
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from audit.models import EntitySnapshot
from fxrates.models import FxRate
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
checks=[]
def check(name,condition,extra=None):
 assert condition,(name,extra)
 checks.append(name);print('PASS '+name,flush=True)
def client(tag,role,dept):
 u=get_user_model().objects.create_user(username='ar92.'+tag,password='Accounting-Review-92!')
 p=Personnel.objects.create(name='AR92 '+tag,department=dept,role_code=role,email=tag+'@company.invalid',auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
 c=Client(HTTP_HOST='localhost');c.force_login(u);return c,p
serial=0
def make(prefix='P',**changes):
 global serial;serial+=1;ref='AR92-'+prefix+str(serial)
 p={'twRef':ref,'currency':'TWD','classOfBusiness':'Property','reinsured':'AR92 Cedant','policyFrom':'2026-01-01','policyTo':'2027-01-01','paymentTermsDays':30,'originalPremium':1000,'riCommPct':0,'taxPct':0,'reinsurers':[{'name':'AR92 RI','sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}],'paymentEntries':[]}
 status=changes.pop('status','closed');parent=changes.pop('parent',None);announced=changes.pop('announced',datetime(2026,1,1,tzinfo=dtz.utc))
 p.update(changes)
 if parent:p.update(parentTwRef=parent.tw_ref,endoEffectiveDate=p.get('endoEffectiveDate','2026-01-01'),endorsementAnnouncedAt=announced.isoformat())
 p['transactions']=build_premium_transactions(p)
 for t in p['transactions']:t.update(postedMonth='2026-01',createdAt='2026-01-01T00:00:00Z')
 return Case.objects.create(tw_ref=ref,status=status,payload=p,currency=p['currency'],parent_case=parent,case_kind='endorsement' if parent else 'original',announced_at=announced,created_by='qa',updated_by='qa')
def details(case):case.refresh_from_db();return transaction_details(case.payload)
def tx(case,leg,index=0):case.refresh_from_db();return [t['txNo'] for t in case.payload['transactions'] if t['legType']==leg][index]
def request(c,action,**body):return c.post('/api/accounting',data=json.dumps({'action':action,**body}),content_type='application/json')
def pay(c,case,leg,value,index=0,date='2026-10-01'):
 no=tx(case,leg,index);return request(c,'record_transaction_payments',paymentDate=date,amount=value,allocations=[{'caseUid':str(case.case_uid),'rowVersion':case.row_version,'txNo':no,'amount':value}])
def settle(c,case,leg,index=0,undo=False,**extra):
 no=tx(case,leg,index);return request(c,'unconfirm_facility_settlement' if undo else 'confirm_facility_settlement',caseUid=str(case.case_uid),rowVersion=case.row_version,txNo=no,note='AR92 checked',**extra)
def offset(c,root,refund,party='cedant'):
 from cases.calc.payment_terms import build_payment_schedule
 from cases.calc.swiss_facility import case_payload
 root.refresh_from_db();refund.refresh_from_db()
 a=next(i for i in build_payment_schedule(case_payload(root))['items'] if i['partyType']==party)
 b=next(i for i in build_payment_schedule(case_payload(refund))['items'] if i['partyType']==party)
 return request(c,'record_premium_offset',originalCaseUid=str(root.case_uid),refundCaseUid=str(refund.case_uid),originalRowVersion=root.row_version,refundRowVersion=refund.row_version,originalKey=a['scheduleKey'],refundKey=b['scheduleKey'],paymentDate='2026-10-01',amount=abs(b['outstanding']))

import time
serial=int(time.time())
tag=str(serial)
fin,fp=client('browserfin'+tag,'accounting','finance');sales,sp=client('browsersales'+tag,'sales','reinsurance')
a=make('UI-PREMIUM');b=make('UI-CLAIM');pending=make('UI-PENDING',paymentTermsDays=None)
p=b.payload;p['transactions']=[{'txNo':b.tw_ref+'-CL-T1','source':'claim','claimId':1,'paymentId':1,'reinsurerIdx':0,'reinsurer':'AR92 RI','legType':'Claim Leg 1','amount':1000,'dueDate':'2026-10-31','postedMonth':'2026-10','createdAt':'2026-10-16T00:00:00Z','settlement':'open'},{'txNo':b.tw_ref+'-CL-T2','source':'claim','claimId':1,'paymentId':1,'reinsurerIdx':0,'reinsurer':'AR92 RI','legType':'Claim Leg 2','amount':1000,'dueDate':'2026-10-31','postedMonth':'2026-10','createdAt':'2026-10-16T00:00:00Z','settlement':'open'}];b.payload=p;b.save()
r=make('UI-REFUND',parent=a,originalPremium=-200,reinsurers=[{'name':'AR92 RI','sharePct':100,'premium':-160,'riCommPct':0,'taxPct':0,'paymentTermsDays':30}])
swiss=make('UI-SWISS',reinsurers=[{'name':'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)','sharePct':100,'premium':800,'riCommPct':0,'taxPct':0,'paymentTermsDays':90}])
print('BROWSER_SEED '+json.dumps({'sessions':{'finance':fin.cookies['ri_sessionid'].value,'sales':sales.cookies['ri_sessionid'].value},'refs':{'premium':a.tw_ref,'claim':b.tw_ref,'pending':pending.tw_ref,'refund':r.tw_ref,'swiss':swiss.tw_ref}}))
