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
def check(name, condition):
    assert condition, name
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
        check('manual receipt supports partial cash', pay(finance, case, ckey, 400).status_code == 200)
        check('partial receipt remains partial', transaction_details(case.payload)['M-R1-T1']['settlement'] == 'partial')
        check('manual final receipt succeeds', pay(finance, case, ckey, 600).status_code == 200)
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
        check('cancel T1 settlement is a manual action', settle(finance, case, 'M-R1-T1', undo=True).status_code == 200)
        check('cancelling T1 invalidates retained-income settlement', transaction_details(case.payload)['M-R1-T3']['settlement'] != 'settled')
        check('cancelling reconciliation does not reverse bank cash', case.payload['paymentEntries'] == payments_before)
        check('T1 can be manually reconfirmed', settle(finance, case, 'M-R1-T1').status_code == 200)
        incoming = next(e for e in case.payload['paymentEntries'] if e['scheduleKey'] == ckey)
        check('cash reversal is a manual action', post(finance, case, 'reverse_payment', entryId=incoming['id'], paymentDate='2026-04-21', note='Bank return').status_code == 200)
        d = transaction_details(case.payload)
        check('reversal restores outstanding and invalidates T1 confirmation', d['M-R1-T1']['outstanding'] == 400 and d['M-R1-T1']['settlement'] != 'settled')
        check('reversal also invalidates T3 confirmation', d['M-R1-T3']['settlement'] != 'settled')
        check('principal and original payment history are preserved', [t['amount'] for t in case.payload['transactions']] == original_amounts and incoming in case.payload['paymentEntries'])
        stale = case.row_version - 1
        response = finance.post('/api/accounting', json.dumps({'action': 'confirm_facility_settlement', 'caseUid': str(case.case_uid), 'rowVersion': stale, 'txNo': 'M-R1-T1', 'note': 'stale'}), content_type='application/json')
        check('stale confirmation is rejected', response.status_code == 409)
        check('case drafts cannot inject accounting confirmation', 'facilityAccounting' not in normalize_draft({**fixture(), 'facilityAccounting': {'confirmations': {'fake': True}}})['value'])
        check('renewal does not inherit prior reconciliation', not build_renewal_payload(case.payload, 'ROOT')['facilityAccounting'])
        check('endorsement does not inherit prior reconciliation', not build_endorsement_payload(case.payload, 'ROOT', 0)['facilityAccounting'])
        ordinary = fixture('Ordinary RI')
        for item in build_payment_schedule(ordinary)['items']:
            ordinary['paymentEntries'].append({'id': item['scheduleKey'], 'entryType': 'payment', 'scheduleKey': item['scheduleKey'], 'amount': item['amount'], 'paymentDate': '2026-04-20'})
        check('ordinary non-Facility automatic cash and brokerage settlement is preserved', all(d['settlement'] == 'settled' and not d.get('manualSettlementRequired') for d in transaction_details(ordinary).values()))
        ordinary_case = make('ZZ-MANUAL-ORDINARY', ordinary)
        check('manual Facility API rejects ordinary entries', settle(finance, ordinary_case, 'M-R1-T1').status_code == 400)
        swiss = make('ZZ-MANUAL-SWISS', fixture(SWISS_NAME))
        check('Swiss cash receipt is manually recorded', pay(finance, swiss, ckey, 1000).status_code == 200)
        check('Swiss zero receipt requires an accountant action', not build_payment_schedule(swiss.payload)['items'][0]['collectionConfirmed'])
        check('Swiss manual collected confirmation succeeds', post(finance, swiss, 'confirm_swiss_collection', scheduleKey=ckey).status_code == 200)
        check('Swiss collected action settles the matching T1 transaction', transaction_details(swiss.payload)['M-R1-T1']['settlement'] == 'settled')
        check('Swiss full payment is manually recorded', pay(finance, swiss, rkey, 900).status_code == 200)
        check('Swiss full payment remains awaiting reconciliation', transaction_details(swiss.payload)['M-R1-T2']['settlement'] == 'pending_confirmation')
        check('Swiss schedule settlement is manual', post(finance, swiss, 'confirm_facility_settlement', scheduleKey=rkey, note='Swiss statement matched').status_code == 200)
        check('Swiss schedule confirmation settles the matching T2', transaction_details(swiss.payload)['M-R1-T2']['settlement'] == 'settled')
        check('Swiss T3 also requires manual settlement', transaction_details(swiss.payload)['M-R1-T3']['settlement'] == 'pending_confirmation')
        legacy = fixture(SWISS_NAME)
        for item in build_payment_schedule(legacy)['items']:
            if item['partyType'] == 'cedant':
                legacy['paymentEntries'].append({'id': 'old', 'entryType': 'payment', 'scheduleKey': item['scheduleKey'], 'amount': 1000, 'paymentDate': '2026-04-01'})
        legacy['transactions'][0].update(settlement='settled', settledAt='2026-04-01T01:00:00Z')
        check('legacy transaction status no longer auto-confirms Swiss collection', not build_payment_schedule(legacy)['items'][0]['collectionConfirmed'])
        before = copy.deepcopy(case.payload)
        for _ in range(3): transaction_details(case.payload); build_payment_schedule(case.payload)
        check('reading balances never writes confirmation or cash', case.payload == before)
        check('no automatic offsets or noncash adjustments were generated', not any(e.get('nonCash') for e in case.payload['paymentEntries']))
        raise Rollback()
except Rollback:
    print(f'{len(checks)}/{len(checks)} passed; database changes rolled back', flush=True)
