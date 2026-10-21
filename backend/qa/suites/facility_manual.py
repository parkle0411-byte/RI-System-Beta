"""Manual Facility cash reconciliation, isolated database, every write rolled back."""
import copy
import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.models import Case
from cases.calc.payment_terms import build_payment_schedule
from cases.cash_ledger import transaction_details
from cases.calc.swiss_facility import SWISS_NAME
from cases.draft import normalize_draft
from cases.workflow import build_renewal_payload, build_endorsement_payload
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, condition, extra=None):
    assert condition, (name, extra) if extra is not None else name
    checks.append(name)
    print('PASS ' + name, flush=True)

def fixture(name='Lloyd\'s Underwriter Syndicate No. 0609 AUW (Facility)'):
    p = {'classOfBusiness': 'Property', 'currency': 'TWD', 'reinsured': 'Manual Cedant',
         'policyFrom': '2026-01-01', 'policyTo': '2027-01-01', 'paymentTermsDays': 90,
         'originalPremium': 1000, 'riCommPct': 0, 'taxPct': 0,
         'reinsurers': [{'name': name, 'sharePct': 100, 'premium': 900, 'riCommPct': 0, 'taxPct': 0}],
         'transactions': [], 'paymentEntries': []}
    p['transactions'] = [{'txNo': 'M-R1-T' + str(i), 'legType': 'Leg ' + str(i), 'amount': v,
                          'reinsurerIdx': 0, 'reinsurer': name,
                          'partyName': 'Manual Cedant' if i == 1 else name} for i, v in [(1, 1000), (2, 900), (3, 100)]]
    return p

def make(ref, payload=None):
    return Case.objects.create(tw_ref=ref, status='posted', currency='TWD', payload=payload or fixture(),
                               case_kind='original', reinsured_name_snapshot='Manual Cedant',
                               announced_at=datetime(2026, 1, 1, tzinfo=timezone.utc), created_by='qa', updated_by='qa')

def client(tag, role='accounting', department='finance'):
    u = get_user_model().objects.create_user(username='zz.manual.' + tag, password='Manual-QA-Pass-9!')
    Personnel.objects.create(name='Manual ' + tag, department=department, role_code=role,
                             auth_user_id=str(u.pk), account_status='active', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost'); c.force_login(u); return c

def post(c, case, action, **extra):
    case.refresh_from_db()
    response = c.post('/api/accounting', json.dumps({'action': action, 'caseUid': str(case.case_uid),
                      'rowVersion': case.row_version, **extra}), content_type='application/json')
    case.refresh_from_db()
    return response

def settle(c, case, no, undo=False, **extra):
    return post(c, case, 'unconfirm_facility_settlement' if undo else 'confirm_facility_settlement',
                txNo=no, note='Accountant checked bank and SoA', **extra)

def pay(c, case, key, value, day='2026-04-20'):
    return post(c, case, 'record_payment', scheduleKey=key, amount=value, paymentDate=day)

class Rollback(Exception): pass
try:
    with transaction.atomic():
        finance = client('finance'); readonly = client('readonly', 'president', 'board_of_directors')
        case = make('ZZ-MANUAL-AUW')
        ckey, rkey = [i['scheduleKey'] for i in build_payment_schedule(case.payload)['items']]
        original_amounts = [t['amount'] for t in case.payload['transactions']]
        check('cannot confirm a Facility receivable before cash clearance', settle(finance, case, 'M-R1-T1').status_code == 400)
        check('read-only roles cannot confirm Facility settlement', settle(readonly, case, 'M-R1-T1').status_code == 403)
        # 2026-10-16「92 項會計規則」／2026-10-20「四類會計收付」：保費每次須登錄整筆餘額，只有賠款可部分收付
        check('manual receipt rejects partial premium cash', pay(finance, case, ckey, 400).status_code == 400)
        check('rejected partial receipt leaves T1 open', transaction_details(case.payload)['M-R1-T1']['settlement'] == 'open' and not case.payload['paymentEntries'])
        check('manual full receipt succeeds', pay(finance, case, ckey, 1000).status_code == 200)
        d = transaction_details(case.payload)
        check('zero cash balance does not auto-settle Facility T1', d['M-R1-T1']['outstanding'] == 0 and d['M-R1-T1']['settlement'] == 'pending_confirmation')
        check('read-only Accounting can see pending confirmation', any(r['settlement'] == 'pending_confirmation' for r in readonly.get('/api/accounting').json()['transactionRows'] if r['caseUid'] == str(case.case_uid)))
        check('manual confirmation requires a reconciliation reason', post(finance, case, 'confirm_facility_settlement', txNo='M-R1-T1').status_code == 400)
        check('manual T1 settlement succeeds', settle(finance, case, 'M-R1-T1').status_code == 200)
        check('confirmed T1 shows settled', transaction_details(case.payload)['M-R1-T1']['settlement'] == 'settled')
        check('manual confirmation is shared with payment schedule', build_payment_schedule(case.payload)['items'][0]['settlement'] == 'settled')
        check('manual T2 payment succeeds', pay(finance, case, rkey, 900).status_code == 200)
        d = transaction_details(case.payload)
        check('unrelated T2 payment preserves confirmed T1', d['M-R1-T1']['settlement'] == 'settled')
        check('zero payable does not auto-settle T2', d['M-R1-T2']['settlement'] == 'pending_confirmation')
        check('T3 cannot settle before T2 confirmation', settle(finance, case, 'M-R1-T3').status_code == 400)
        check('manual T2 settlement succeeds', settle(finance, case, 'M-R1-T2').status_code == 200)
        d = transaction_details(case.payload)
        check('both settled cash legs do not auto-settle T3', d['M-R1-T3']['settlement'] == 'pending_confirmation' and d['M-R1-T3']['paid'] == 0)
        payments_before = copy.deepcopy(case.payload['paymentEntries'])
        check('manual T3 settlement succeeds', settle(finance, case, 'M-R1-T3').status_code == 200)
        check('T3 confirmation creates no cash remittance', case.payload['paymentEntries'] == payments_before)
        check('T3 shows settled after accountant confirmation', transaction_details(case.payload)['M-R1-T3']['settlement'] == 'settled')
        check('manual history records actor, date and reason', all(e.get('confirmedBy') and e.get('confirmedAt') and e.get('note') for e in case.payload['facilityAccounting']['history']))
        # 2026-10-16「92 項會計規則」：T3 完成後整組（T1／T2／T3）都不能取消；曾銷帳金額永久鎖定
        response = settle(finance, case, 'M-R1-T1', undo=True)
        check('T1 settlement cannot be cancelled after T3 is final', response.status_code == 409 and response.json()['error'] == 'final_settlement_locked')
        check('final group keeps retained-income settlement', transaction_details(case.payload)['M-R1-T3']['settlement'] == 'settled')
        check('rejected cancellation does not touch bank cash', case.payload['paymentEntries'] == payments_before)
        incoming = next(e for e in case.payload['paymentEntries'] if e['scheduleKey'] == ckey)
        response = finance.post('/api/accounting', json.dumps({'action': 'reverse_batch_payment', 'batchId': incoming['batchId'], 'cases': [{'caseUid': str(case.case_uid), 'rowVersion': case.row_version}], 'paymentDate': '2026-04-21', 'note': 'Bank return'}), content_type='application/json')
        case.refresh_from_db()
        check('settled cash cannot be reversed', response.status_code == 409 and response.json()['error'] == 'settled_amount_locked' and case.payload['paymentEntries'] == payments_before, response.content[:200])
        # 取消銷帳仍為人工動作（T3 未完成前）；取消銷帳不解鎖金額，也不沖回銀行現金
        second = make('ZZ-MANUAL-AUW-2')
        assert pay(finance, second, ckey, 1000).status_code == 200 and settle(finance, second, 'M-R1-T1').status_code == 200
        cash = copy.deepcopy(second.payload['paymentEntries'])
        check('cancel T1 settlement is a manual action', settle(finance, second, 'M-R1-T1', undo=True).status_code == 200)
        check('cancelling reconciliation does not reverse bank cash', second.payload['paymentEntries'] == cash and transaction_details(second.payload)['M-R1-T1']['settlement'] == 'pending_confirmation')
        batch = cash[0]['batchId']
        response = finance.post('/api/accounting', json.dumps({'action': 'reverse_batch_payment', 'batchId': batch, 'cases': [{'caseUid': str(second.case_uid), 'rowVersion': second.row_version}], 'note': 'Bank return'}), content_type='application/json')
        check('cancelling settlement does not unlock the previously settled amount', response.status_code == 409 and response.json()['error'] == 'settled_amount_locked')
        check('T1 can be manually reconfirmed', settle(finance, second, 'M-R1-T1').status_code == 200)
        # 未銷帳的收款仍可人工沖回（須填原因），餘額恢復
        third = make('ZZ-MANUAL-AUW-3')
        assert pay(finance, third, ckey, 1000).status_code == 200
        third_cash = copy.deepcopy(third.payload['paymentEntries'])
        response = finance.post('/api/accounting', json.dumps({'action': 'reverse_batch_payment', 'batchId': third_cash[0]['batchId'], 'cases': [{'caseUid': str(third.case_uid), 'rowVersion': third.row_version}], 'paymentDate': '2026-04-21', 'note': 'Bank return'}), content_type='application/json')
        check('cash reversal is a manual action', response.status_code == 200, response.content[:200])
        third.refresh_from_db(); d = transaction_details(third.payload)
        check('reversal restores outstanding and leaves T1 unsettled', d['M-R1-T1']['outstanding'] == 1000 and d['M-R1-T1']['settlement'] == 'open')
        check('principal and original payment history are preserved', [t['amount'] for t in third.payload['transactions']] == original_amounts and all(e in third.payload['paymentEntries'] for e in third_cash))
        stale = case.row_version - 1
        response = finance.post('/api/accounting', json.dumps({'action': 'confirm_facility_settlement', 'caseUid': str(case.case_uid), 'rowVersion': stale, 'txNo': 'M-R1-T1', 'note': 'stale'}), content_type='application/json')
        check('stale confirmation is rejected', response.status_code == 409)
        check('case drafts cannot inject accounting confirmation', 'facilityAccounting' not in normalize_draft({**fixture(), 'facilityAccounting': {'confirmations': {'fake': True}}})['value'])
        check('renewal does not inherit prior reconciliation', not build_renewal_payload(case.payload, 'ROOT')['facilityAccounting'])
        check('endorsement does not inherit prior reconciliation', not build_endorsement_payload(case.payload, 'ROOT', 0)['facilityAccounting'])
        ordinary = fixture('Ordinary RI')
        for item in build_payment_schedule(ordinary)['items']:
            ordinary['paymentEntries'].append({'id': item['scheduleKey'], 'entryType': 'payment', 'scheduleKey': item['scheduleKey'], 'amount': item['amount'], 'paymentDate': '2026-04-20'})
        # 2026-10-14 owner decision: no automatic settlement for any case.
        check('ordinary non-Facility cases also wait for manual settlement', all(d['manualSettlementRequired'] and d['settlement'] in ('pending_confirmation', 'open') for d in transaction_details(ordinary).values())
              and transaction_details(ordinary)['M-R1-T1']['settlement'] == 'pending_confirmation')
        ordinary_case = make('ZZ-MANUAL-ORDINARY', ordinary)
        check('ordinary entries are confirmed through the same manual action', settle(finance, ordinary_case, 'M-R1-T1').status_code == 200
              and transaction_details(Case.objects.get(pk=ordinary_case.pk).payload)['M-R1-T1']['settlement'] == 'settled')
        # 2026-10-14 owner decision: one Facility reinsurer makes every party and leg of the case manual.
        mixed = fixture()
        mixed['reinsurers'] = [{**mixed['reinsurers'][0], 'sharePct': 50, 'premium': 450},
                               {'name': 'Ordinary RI', 'sharePct': 50, 'premium': 450, 'riCommPct': 0, 'taxPct': 0}]
        mixed['transactions'] = [{**t, 'amount': t['amount'] / 2} for t in mixed['transactions']] + [
            {'txNo': 'M-R2-T' + str(i), 'legType': 'Leg ' + str(i), 'amount': v, 'reinsurerIdx': 1, 'reinsurer': 'Ordinary RI',
             'partyName': 'Manual Cedant' if i == 1 else 'Ordinary RI'} for i, v in [(1, 500), (2, 450), (3, 50)]]
        for item in build_payment_schedule(mixed)['items']:
            mixed['paymentEntries'].append({'id': 'mx-' + item['scheduleKey'], 'entryType': 'payment', 'scheduleKey': item['scheduleKey'], 'amount': item['amount'], 'paymentDate': '2026-04-20'})
        mixed_details = transaction_details(mixed)
        check('mixed case: ordinary reinsurer legs also wait for manual settlement',
              mixed_details['M-R2-T1']['settlement'] == 'pending_confirmation'
              and all(mixed_details[no]['manualSettlementRequired'] for no in ('M-R2-T1', 'M-R2-T2', 'M-R2-T3')))
        check('mixed case: every schedule party waits for manual settlement',
              all(i['settlement'] == 'pending_confirmation' for i in build_payment_schedule(mixed)['items']))
        swiss = make('ZZ-MANUAL-SWISS', fixture(SWISS_NAME))
        check('Swiss cash receipt is manually recorded', pay(finance, swiss, ckey, 1000).status_code == 200)
        check('Swiss zero receipt requires an accountant action', not build_payment_schedule(swiss.payload)['items'][0]['collectionConfirmed'])
        # 2026-10-16「92 項會計規則」：Swiss 收妥與 Cedant 逐筆銷帳合一，移除另設收妥勾選；付款前必填結算清單參考號
        response = post(finance, swiss, 'confirm_swiss_collection', scheduleKey=ckey)
        check('separate Swiss collected action is retired', response.status_code == 400 and response.json()['error'] == 'manual_transaction_workflow')
        check('Swiss T1 manual settlement succeeds', settle(finance, swiss, 'M-R1-T1').status_code == 200)
        check('Swiss T1 settlement doubles as the collection confirmation', transaction_details(swiss.payload)['M-R1-T1']['settlement'] == 'settled' and build_payment_schedule(swiss.payload)['items'][0]['collectionConfirmed'])
        check('Swiss payment requires the settlement statement reference', pay(finance, swiss, rkey, 900).status_code == 400)
        check('Swiss statement reference is recorded', post(finance, swiss, 'mark_swiss_statement', scheduleKey=rkey, reference='SWISS-SOA-QA').status_code == 200)
        check('Swiss full payment is manually recorded', pay(finance, swiss, rkey, 900).status_code == 200)
        check('Swiss full payment remains awaiting reconciliation', transaction_details(swiss.payload)['M-R1-T2']['settlement'] == 'pending_confirmation')
        # 2026-10-16：銷帳逐筆交易進行，排程層級（scheduleKey）銷帳已停用
        response = post(finance, swiss, 'confirm_facility_settlement', scheduleKey=rkey, note='Swiss statement matched')
        check('Swiss schedule-level settlement is replaced by transaction settlement', response.status_code == 400 and response.json()['error'] == 'individual_transaction_required')
        check('Swiss T2 settlement is manual', settle(finance, swiss, 'M-R1-T2').status_code == 200)
        check('Swiss transaction confirmation settles T2', transaction_details(swiss.payload)['M-R1-T2']['settlement'] == 'settled')
        check('Swiss T3 also requires manual settlement', transaction_details(swiss.payload)['M-R1-T3']['settlement'] == 'pending_confirmation')
        legacy = fixture(SWISS_NAME)
        for item in build_payment_schedule(legacy)['items']:
            if item['partyType'] == 'cedant':
                legacy['paymentEntries'].append({'id': 'old', 'entryType': 'payment', 'scheduleKey': item['scheduleKey'], 'amount': 1000, 'paymentDate': '2026-04-01'})
        legacy['transactions'][0].update(settlement='settled', settledAt='2026-04-01T01:00:00Z')
        # 2026-10-14 owner decision: keep the 10/13 rule; a verifiable historical settlement timestamp carries over with its source.
        carried = build_payment_schedule(legacy)['items'][0]
        check('legacy settled transaction carries over as Swiss collection evidence with its source', carried['collectionConfirmed'] and carried['collectionConfirmedAt'] == '2026-04-01' and carried['collectionConfirmationSource'].startswith('historical transaction reconciliation'))
        before = copy.deepcopy(case.payload)
        for _ in range(3): transaction_details(case.payload); build_payment_schedule(case.payload)
        check('reading balances never writes confirmation or cash', case.payload == before)
        check('no automatic offsets or noncash adjustments were generated', not any(e.get('nonCash') for e in case.payload['paymentEntries']))
        raise Rollback()
except Rollback:
    print(f'{len(checks)}/{len(checks)} passed; database changes rolled back', flush=True)
