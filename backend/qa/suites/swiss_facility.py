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
def check(name, condition, extra=None):
    assert condition, (name, extra) if extra is not None else name
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

def txpay(client,case,amounts,day='2026-04-20',**extra):
    # 逐筆交易登錄（record_transaction_payments）；amounts={txNo: 金額}
    case.refresh_from_db()
    body={'action':'record_transaction_payments','paymentDate':day,'amount':round(sum(amounts.values()),2),
          'allocations':[{'caseUid':str(case.case_uid),'txNo':no,'rowVersion':case.row_version,'amount':v} for no,v in amounts.items()],**extra}
    response=client.post('/api/accounting',json.dumps(body),content_type='application/json')
    case.refresh_from_db();return response

# 2026-10-16「92 項會計規則」：Swiss 收妥與 Cedant 逐筆銷帳合一，移除另設收妥勾選（confirm_swiss_collection）；
# 原「確認收妥」改為對應交易的人工銷帳（confirm_facility_settlement）。ckey→t1（Cedant），rkey→t2（Swiss）
KEY_TX={'case-effective-date:cedant':'t1','case-effective-date:reinsurer:r1':'t2'}
def confirm(client,case,key='case-effective-date:cedant',undo=False,**extra):
    return post(client,case,'unconfirm_facility_settlement' if undo else 'confirm_facility_settlement',txNo=KEY_TX.get(key,key),note='QA Swiss reconciliation',**extra)

def statement(client,case,reference='SWISS-SOA-QA',key='case-effective-date:reinsurer:r1'):
    # 2026-10-16：Swiss 付款前必填結算清單參考號（須 Cedant 整期銷帳後才能登錄）
    return post(client,case,'mark_swiss_statement',scheduleKey=key,reference=reference)

def reverse_batch(client,cases,batch_id,day,note='Bank returned remittance'):
    for c in cases:c.refresh_from_db()
    body={'action':'reverse_batch_payment','batchId':batch_id,'paymentDate':day,'note':note,
          'cases':[{'caseUid':str(c.case_uid),'rowVersion':c.row_version} for c in cases]}
    response=client.post('/api/accounting',json.dumps(body),content_type='application/json')
    for c in cases:c.refresh_from_db()
    return response

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
            # 2026-10-16「92 項會計規則」：保費每次須登錄整筆餘額；移除另設收妥勾選及銀行手續費／短款作業
            before=copy.deepcopy(original.payload)
            check('partial incoming insurer receipt is rejected (whole balance required)',receipt(finance,original,ckey,990).status_code==400 and original.payload==before)
            response=post(finance,original,'confirm_swiss_collection',scheduleKey=ckey)
            check('separate Swiss collected action is retired',response.status_code==400 and response.json()['error']=='manual_transaction_workflow')
            response=post(finance,original,'record_swiss_clearance',scheduleKey=ckey,amount=10,clearingType='bank_fee',note='Recorded bank fee')
            check('bank fee / shortfall clearance is retired without writes',response.status_code==400 and response.json()['error']=='manual_transaction_workflow' and original.payload==before)
            check('full incoming insurer receipt is recorded',receipt(finance,original,ckey,1000).status_code==200)
            check('ledger zero does not automatically create a collection confirmation',not build_payment_schedule(original.payload)['items'][1]['paymentAllowed'])
            check('confirmation date cannot be supplied or backdated',confirm(finance,original,confirmationDate='2026-01-01').status_code==400)
            check('accountant can manually confirm the cleared receivable',confirm(finance,original).status_code==200)
            check('system records actual confirmation timestamp and source',original.payload['swissAccounting']['confirmations'][ckey]['confirmedAt']=='2026-04-20T02:00:00.000Z' and original.payload['swissAccounting']['confirmations'][ckey]['source']=='manual settlement' and build_payment_schedule(original.payload)['items'][1]['paymentAllowed'])
            check('Swiss payment requires the settlement statement reference',receipt(finance,original,rkey,1000,'2026-05-14').status_code==400)
            check('statement reference is recorded after Cedant settlement',statement(finance,original).status_code==200)
            check('legacy payment endpoint rejects planned partial Swiss payments',receipt(finance,original,rkey,400).status_code==400)
            check('transaction allocation endpoint cannot bypass the full Swiss payment rule',txpay(finance,original,{'t2':400},'2026-05-14').status_code==400)
            check('full Swiss payment is recorded',receipt(finance,original,rkey,1000,'2026-05-14').status_code==200)
            paid=original.payload['paymentEntries'][-1]
            check('Swiss payment preserves its original settlement period',paid['settlementDueDate']=='2026-05-14')
            # 銀行退匯以整筆匯款沖回（reverse_batch_payment，須填原因）；未銷帳的付款仍可沖回
            check('bank return preserves original and adds a reversal',reverse_batch(finance,[original],paid['batchId'],'2026-05-16').status_code==200 and original.payload['paymentEntries'][-2]==paid)
            with patch('cases.calc.payment_terms._as_utc',side_effect=lambda v=None:datetime(2026,5,16,tzinfo=dt_timezone.utc) if v is None else _as_utc(v)):
                restored=build_payment_schedule(original.payload)['items'][1]
                check('bank return restores original payable and overdue date',restored['outstanding']==1000 and restored['dueDate']=='2026-05-14' and restored['status']=='overdue')
            # 2026-10-16：曾銷帳金額永久鎖定、取消銷帳不解鎖金額 → 已銷帳的 Cedant 收款不可沖回；取消銷帳即取消收妥
            incoming=original.payload['paymentEntries'][0]
            response=reverse_batch(finance,[original],incoming['batchId'],'2026-04-21')
            check('settled incoming premium cannot be reversed',response.status_code==409 and response.json()['error']=='settled_amount_locked')
            check('cancelling the Cedant settlement cancels the collected confirmation',confirm(finance,original,undo=True).status_code==200 and not original.payload['swissAccounting']['confirmations'][ckey]['confirmed'] and not build_payment_schedule(original.payload)['items'][1]['paymentAllowed'])
            response=reverse_batch(finance,[original],incoming['batchId'],'2026-04-21')
            check('cancelled settlement does not unlock the previously settled receipt',response.status_code==409 and response.json()['error']=='settled_amount_locked')
            check('cleared receivable can be manually reconfirmed',confirm(finance,original).status_code==200)

            # 2026-10-16：保費整筆登錄；抵銷限同原單直接退批、同對象、同期且退批整筆抵完 → 先抵銷退費，再整筆收取淨額餘額
            net=make_case('ZZ-SWISS-NET')
            refund_payload=fixture(premium=-200);refund_payload.update(parentTwRef=net.tw_ref,endoEffectiveDate='2026-04-01',endorsementAnnouncedAt='2026-04-01T01:00:00Z')
            returned=make_case('ZZ-SWISS-NET-E1',refund_payload,net)
            check('net insurer cash cannot be recorded as a partial gross receipt',receipt(finance,net,ckey,800).status_code==400)
            # 2026-10-14: a Cedant refund (including by offset) is released only after every Reinsurer refund is confirmed collected.
            blocked=offset(finance,net,returned)
            check('insurer offset is blocked until the Swiss refund is collected and confirmed',blocked.status_code==400 and blocked.json()['error']=='refund_collection_required')
            check('Swiss refund is collected in cash',receipt(finance,returned,rkey,200,'2026-04-20').status_code==200)
            check('collected Swiss refund is confirmed',confirm(finance,returned,rkey).status_code==200)
            check('same-policy same-period insurer offset clears the full refund',offset(finance,net,returned).status_code==200)
            net_offset=next(e for e in net.payload['paymentEntries'] if e.get('offsetId'));refund_offset=next(e for e in returned.payload['paymentEntries'] if e.get('offsetId'))
            check('both offset sides retain their linked original amounts',net_offset['offsetId']==refund_offset['offsetId'] and refund_offset['amount']==-200)
            check('net insurer cash is recorded as the whole remaining balance',receipt(finance,net,ckey,800).status_code==200)
            check('net receipt plus full refund offset can be manually confirmed',confirm(finance,net).status_code==200)
            # Swiss-side netting needs the Cedant premium collected in full and the Swiss refund still outstanding.
            net2=make_case('ZZ-SWISS-NET2')
            returned2=make_case('ZZ-SWISS-NET2-E1',{**copy.deepcopy(refund_payload),'parentTwRef':net2.tw_ref},net2)
            check('Cedant premium of the second policy is received in full',receipt(finance,net2,ckey,1000).status_code==200)
            check('Cedant premium of the second policy is confirmed',confirm(finance,net2).status_code==200)
            check('Swiss same-policy same-period offset is supported',offset(finance,net2,returned2,'reinsurer').status_code==200)
            check('statement reference for the second policy is recorded',statement(finance,net2,'SWISS-SOA-NET2').status_code==200)
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
            # 2026-10-16：退費同屬保費，須整筆登錄餘額
            check('partial Swiss incoming refund is rejected (whole balance required)',receipt(finance,cross,rkey,50,'2026-04-20').status_code==400)
            check('uncollected refund is not confirmable',confirm(finance,cross,rkey).status_code==400)
            check('full refund receipt can be recorded',receipt(finance,cross,rkey,100,'2026-04-21').status_code==200)
            check('refund receipt requires actual manual confirmation',confirm(finance,cross,rkey).status_code==200)
            check('confirmed Swiss refund permits early full insurer refund',receipt(finance,cross,ckey,100,'2026-04-22').status_code==200)
            multi_payload=fixture(premium=-200);multi_payload.update(parentTwRef=alien.tw_ref,endoEffectiveDate='2026-04-01',endorsementAnnouncedAt='2026-04-01T01:00:00Z')
            multi_payload['reinsurers'][0].update(sharePct=50,premium=-100)
            # 2026-10-16：每家普通再保人天數須獨立填寫、不繼承
            multi_payload['reinsurers'].append({'name':'ZZ Other Reinsurer','sharePct':50,'premium':-100,'riCommPct':0,'taxPct':0,'paymentTermsDays':30})
            # 2026-10-16：收付逐筆交易登錄，排程不能自動分配 → 夾具為兩家再保人各建 T1／T2／T3
            items=build_payment_schedule(multi_payload)['items'];cedant_amount=next(i['amount'] for i in items if i['partyType']=='cedant')
            multi_payload['transactions']=[{'txNo':pre+str(i),'legType':'Leg '+str(i),'reinsurerIdx':idx,'reinsurer':name,
                'amount':(cedant_amount/2 if i==1 else next(x['amount'] for x in items if x['partyKey']=='r'+str(idx+1)) if i==2 else 0),
                'partyName':name if i==2 else 'ZZ Swiss Cedant'} for pre,idx,name in [('t',0,SWISS_NAME),('u',1,'ZZ Other Reinsurer')] for i in [1,2,3]]
            multi=make_case('ZZ-SWISS-MULTI',multi_payload,alien)
            details=lambda c:__import__('cases.cash_ledger',fromlist=['transaction_details']).transaction_details(c.payload)
            whole_refund=lambda:{no:abs(details(multi)[no]['outstanding']) for no in ('t1','u1')}
            check('Swiss refund collected in full',txpay(finance,multi,{'t2':abs(details(multi)['t2']['outstanding'])}).status_code==200 and confirm(finance,multi,'t2').status_code==200)
            check('Swiss confirmed alone does not authorize a mixed-reinsurer insurer refund',txpay(finance,multi,whole_refund()).status_code==400)
            check('other reinsurer refund collected in full',txpay(finance,multi,{'u2':abs(details(multi)['u2']['outstanding'])}).status_code==200)
            check('other reinsurer cash also requires manual confirmation',txpay(finance,multi,whole_refund()).status_code==400)
            check('all reinsurer confirmations authorize one full insurer refund',confirm(finance,multi,'u2').status_code==200 and txpay(finance,multi,whole_refund()).status_code==200)
            # Re-submitting a stale confirmation must not overwrite an updated receipt.
            stale={'action':'confirm_facility_settlement','caseUid':str(multi.case_uid),'rowVersion':1,'txNo':'t1','note':'stale'}
            check('stale confirmation versions are rejected',finance.post('/api/accounting',json.dumps(stale),content_type='application/json').status_code==409)


            # 2026-10-16：結算清單參考號須在 Cedant 整期銷帳後登錄，故不再有「先登錄清單、後因晚確認而需修訂」的情境；
            # 保留固定結算期：晚確認仍移到下一期，清單參考號記錄新期別，付款前必填
            late=make_case('ZZ-SWISS-LATE')
            response=statement(finance,late,'SWISS-2026-05')
            check('statement reference cannot precede Cedant settlement',response.status_code==409 and response.json()['error']=='cedant_settlement_required')
            with patch('cases.calc.payment_terms._as_utc',side_effect=lambda v=None:datetime(2026,5,2,tzinfo=dt_timezone.utc) if v is None else _as_utc(v)),patch('cases.accounting_views._iso_now',return_value='2026-05-02T02:00:00.000Z'):
                receipt(finance,late,ckey,1000,'2026-04-30');confirm(finance,late)
                item=build_payment_schedule(late.payload)['items'][1]
                check('late confirmation changes period',item['dueDate']=='2026-08-14' and item['paymentAllowed'])
                moved_payload=copy.deepcopy(late.payload)
                check('missing statement blocks payment',receipt(finance,late,rkey).status_code==400)
                check('manual statement records the new period',statement(finance,late,'SWISS-2026-08').status_code==200 and late.payload['swissAccounting']['statements'][rkey]['dueDate']=='2026-08-14')
                check('statement reference permits payment',receipt(finance,late,rkey).status_code==200)

            # Combined outgoing bank remittance fully clears each individual Swiss payable.
            batch_cases=[make_case('ZZ-SWISS-BATCH-'+str(i)) for i in [1,2]]
            for case in batch_cases:receipt(finance,case,ckey);confirm(finance,case);statement(finance,case)
            combined={'action':'record_transaction_payments','paymentDate':'2026-05-14','amount':2000,
                      'allocations':[{'caseUid':str(c.case_uid),'txNo':'t2','rowVersion':c.row_version,'amount':1000} for c in batch_cases]}
            response=finance.post('/api/accounting',json.dumps(combined),content_type='application/json')
            check('different-case Swiss payables can share one full-allocation remittance',response.status_code==200,response.content[:300])
            batch_id=response.json()['batchId']
            for c in batch_cases:c.refresh_from_db()
            check('both batch allocations store their Swiss settlement period',all(c.payload['paymentEntries'][-1]['settlementDueDate']=='2026-05-14' for c in batch_cases))
            check('complete bank-return batch preserves all original allocations',reverse_batch(finance,batch_cases,batch_id,'2026-05-16').status_code==200)
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
            # 2026-10-16 畫面用的精簡模式（?view=list）：只少了非 Swiss 案件的付款排程列，其餘完全相同
            from cases.calc.swiss_facility import applies as _swiss_applies, case_payload as _case_payload
            lean=finance.get('/api/accounting?view=list').json();_swiss={}
            def _is_swiss(uid):
                if uid not in _swiss:_swiss[uid]=_swiss_applies(_case_payload(Case.objects.get(case_uid=uid)))
                return _swiss[uid]
            check('screen list mode returns the same transactions, Swiss schedules, batches, warnings and currencies',all(lean[k]==result[k] for k in ('transactionRows','swissRows','cashBatches','warnings','currencies','scope')))
            check('screen list mode keeps every Swiss schedule row and drops only non-Swiss ones',lean['rows']==[r for r in result['rows'] if _is_swiss(r['caseUid'])] and len(lean['rows'])>0)
            if os.environ.get('SWISS_EXPORT_FIXTURE'):
                uids={str(c.case_uid) for c in [original,net,returned,alien,cross,late,pending,moved,*batch_cases]}
                for field in ['rows','transactionRows','swissRows']:result[field]=[r for r in result[field] if r['caseUid'] in uids]
                result['cashBatches']=[b for b in result['cashBatches'] if any(a['caseUid'] in uids for a in b['allocations'])]
                Path(os.environ['SWISS_EXPORT_FIXTURE']).write_text(json.dumps(result,ensure_ascii=False))
            raise Rollback()
except Rollback:pass
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back')
