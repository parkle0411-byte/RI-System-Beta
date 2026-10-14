"""Swiss Facility Property integration; disposable QA only, all writes rolled back."""
import copy
import json
import os
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.models import Case
from cases.calc.payment_terms import build_payment_schedule, _as_utc
from cases.calc.swiss_facility import SWISS_NAME
from cases.draft import normalize_draft
from cases.resolve import payment_terms_signature
from cases.workflow import build_renewal_payload, build_endorsement_payload
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks=[]
def check(name, condition):
    assert condition, name
    checks.append(name)
    print('PASS '+name)

def fixture(base='2026-01-31', premium=1000):
    p={'classOfBusiness':'Property','currency':'TWD','reinsured':'ZZ Swiss Cedant','policyFrom':base,
       'paymentTermsDays':90,'originalPremium':premium,'riCommPct':0,'taxPct':0,
       'reinsurers':[{'name':SWISS_NAME,'sharePct':100,'premium':premium,'riCommPct':0,'taxPct':0}],
       'paymentEntries':[],'transactions':[],'originalInsured':'ZZ Swiss Original','originalInsuredCn':'測試Swiss被保險人'}
    p['transactions']=[{'txNo':'t'+str(i),'legType':'Leg '+str(i),'amount':premium if i<3 else 0,'reinsurerIdx':0,
                        'reinsurer':SWISS_NAME,'partyName':SWISS_NAME if i==2 else 'ZZ Swiss Cedant'} for i in [1,2,3]]
    return p

def make_case(ref,payload=None,parent=None):
    return Case.objects.create(tw_ref=ref,status='posted',payload=payload or fixture(),currency='TWD',
        parent_case=parent,case_kind='endorsement' if parent else 'original',
        reinsured_name_snapshot='ZZ Swiss Cedant',announced_at=_as_utc((payload or {}).get('endorsementAnnouncedAt') or '2026-04-01T00:00:00Z'),created_by='qa',updated_by='qa')

def client_for(tag,role='accounting',dept='finance'):
    user=get_user_model().objects.create_user(username='zz.swiss.'+tag,password='Swiss-QA-Password-9!')
    Personnel.objects.create(name='ZZ Swiss '+tag,department=dept,role_code=role,auth_user_id=str(user.pk),account_status='active',created_by='qa',updated_by='qa')
    client=Client(HTTP_HOST='localhost');client.force_login(user);return client

def post(client,case,action,**extra):
    case.refresh_from_db()
    body={'action':action,'caseUid':str(case.case_uid),'rowVersion':case.row_version,**extra}
    response=client.post('/api/accounting',json.dumps(body),content_type='application/json')
    case.refresh_from_db();return response

def receipt(client,case,key,value=1000,day='2026-04-20'):
    return post(client,case,'record_payment',scheduleKey=key,amount=value,paymentDate=day)

def confirm(client,case,key='case-effective-date:cedant',**extra):
    return post(client,case,'confirm_swiss_collection',scheduleKey=key,**extra)

def offset(client,original,refund,party='cedant'):
    original.refresh_from_db();refund.refresh_from_db()
    key='case-effective-date:'+('cedant' if party=='cedant' else 'reinsurer:r1')
    body={'action':'record_swiss_offset','originalCaseUid':str(original.case_uid),'refundCaseUid':str(refund.case_uid),
          'originalRowVersion':original.row_version,'refundRowVersion':refund.row_version,'originalKey':key,'refundKey':key,
          'amount':abs(next(i for i in build_payment_schedule(refund.payload)['items'] if i['scheduleKey']==key)['outstanding']),
          'paymentDate':'2026-04-20'}
    response=client.post('/api/accounting',json.dumps(body),content_type='application/json')
    original.refresh_from_db();refund.refresh_from_db()
    if response.status_code != 200: print('OFFSET RESULT',response.status_code,response.json())
    return response

class Rollback(Exception):pass
try:
    with transaction.atomic():
        stamp=datetime(2026,4,20,2,tzinfo=dt_timezone.utc)
        clock=lambda value=None:stamp if value is None else _as_utc(value)
        with patch('cases.calc.payment_terms._as_utc',side_effect=clock),patch('cases.cash_ledger._as_utc',side_effect=clock),patch('cases.accounting_views._iso_now',return_value='2026-04-20T02:00:00.000Z'):
            finance=client_for('finance');readonly=client_for('readonly','president','board_of_directors')
            original=make_case('ZZ-SWISS-ORIGINAL')
            ckey='case-effective-date:cedant';rkey='case-effective-date:reinsurer:r1'
            response=finance.get('/api/accounting');body=response.json()
            check('Swiss schedule and original/projected dates are available before any payment',response.status_code==200 and any(r['caseUid']==str(original.case_uid) and r.get('originalDueDate')=='2026-05-14' for r in body['swissRows']))
            check('Swiss full payment is blocked until the entire Cedant receivable is confirmed',receipt(finance,original,rkey).status_code==400)
            check('manual confirmation is blocked before ledger clearance',confirm(finance,original).status_code==400)
            check('readonly role cannot confirm collected',confirm(readonly,original).status_code==403)
            check('partial incoming insurer receipt is supported',receipt(finance,original,ckey,990).status_code==200)
            check('short receipt cannot be confirmed without a clearance entry',confirm(finance,original).status_code==400)
            check('clearance requires a reason',post(finance,original,'record_swiss_clearance',scheduleKey=ckey,amount=10,clearingType='bank_fee').status_code==400)
            check('bank fee clears the ledger without inventing bank cash',post(finance,original,'record_swiss_clearance',scheduleKey=ckey,amount=10,clearingType='bank_fee',note='Recorded bank fee').status_code==200)
            check('ledger zero does not automatically create a collection confirmation',not build_payment_schedule(original.payload)['items'][1]['paymentAllowed'])
            check('confirmation date cannot be supplied or backdated',confirm(finance,original,confirmationDate='2026-01-01').status_code==400)
            check('accountant can manually confirm the cleared receivable',confirm(finance,original).status_code==200)
            check('system records actual confirmation timestamp and source',original.payload['swissAccounting']['confirmations'][ckey]['confirmedAt']=='2026-04-20T02:00:00.000Z' and original.payload['swissAccounting']['confirmations'][ckey]['source']=='manual')
            check('legacy payment endpoint rejects planned partial Swiss payments',receipt(finance,original,rkey,400).status_code==400)
            original.refresh_from_db()
            partial={'action':'record_transaction_payments','amount':400,'paymentDate':'2026-05-14','allocations':[{'caseUid':str(original.case_uid),'txNo':'t2','rowVersion':original.row_version,'amount':400}]}
            check('transaction allocation endpoint cannot bypass the full Swiss payment rule',finance.post('/api/accounting',json.dumps(partial),content_type='application/json').status_code==400)
            before=copy.deepcopy(original.payload)
            check('full Swiss payment is recorded',receipt(finance,original,rkey,1000,'2026-05-14').status_code==200)
            paid=original.payload['paymentEntries'][-1]
            check('Swiss payment preserves its original settlement period',paid['settlementDueDate']=='2026-05-14')
            check('bank return preserves original and adds a reversal',post(finance,original,'reverse_payment',entryId=paid['id'],paymentDate='2026-05-16',note='Bank returned remittance').status_code==200 and original.payload['paymentEntries'][-2]==paid)
            with patch('cases.calc.payment_terms._as_utc',side_effect=lambda v=None:datetime(2026,5,16,tzinfo=dt_timezone.utc) if v is None else _as_utc(v)):
                restored=build_payment_schedule(original.payload)['items'][1]
                check('bank return restores original payable and overdue date',restored['outstanding']==1000 and restored['dueDate']=='2026-05-14' and restored['status']=='overdue')
            # A returned incoming receipt always cancels collected confirmation.
            incoming=original.payload['paymentEntries'][0]
            check('reversal of incoming premium cancels confirmation',post(finance,original,'reverse_payment',entryId=incoming['id'],paymentDate='2026-04-21').status_code==200 and not original.payload['swissAccounting']['confirmations'][ckey]['confirmed'])
            check('reconfirmation is blocked until the changed receivable is cleared again',confirm(finance,original).status_code==400)

            # Net receipts and reinsurance net payments remain separately recorded.
            net=make_case('ZZ-SWISS-NET')
            refund_payload=fixture(premium=-200);refund_payload.update(parentTwRef=net.tw_ref,endoEffectiveDate='2026-04-01',endorsementAnnouncedAt='2026-04-01T01:00:00Z')
            returned=make_case('ZZ-SWISS-NET-E1',refund_payload,net)
            check('net insurer cash can be recorded without pretending it was the gross receipt',receipt(finance,net,ckey,800).status_code==200)
            # 2026-10-14: a Cedant refund (including by offset) is released only after every Reinsurer refund is confirmed collected.
            blocked=offset(finance,net,returned)
            check('insurer offset is blocked until the Swiss refund is collected and confirmed',blocked.status_code==400 and blocked.json()['error']=='refund_collection_required')
            check('Swiss refund is collected in cash',receipt(finance,returned,rkey,200,'2026-04-20').status_code==200)
            check('collected Swiss refund is confirmed',confirm(finance,returned,rkey).status_code==200)
            check('same-policy same-period insurer offset clears the full refund',offset(finance,net,returned).status_code==200)
            check('both offset sides retain their linked original amounts',net.payload['paymentEntries'][-1]['offsetId']==returned.payload['paymentEntries'][-1]['offsetId'] and returned.payload['paymentEntries'][-1]['amount']==-200)
            check('net receipt plus full refund offset can be manually confirmed',confirm(finance,net).status_code==200)
            # Swiss-side netting needs the Cedant premium collected in full and the Swiss refund still outstanding.
            net2=make_case('ZZ-SWISS-NET2')
            returned2=make_case('ZZ-SWISS-NET2-E1',{**copy.deepcopy(refund_payload),'parentTwRef':net2.tw_ref},net2)
            check('Cedant premium of the second policy is received in full',receipt(finance,net2,ckey,1000).status_code==200)
            check('Cedant premium of the second policy is confirmed',confirm(finance,net2).status_code==200)
            check('Swiss same-policy same-period offset is supported',offset(finance,net2,returned2,'reinsurer').status_code==200)
            check('remaining Swiss payable is paid once in full',receipt(finance,net2,rkey,800,'2026-05-14').status_code==200)
            check('offset does not rewrite original premium and refund principal',net2.payload['originalPremium']==1000 and returned2.payload['originalPremium']==-200)
            check('offset Swiss refund requires separate manual confirmation',not build_payment_schedule(returned2.payload)['items'][1]['collectionConfirmed'] and confirm(finance,returned2,rkey).status_code==200)
            alien=make_case('ZZ-SWISS-ALIEN')
            fresh=make_case('ZZ-SWISS-NET-E2',copy.deepcopy(refund_payload),net)
            untouched=(copy.deepcopy(alien.payload),copy.deepcopy(fresh.payload),alien.row_version,fresh.row_version)
            rejected=offset(finance,alien,fresh)
            check('different original policies cannot share a net offset',rejected.status_code==400 and rejected.json()['error']=='same_policy_required')
            check('rejected multi-case offset changes neither ledger nor version',untouched==(alien.payload,fresh.payload,alien.row_version,fresh.row_version))
            cross_payload=fixture(premium=-100);cross_payload.update(parentTwRef=alien.tw_ref,endoEffectiveDate='2026-05-05',endorsementAnnouncedAt='2026-05-05T01:00:00Z')
            cross=make_case('ZZ-SWISS-CROSS',cross_payload,alien)
            check('cross-period original and refund cannot be offset',offset(finance,alien,cross).status_code==400)
            check('insurer cash refund is blocked until all reinsurers confirm refunds',receipt(finance,cross,ckey,100,'2026-04-20').status_code==400)
            check('partial Swiss incoming refund is allowed',receipt(finance,cross,rkey,50,'2026-04-20').status_code==200)
            check('partial refund is not confirmable',confirm(finance,cross,rkey).status_code==400)
            check('final refund receipt can be recorded',receipt(finance,cross,rkey,50,'2026-04-21').status_code==200)
            check('refund receipt requires actual manual confirmation',confirm(finance,cross,rkey).status_code==200)
            check('confirmed Swiss refund permits early full insurer refund',receipt(finance,cross,ckey,100,'2026-04-22').status_code==200)
            multi_payload=fixture(premium=-200);multi_payload.update(parentTwRef=alien.tw_ref,endoEffectiveDate='2026-04-01',endorsementAnnouncedAt='2026-04-01T01:00:00Z')
            multi_payload['reinsurers'][0].update(sharePct=50,premium=-200)
            multi_payload['reinsurers'].append({'name':'ZZ Other Reinsurer','sharePct':50,'premium':-200,'riCommPct':0,'taxPct':0})
            multi=make_case('ZZ-SWISS-MULTI',multi_payload,alien)
            receipt(finance,multi,rkey,100);confirm(finance,multi,rkey)
            check('Swiss confirmed alone does not authorize a mixed-reinsurer insurer refund',receipt(finance,multi,ckey,200).status_code==400)
            other='case-effective-date:reinsurer:r2';receipt(finance,multi,other,100)
            check('other reinsurer cash also requires manual confirmation',receipt(finance,multi,ckey,200).status_code==400)
            check('all reinsurer confirmations authorize one full insurer refund',confirm(finance,multi,other).status_code==200 and receipt(finance,multi,ckey,200).status_code==200)
            # Re-submitting a stale confirmation must not overwrite an updated receipt.
            stale={'action':'confirm_swiss_collection','caseUid':str(multi.case_uid),'rowVersion':1,'scheduleKey':other}
            check('stale confirmation versions are rejected',finance.post('/api/accounting',json.dumps(stale),content_type='application/json').status_code==409)


            # Statement reference records a period; late confirmation prompts manual revision.
            late=make_case('ZZ-SWISS-LATE')
            check('accountant records the prepared statement period',post(finance,late,'mark_swiss_statement',scheduleKey=rkey,reference='SWISS-2026-05').status_code==200)
            with patch('cases.calc.payment_terms._as_utc',side_effect=lambda v=None:datetime(2026,5,2,tzinfo=dt_timezone.utc) if v is None else _as_utc(v)),patch('cases.accounting_views._iso_now',return_value='2026-05-02T02:00:00.000Z'):
                receipt(finance,late,ckey,1000,'2026-04-30');confirm(finance,late)
                item=build_payment_schedule(late.payload)['items'][1]
                check('late confirmation changes period and flags the prepared statement',item['dueDate']=='2026-08-14' and item['statementNeedsRevision'])
                moved_payload=copy.deepcopy(late.payload)
                check('unrevised statement blocks payment',receipt(finance,late,rkey).status_code==400)
                check('manual statement revision records the new period',post(finance,late,'mark_swiss_statement',scheduleKey=rkey,reference='SWISS-2026-08-REVISED').status_code==200)
                check('revised statement permits payment',receipt(finance,late,rkey).status_code==200)

            # Combined outgoing bank remittance fully clears each individual Swiss payable.
            batch_cases=[make_case('ZZ-SWISS-BATCH-'+str(i)) for i in [1,2]]
            for case in batch_cases:receipt(finance,case,ckey);confirm(finance,case)
            combined={'action':'record_transaction_payments','paymentDate':'2026-05-14','amount':2000,
                      'allocations':[{'caseUid':str(c.case_uid),'txNo':'t2','rowVersion':c.row_version,'amount':1000} for c in batch_cases]}
            response=finance.post('/api/accounting',json.dumps(combined),content_type='application/json')
            check('different-case Swiss payables can share one full-allocation remittance',response.status_code==200)
            batch_id=response.json()['batchId']
            for c in batch_cases:c.refresh_from_db()
            check('both batch allocations store their Swiss settlement period',all(c.payload['paymentEntries'][-1]['settlementDueDate']=='2026-05-14' for c in batch_cases))
            reversal={'action':'reverse_batch_payment','batchId':batch_id,'paymentDate':'2026-05-16',
                      'cases':[{'caseUid':str(c.case_uid),'rowVersion':c.row_version} for c in batch_cases]}
            check('complete bank-return batch preserves all original allocations',finance.post('/api/accounting',json.dumps(reversal),content_type='application/json').status_code==200)
            for c in batch_cases:c.refresh_from_db()
            check('both returned payable balances restore their original period',all(build_payment_schedule(c.payload)['items'][1]['dueDate']=='2026-05-14' and build_payment_schedule(c.payload)['items'][1]['outstanding']==1000 for c in batch_cases))

            raw=fixture();raw['swissAccounting']={'confirmations':{ckey:{'confirmed':True}}}
            normalized=normalize_draft(raw)
            check('case normalization does not accept forged accounting confirmation',not normalized['value'].get('swissAccounting'))
            legacy=copy.deepcopy(raw);legacy['paymentTermsDays']=30;legacy['reinsurers'][0]['paymentTermsDays']=180
            canonical=normalize_draft(legacy)['value']
            check('fixed Swiss terms do not falsely trigger old-case Announce locks',payment_terms_signature(legacy)==payment_terms_signature(canonical))
            mixed=fixture(premium=-100);mixed.update(parentTwRef='ROOT',endoEffectiveDate='2026-04-01');mixed['reinsurers'][0]['premium']=100
            check('mixed-direction Swiss endorsements are rejected',any('cannot mix' in e for e in normalize_draft(mixed,allow_negative_premiums=True)['errors']))
            check('endorsements and renewals do not inherit Swiss collected state',not build_endorsement_payload(raw,'ROOT',0)['swissAccounting'] and not build_renewal_payload(raw,'ROOT')['swissAccounting'])
            pending=make_case('ZZ-SWISS-PENDING');receipt(finance,pending,ckey)
            moved=make_case('ZZ-SWISS-MOVED',moved_payload)
            response=finance.get('/api/accounting');result=response.json()
            check('collection controls and fee/offset metadata are returned to Accounting',any(r.get('nonCashPaid') for r in result['transactionRows']) and any(r.get('requiresCollectionConfirmation') for r in result['swissRows']))
            view=readonly.get('/api/accounting').json()
            check('readonly Accounting receives dates but has no write authority',view['scope']['canEdit'] is False)
            if os.environ.get('SWISS_EXPORT_FIXTURE'):
                uids={str(c.case_uid) for c in [original,net,returned,alien,cross,late,pending,moved,*batch_cases]}
                for field in ['rows','transactionRows','swissRows']:result[field]=[r for r in result[field] if r['caseUid'] in uids]
                result['cashBatches']=[b for b in result['cashBatches'] if any(a['caseUid'] in uids for a in b['allocations'])]
                Path(os.environ['SWISS_EXPORT_FIXTURE']).write_text(json.dumps(result,ensure_ascii=False))
            raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back')
