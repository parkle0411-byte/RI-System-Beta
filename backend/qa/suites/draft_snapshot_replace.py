"""Replaceable Draft snapshot (owner decision 2026-11-13). Disposable MySQL with db_harden protection.

A Draft keeps one latest `draft_updated` snapshot that each save overwrites. Everything else stays
append-only: other reasons and entity types, cases that are no longer Drafts, and every DELETE.
"""
import copy, json, os, uuid
from django.contrib.auth import get_user_model
from django.db import connection, transaction, DatabaseError
from django.test import Client
from audit.models import AppendOnlyError, AuditLog, EntitySnapshot
from audit.services import record_draft_snapshot, record_snapshot
from cases.models import Case
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

user = get_user_model().objects.create_user(username='qa-draft-snapshot', password='Qa-Snapshot-9!')
person = Personnel.objects.create(name='QA Draft Snapshot', department='reinsurance', role_code='sales', auth_user_id=str(user.pk),
                                  account_status='active', email='qa-snapshot@example.test', created_by='qa', updated_by='qa')
c = Client(HTTP_HOST='localhost', raise_request_exception=False); c.force_login(user)
def payload(**over):
    p = dict(classOfBusiness='Property', classCode='PF', typePrefix='Property', reinsuranceStructure='QS', currency='TWD',
             originalInsured='QA Snapshot Insured', originalInsuredCn='草稿副本測試', reinsured='QA Snapshot Cedant', newOrRenew='New',
             policyFrom='2026-01-01', policyTo='2027-01-01', interest='Stock', situations=[{'address': 'Taipei', 'postcode': '100'}],
             sumInsured=[{'item': 'Building', 'amount': 1000000}], basisOfValuation='Actual Cash Value',
             originalPremium=1000, riCommPct=0, taxPct=1, paymentTermsDays=90,
             reinsurers=[{'name': 'QA Snapshot Re', 'sharePct': 20, 'premium': 1000, 'riCommPct': 10, 'taxPct': 0, 'paymentTermsDays': 90}],
             deductibles='TWD 1,000', originalConditions='A', reinsuredRetention='Waived', lossAdvisedDate='2026-01-01', lossRecordYears=5,
             ae=person.name, ownerPersonnelId=person.pk, ownerPersonnelName=person.name)
    p.update(over); return p
def snaps(uid, reason=None):
    q = EntitySnapshot.objects.filter(entity_type='case', entity_id=str(uid))
    return list((q.filter(snapshot_reason=reason) if reason else q).order_by('entity_version'))
def raw(sql, params=()):
    """Run as the application database account; return the error text, or '' when it succeeds."""
    try:
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(sql, params)
        return ''
    except DatabaseError as exc:
        return str(exc)

r = c.post('/api/cases', json.dumps({'case': payload()}), content_type='application/json')
assert r.status_code == 201, r.content[:300]
uid = r.json()['case']['caseUid']; version = r.json()['case']['rowVersion']
check('creating a Draft keeps its draft_created snapshot', [s.snapshot_reason for s in snaps(uid)] == ['draft_created'])

for n, incomplete in enumerate((False, True, True, False, True), start=1):
    r = c.put('/api/cases', json.dumps({'caseUid': uid, 'rowVersion': version, 'incompleteDraft': incomplete,
                                         'case': payload(originalPremium=1000 + n, interest=f'Stock {n}')}), content_type='application/json')
    assert r.status_code == 200, r.content[:300]
    version = r.json()['case']['rowVersion']
    drafts = snaps(uid, 'draft_updated')
    check(f'save {n} (autosave={incomplete}): exactly one draft_updated snapshot, at the current version', len(drafts) == 1 and drafts[0].entity_version == version,
          [(s.entity_version) for s in drafts])
row = Case.objects.get(case_uid=uid)
latest = snaps(uid, 'draft_updated')[0]
check('the single snapshot holds the latest saved content', latest.snapshot_data['payload'].get('interest') == row.payload.get('interest') == 'Stock 5'
      and latest.snapshot_data['rowVersion'] == row.row_version)
check('the creation snapshot is untouched', [(s.snapshot_reason, s.entity_version) for s in snaps(uid)] == [('draft_created', 1), ('draft_updated', version)])
check('Draft saves are still audited when Audit is recording, or silently skipped when paused',
      AuditLog.objects.filter(entity_type='case', entity_id=uid, action='update_draft').count() in (0, 5))

# Old accumulated copies (before 2026-11-13) are kept; only the newest one is replaced.
with transaction.atomic():
    record_snapshot(entity_type='case', entity_id=uid, version=version + 50, reason='draft_updated', data={'old': 'accumulated copy'}, created_by='qa')
older_pk = latest.pk
r = c.put('/api/cases', json.dumps({'caseUid': uid, 'rowVersion': version, 'case': payload(interest='After old copies')}), content_type='application/json')
assert r.status_code == 200, r.content[:300]; version = r.json()['case']['rowVersion']
drafts = snaps(uid, 'draft_updated')
check('with older accumulated copies only the newest is replaced', len(drafts) == 2 and EntitySnapshot.objects.get(pk=older_pk).snapshot_data['payload']['interest'] == 'Stock 5'
      and drafts[-1].entity_version == version and drafts[-1].snapshot_data['payload']['interest'] == 'After old copies', [(s.pk, s.entity_version) for s in drafts])

# Protection that must remain.
draft_pk = drafts[-1].pk; created_pk = snaps(uid, 'draft_created')[0].pk
for label, fn in (('queryset.update', lambda: EntitySnapshot.objects.filter(pk=draft_pk).update(created_by='x')),
                  ('queryset.delete', lambda: EntitySnapshot.objects.filter(pk=draft_pk).delete())):
    try:
        fn(); refused = False
    except AppendOnlyError:
        refused = True
    check(f'model {label} is still refused', refused)
err = raw("DELETE FROM ri_entity_snapshots WHERE id=%s", [draft_pk])
check('DELETE of a draft snapshot is refused', bool(err) and EntitySnapshot.objects.filter(pk=draft_pk).exists(), err[:120])
err = raw("UPDATE ri_entity_snapshots SET created_by='x' WHERE id=%s", [created_pk])
check('UPDATE of the draft_created snapshot is refused', 'append-only' in err, err[:160])
err = raw("UPDATE ri_entity_snapshots SET snapshot_reason='case_updated' WHERE id=%s", [draft_pk])
check('a draft snapshot cannot be relabelled', 'append-only' in err, err[:160])
err = raw("UPDATE ri_entity_snapshots SET entity_id=%s WHERE id=%s", [str(uuid.uuid4()), draft_pk])
check('a draft snapshot cannot be moved to another case', 'append-only' in err, err[:160])
err = raw("UPDATE ri_entity_snapshots SET entity_type='master_record' WHERE id=%s", [draft_pk])
check('a draft snapshot cannot change entity type', 'append-only' in err, err[:160])
other = EntitySnapshot.objects.exclude(entity_type='case').first()
if other is None:
    with transaction.atomic():
        other = record_snapshot(entity_type='personnel', entity_id=str(person.pk), version=999, reason='qa', data={'x': 1}, created_by='qa')
err = raw("UPDATE ri_entity_snapshots SET created_by='x' WHERE id=%s", [other.pk])
check('snapshots of other entity types stay immutable', 'append-only' in err, err[:160])
err = raw("UPDATE ri_entity_snapshots SET created_by='x' WHERE entity_type='case' AND snapshot_reason='draft_updated' AND entity_id=%s", [str(uuid.uuid4())])
check('an UPDATE that matches no row changes nothing', err == '')
with transaction.atomic():
    orphan = record_snapshot(entity_type='case', entity_id=str(uuid.uuid4()), version=1, reason='draft_updated', data={'x': 1}, created_by='qa')
err = raw("UPDATE ri_entity_snapshots SET created_by='x' WHERE id=%s", [orphan.pk])
check('a draft snapshot whose case does not exist cannot be changed', 'append-only' in err, err[:160])
for table in ('ri_audit_log', 'ri_legacy_audit'):
    err = raw(f"UPDATE {table} SET id=id WHERE 1=0")
    check(f'{table} gained no UPDATE privilege', 'denied' in err.lower(), err[:120])

# Once the case is no longer a Draft, its draft-era snapshots are immutable again.
before = copy.deepcopy(EntitySnapshot.objects.get(pk=draft_pk).snapshot_data)
Case.objects.filter(case_uid=uid).update(status='posted')
err = raw("UPDATE ri_entity_snapshots SET created_by='x' WHERE id=%s", [draft_pk])
check('after Announce the draft-era snapshot can no longer be changed', 'append-only' in err, err[:160])
try:
    with transaction.atomic():
        record_draft_snapshot(entity_id=uid, version=version + 1, data={'tampered': True}, created_by='qa')
    blocked = False
except DatabaseError:
    blocked = True
check('record_draft_snapshot cannot overwrite a posted case', blocked and EntitySnapshot.objects.get(pk=draft_pk).snapshot_data == before)
Case.objects.filter(case_uid=uid).update(status='draft')
with transaction.atomic():
    record_draft_snapshot(entity_id=uid, version=version + 1, data={'draft': 'again'}, created_by='qa')
check('a case that is a Draft again (for example after Reverse) is replaceable again', EntitySnapshot.objects.get(pk=draft_pk).snapshot_data == {'draft': 'again'})

# A second Draft is independent.
r = c.post('/api/cases', json.dumps({'case': payload(originalInsured='QA Snapshot Second')}), content_type='application/json'); assert r.status_code == 201
uid2 = r.json()['case']['caseUid']; v2 = r.json()['case']['rowVersion']
for n in range(3):
    r = c.put('/api/cases', json.dumps({'caseUid': uid2, 'rowVersion': v2, 'case': payload(originalInsured='QA Snapshot Second', interest=f'Second {n}')}), content_type='application/json')
    assert r.status_code == 200; v2 = r.json()['case']['rowVersion']
check('each Draft has its own single snapshot', len(snaps(uid2, 'draft_updated')) == 1 and snaps(uid2, 'draft_updated')[0].snapshot_data['payload']['interest'] == 'Second 2'
      and EntitySnapshot.objects.get(pk=draft_pk).snapshot_data == {'draft': 'again'})
print(f'{len(checks)}/{len(checks)} passed')
