"""Renewal Claim snapshots synchronize without guessing or modifying accounting."""
import json, os, uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.test import Client
from cases.models import Case
from cases.claim_loss_record import renewal_claim_snapshots
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    checks.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ' ' + str(detail)))

with transaction.atomic():
    user = get_user_model().objects.create_user(username='qa.claim.sync', password='qa-Pass-123!')
    person = Personnel.objects.create(name='QA Claim Sync', department='reinsurance', role_code='sales', auth_user_id=str(user.pk), account_status='active', created_by='qa', updated_by='qa')
    client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
    client.force_login(user)
    client.get('/api/auth/csrf')
    source = Case.objects.create(case_kind='original', status='posted', tw_ref='TWPR2601001', created_by='qa', updated_by='qa', payload={
        'currency':'USD', 'claims':[{'id':1,'dateOfLoss':'2026-01-01','causeOfLoss':'Old','outstandingReserve':100,'payments':[]}],
        'transactions':[{'txNo':'T1','source':'claim','amount':50}]})
    snapshots = renewal_claim_snapshots(source.payload, source.tw_ref, source.case_uid)
    renewal = Case.objects.create(case_kind='renewal', status='draft', created_by='qa', updated_by='qa', payload={'claimLossSnapshots':snapshots})
    def post(action, **extra):
        renewal.refresh_from_db()
        body = {'caseUid':str(renewal.case_uid), 'rowVersion':renewal.row_version, 'index':0, 'action':action, **extra}
        return client.post('/api/claim-loss-snapshot', data=json.dumps(body), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    r = post('edit', updates={'date':'2026-02-01','cause':'New','lossPaid':200,'currency':'USD'}, reason='Correct date')
    source.refresh_from_db(); renewal.refresh_from_db()
    check('date and cause synchronize to source', r.status_code == 200 and source.payload['claims'][0]['dateOfLoss'] == '2026-02-01' and source.payload['claims'][0]['causeOfLoss'] == 'New', r.content[:500])
    check('money is local and original accounting remains unchanged', source.payload['claims'][0]['outstandingReserve'] == 100 and source.payload['transactions'][0]['amount'] == 50 and renewal.payload['claimLossSnapshots'][0]['lossPaid'] == 200)
    check('source histories record actor and dates', source.payload['claims'][0]['lossDateHistory'][0]['reason'] == 'Correct date' and source.payload['claims'][0]['causeHistory'][0]['changedByName'] == person.name)
    changed = source.payload; changed['claims'][0]['causeOfLoss'] = 'Third party edit'; source.payload = changed; source.row_version += 1; source.save()
    r = post('edit', updates={'cause':'Renewal edit'}); source.refresh_from_db(); renewal.refresh_from_db()
    snap = renewal.payload['claimLossSnapshots'][0]
    check('concurrent cause edit stays pending as conflict', r.status_code == 200 and snap['sync']['cause']['state'] == 'conflict' and source.payload['claims'][0]['causeOfLoss'] == 'Third party edit', r.content[:500])
    r = post('retry', decisions={'cause':{'choice':'use_renewal', 'observed':'stale'}}); source.refresh_from_db(); renewal.refresh_from_db()
    check('stale conflict confirmation never overwrites source', source.payload['claims'][0]['causeOfLoss'] == 'Third party edit' and renewal.payload['claimLossSnapshots'][0]['sync']['cause']['state'] == 'conflict')
    r = post('retry', decisions={'cause':{'choice':'use_renewal', 'observed':'Third party edit'}}); source.refresh_from_db(); renewal.refresh_from_db()
    check('confirmed conflict updates source', r.status_code == 200 and source.payload['claims'][0]['causeOfLoss'] == 'Renewal edit' and renewal.payload['claimLossSnapshots'][0]['sync']['cause']['state'] == 'synced', r.content[:500])
    from cases.claim_loss_snapshot_views import record_snapshot
    calls = []
    def fail_source_once(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise DatabaseError('simulated source write failure')
        return record_snapshot(**kwargs)
    with patch('cases.claim_loss_snapshot_views.record_snapshot', side_effect=fail_source_once):
        r = post('edit', updates={'cause':'Saved despite failure'})
    source.refresh_from_db(); renewal.refresh_from_db()
    snap = renewal.payload['claimLossSnapshots'][0]
    check('source database failure preserves renewal edit for retry', r.status_code == 200 and snap['cause'] == 'Saved despite failure' and snap['sync']['cause']['state'] == 'pending' and source.payload['claims'][0]['causeOfLoss'] == 'Renewal edit', r.content[:500])
    snap = renewal.payload['claimLossSnapshots'][0]; snap['sourceCaseUid'] = str(uuid.uuid4()); renewal.save()
    r = post('edit', updates={'cause':'Pending'}); renewal.refresh_from_db()
    check('missing source preserves renewal change and pending status', r.status_code == 200 and renewal.payload['claimLossSnapshots'][0]['sync']['cause']['state'] == 'pending', r.content[:500])
    transaction.set_rollback(True)
print(f'{sum(checks)}/{len(checks)} Claim loss synchronization checks passed')
