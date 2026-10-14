"""Synthetic API checks for consolidated SoA rows; run only in disposable QA."""
import copy
import json
import os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)
    print('PASS ' + name)

def fixture():
    payload = {
        'currency': 'USD', 'statementNo': 'SOA-001', 'reinsured': 'QA Cedant',
        'originalInsured': 'QA Original Insured', 'originalInsuredCn': '測試原被保險人',
        'policyFrom': '2026-09-01', 'paymentTermsDays': 30,
        'originalPremium': 1000, 'riCommPct': 10, 'taxPct': 0,
        'reinsurers': [{'name': 'QA Reinsurer', 'sharePct': 100, 'premium': 800,
                       'riCommPct': 10, 'taxPct': 0, 'settlementRef': 'RI-777'}],
        'installmentEnabled': True,
        'performanceInstallments': [
            {'id': 'i1', 'performanceMonth': '2026-09', 'premium': 500, 'paymentBaseDate': '2026-09-01'},
            {'id': 'i2', 'performanceMonth': '2026-10', 'premium': 500, 'paymentBaseDate': '2026-10-01'},
        ],
        'paymentEntries': [
            {'id': 'paid-cedant', 'entryType': 'payment', 'scheduleKey': 'i1:cedant', 'amount': 450, 'paymentDate': '2026-09-20'},
            {'id': 'paid-reinsurer', 'entryType': 'payment', 'scheduleKey': 'i1:reinsurer:r1', 'amount': 100, 'paymentDate': '2026-09-20'},
        ],
    }
    txs = []
    for installment in [1, 2]:
        for leg, amount in [(1, 450), (2, 360), (3, 90)]:
            txs.append({'txNo': f'TW-QA-R1-TX{leg}-I{installment}', 'legType': f'Leg {leg}',
                        'reinsurerIdx': 0, 'reinsurer': 'QA Reinsurer', 'amount': amount,
                        'installmentId': f'i{installment}', 'installmentLabel': f'2026-{8+installment:02}',
                        'label': 'QA premium recipient', 'settlement': 'settled'})
    txs += [
        {'txNo': 'TW-QA-CLM1-TX1', 'source': 'claim', 'legType': 'Claim Leg 1',
         'reinsurerIdx': 0, 'reinsurer': 'QA Reinsurer', 'amount': -50, 'settlement': 'settled'},
        {'txNo': 'TW-QA-CLM1-TX2', 'source': 'claim', 'legType': 'Claim Leg 2', 'amount': -50, 'settlement': 'open'},
        {**txs[0], 'txNo': 'TW-QA-R1-TX1-I1-REV', 'amount': -450, 'isReversalEntry': True},
        None,
    ]
    payload['transactions'] = txs
    return payload

def make_case(ref, status='posted', **kwargs):
    return Case.objects.create(tw_ref=ref, status=status, payload=fixture(), currency='USD',
                               reinsured_name_snapshot='QA Cedant', announced_at=timezone.now(),
                               created_by='qa', updated_by='qa', **kwargs)

def make_client(tag, role='accounting', dept='finance'):
    user = get_user_model().objects.create_user(username='zz.soa.' + tag, password='Soa-QA-Password-9!')
    Personnel.objects.create(name='ZZ SoA ' + tag, department=dept, role_code=role,
        auth_user_id=str(user.pk), account_status='active', created_by='qa', updated_by='qa')
    client = Client(HTTP_HOST='localhost')
    client.force_login(user)
    return client

class Rollback(Exception): pass
try:
    with transaction.atomic():
        client = make_client('api')
        posted = make_case('TW-QA')
        reversed_case = make_case('TW-REV', 'reversed')
        payload = copy.deepcopy(reversed_case.payload)
        for tx in payload['transactions']:
            if isinstance(tx, dict) and not tx.get('isReversalEntry'):
                tx['reversed'] = True
        reversed_case.payload = payload
        reversed_case.save()
        excluded = [make_case('TW-DRAFT', 'draft'), make_case('TW-ARCHIVED', 'archived', is_archived=True, archived_at=timezone.now(), archived_by='qa'),
                    make_case('TW-RECYCLE', 'draft', recycled_at=timezone.now())]
        no_transactions = make_case('TW-NO-TX')
        no_transactions.payload = {**fixture(), 'transactions': []}
        no_transactions.save()
        before = (copy.deepcopy(posted.payload), posted.row_version, AuditLog.objects.count(), EntitySnapshot.objects.count())
        response = client.get('/api/accounting')
        check('finance can read the consolidated SoA with no-store', response.status_code == 200 and response['Cache-Control'] == 'no-store, max-age=0')
        body = response.json()
        rows = [row for row in body['transactionRows'] if row['caseUid'] == str(posted.case_uid)]
        check('all stored premium, claim and reversal entries are returned; null is skipped', len(rows) == 9)
        check('every premium, claim and reversal row identifies the original insured in both languages', all(row['originalInsured'] == 'QA Original Insured' and row['originalInsuredCn'] == '測試原被保險人' for row in rows))
        by_tx = {row['txNo']: row for row in rows}
        check('SoA number and reference are separate from transaction number', all(row['statementNo'] == 'SOA-001' for row in rows) and by_tx['TW-QA-R1-TX1-I1']['reconciliationRef'] == 'SOA-001')
        check('reinsurer-facing legs use the settlement reference', by_tx['TW-QA-R1-TX2-I1']['reconciliationRef'] == 'RI-777' and by_tx['TW-QA-CLM1-TX1']['reconciliationRef'] == 'RI-777')
        check('cedant-facing claims use the SoA reference; Leg 3 has none', by_tx['TW-QA-CLM1-TX2']['reconciliationRef'] == 'SOA-001' and by_tx['TW-QA-R1-TX3-I1']['reconciliationRef'] == '')
        check('settlement follows payments for the corresponding installment, not stale transaction flags', by_tx['TW-QA-R1-TX1-I1']['settlement'] == 'settled' and by_tx['TW-QA-R1-TX1-I2']['settlement'] == 'open')
        check('partial premium cash and automatic brokerage settlement', by_tx['TW-QA-R1-TX2-I1']['settlement'] == 'partial' and by_tx['TW-QA-R1-TX3-I1']['settlement'] == 'partial')
        check('negative claim amounts and claim settlement are preserved', by_tx['TW-QA-CLM1-TX1']['amount'] == -50 and by_tx['TW-QA-CLM1-TX1']['settlement'] == 'settled' and by_tx['TW-QA-CLM1-TX2']['settlement'] == 'open')
        check('reversal entry retains its number, flag and signed amount', by_tx['TW-QA-R1-TX1-I1-REV']['isReversalEntry'] and by_tx['TW-QA-R1-TX1-I1-REV']['amount'] == -450)
        check('reversed case history remains visible for reconciliation', any(row['caseUid'] == str(reversed_case.case_uid) and row.get('reversed') for row in body['transactionRows']))
        excluded_uids = {str(case.case_uid) for case in excluded + [no_transactions]}
        check('Draft, archived, recycled and not-yet-generated transactions are not fabricated', not any(row['caseUid'] in excluded_uids for row in body['transactionRows']))
        check('existing payment schedule does not include reversed cases', not any(row['caseUid'] == str(reversed_case.case_uid) for row in body['rows']))
        check('keys stay unique across cases and reversal history', len({row['key'] for row in body['transactionRows']}) == len(body['transactionRows']))
        posted.refresh_from_db()
        check('GET does not alter payload, version, audit or snapshots', before == (posted.payload, posted.row_version, AuditLog.objects.count(), EntitySnapshot.objects.count()))
        viewer = make_client('viewer', 'viewer', 'business_1')
        check('a role without accounting.read still cannot access transactions', viewer.get('/api/accounting').status_code == 403)
        check('anonymous accounting access remains denied', Client(HTTP_HOST='localhost').get('/api/accounting').status_code == 401)
        raise Rollback()
except Rollback:
    pass
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back')

if os.environ.get('RI_SOA_SEED_UI') == 'true':
    make_client('browser')
    make_case('TW-QA')
    print('Disposable browser fixtures ready')
