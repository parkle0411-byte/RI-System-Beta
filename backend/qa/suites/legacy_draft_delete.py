"""Deleting never-confirmed Legacy drafts (owner decisions 2026-11-25). Disposable MySQL only.

The owner (draft owner) or a System Administrator may delete an endorsement/claim draft that was never
confirmed, with a reason; the row is removed and the Legacy audit keeps its content. The database allows
the web account to delete only such rows.
"""
import copy, json, os
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction, DatabaseError
from django.test import Client
from django.utils import timezone
from legacy.models import ImportBatch, LegacyTransaction, LegacyAudit, NumberCounter
from personnel.models import Personnel
from qa.accounting_full import accounting_get

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

clients, people = {}, {}
for key, role in (('owner', 'sales'), ('other', 'sales'), ('gm', 'general_manager'), ('admin', 'admin'), ('finance', 'accounting')):
    u = get_user_model().objects.create_user(username='qa-ldd-' + key, password='Delete-QA-9!')
    p = Personnel.objects.create(name='QA LDD ' + key, department='finance' if key == 'finance' else 'reinsurance', role_code=role,
                                 auth_user_id=str(u.pk), account_status='active', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost'); c.force_login(u); clients[key] = c; people[key] = p

source = LegacyTransaction.objects.create(number='F-LDD-1', reference='LDD-REF', historical=True, status='confirmed', currency='TWD',
    first_confirmed_at=timezone.now(), data=dict(reference='LDD-REF', currency='TWD', kind='premium', insured='LDD insured', insuredCn='',
        cedant='LDD cedant', party='LDD reinsurer', ae='QA LDD owner', effectiveDate='2035-01-01', expiryDate='2035-12-31', rule='ordinary',
        cedantDays=90, reinsurerDays=90, share=25, amounts=dict(premium=100, commission=0, tax=0, brokerage=5, claim=0, cedantNet=100, reinsurerNet=95)),
    fx_snapshot=dict(rate=1, incomeTwd=5, premiumTwd=100, people=[dict(name='QA LDD owner', income=5)]))
source_before = (source.version, json.dumps(source.data, sort_keys=True))

def send(who, body, method='PATCH'):
    r = getattr(clients[who], method.lower())('/api/legacy', json.dumps(body), content_type='application/json')
    return r.status_code, r.json()
def draft(kind='endorsement', who='owner'):
    code, t = send(who, dict(referenceTransaction=str(source.pk), kind=kind), method='POST')
    assert code == 201, t
    return t
def act(who, t, action, **extra):
    return send(who, dict(id=t['uid'], version=t['version'], action=action, **extra))
def remove(who, t, reason='Keyed by mistake', **override):
    body = dict(id=t['uid'], version=t['version'], action='delete', reason=reason); body.update(override)
    return send(who, body)
def detail(who, uid):
    return clients[who].get('/api/legacy?id=' + uid)
exists = lambda uid: LegacyTransaction.objects.filter(pk=uid).exists()
deleted_audits = lambda: LegacyAudit.objects.filter(action='draft_deleted').count()

# ---------- who sees the action ----------
t = draft()
check('the draft owner is offered Delete', t['permissions']['delete'] is True, t['permissions'])
check("a System Administrator is offered Delete on another user's draft", detail('admin', t['uid']).json()['permissions']['delete'] is True
      and detail('admin', t['uid']).json()['permissions']['edit'] is False)
for who in ('other', 'gm', 'finance'):
    check(who + ' is not offered Delete', detail(who, t['uid']).json()['permissions']['delete'] is False)
listed = {x['uid']: x for x in clients['owner'].get('/api/legacy?size=100').json()['rows']}
check('list rows carry the same permission', listed[t['uid']]['permissions']['delete'] is True
      and listed[str(source.pk)]['permissions']['delete'] is False)

# ---------- refusals ----------
for who in ('other', 'gm', 'finance'):
    code, r = remove(who, t)
    check(who + ' cannot delete the draft', code == 403 and exists(t['uid']), (code, r))
r = Client(HTTP_HOST='localhost').patch('/api/legacy', json.dumps(dict(id=t['uid'], version=t['version'], action='delete', reason='x')), content_type='application/json')
check('anonymous cannot delete', r.status_code in (401, 403) and exists(t['uid']), r.status_code)
for bad in ('', '   ', None, 5, ['x'], 'x' * 501):
    code, r = remove('owner', t, reason=bad)
    check('refused without a usable reason: ' + repr(bad)[:20], code == 400 and exists(t['uid']), (code, r))
code, r = send('owner', dict(id=t['uid'], version=t['version'], action='delete'))
check('a missing reason is refused', code == 400 and exists(t['uid']), (code, r))
for version in (t['version'] + 1, str(t['version']), None):
    code, r = remove('owner', t, version=version)
    check('a stale or malformed version is refused: ' + repr(version), code == 409 and exists(t['uid']), (code, r))
check('refused attempts record no deletion', deleted_audits() == 0)

# ---------- the owner deletes a saved draft ----------
code, t = act('owner', t, 'save', data=dict(gross=1000, brokerage=10, endorsementNo='DEL-1', remark='typed by mistake', effectiveDate='2035-06-01'))
assert code == 200, t
counters = list(NumberCounter.objects.values().order_by('year'))
rows_before = accounting_get(clients['admin'], '?view=list').json()['transactionRows']
total = LegacyTransaction.objects.count()
code, r = remove('owner', t, reason='  Wrong source row  ')
check('the owner deletes the draft', code == 200 and r == {'ok': True, 'deleted': True}, (code, r))
check('the row is gone', not exists(t['uid']) and LegacyTransaction.objects.count() == total - 1)
check('its detail is not found and it left the list', detail('owner', t['uid']).status_code == 404
      and t['uid'] not in {x['uid'] for x in clients['owner'].get('/api/legacy?size=100').json()['rows']})
a = LegacyAudit.objects.get(entity=t['uid'], action='draft_deleted')
check('the audit names who deleted it and why', a.actor_id == people['owner'].pk and a.actor_name == people['owner'].name and a.reason == 'Wrong source row')
check('the audit keeps the whole draft', a.before['data']['endorsementNo'] == 'DEL-1' and a.before['data']['remark'] == 'typed by mistake'
      and a.before['data']['gross'] == 1000 and a.before['reference'] == 'LDD-REF' and a.before['referenceTransaction'] == str(source.pk)
      and a.before['createdById'] == people['owner'].pk and a.before['ownerId'] == people['owner'].pk and a.before['createdAt']
      and a.before['currency'] == 'TWD' and a.before['status'] == 'draft' and a.before['number'] is None and a.after == {}, a.before)
check('earlier audit entries of the draft are kept', sorted(LegacyAudit.objects.filter(entity=t['uid']).values_list('action', flat=True))
      == ['draft_created', 'draft_deleted', 'draft_saved'])
code, r = remove('owner', t)
check('deleting it again reports not found', code == 404, (code, r))
check('deleting does not touch numbering, the source or Accounting',
      list(NumberCounter.objects.values().order_by('year')) == counters
      and (lambda s: (s.version, json.dumps(s.data, sort_keys=True)) == source_before)(LegacyTransaction.objects.get(pk=source.pk))
      and accounting_get(clients['admin'], '?view=list').json()['transactionRows'] == rows_before)

# ---------- administrator, claim drafts ----------
c = draft('claim')
code, r = remove('admin', c, reason='x' * 500)
check("a System Administrator deletes another user's claim draft (500-character reason)", code == 200 and not exists(c['uid'])
      and LegacyAudit.objects.get(entity=c['uid'], action='draft_deleted').actor_id == people['admin'].pk, (code, r))
c = draft('claim', who='admin')
code, r = remove('admin', c)
check('an administrator deletes their own draft', code == 200 and not exists(c['uid']), (code, r))

# ---------- confirmed, retracted and historical rows ----------
t = draft()
code, t = act('owner', t, 'save', data=dict(gross=1000, commissionRate=0, taxRate=0, brokerage=10, endorsementNo='KEEP-1', effectiveDate='2035-06-01'))
assert code == 200, t
code, t = act('owner', t, 'confirm')
check('a draft can still be confirmed and numbered', code == 200 and t['status'] == 'confirmed' and t['number'].startswith('LTX-') and not t['permissions']['delete'], t)
for who in ('owner', 'admin'):
    code, r = remove(who, t)
    check(who + ' cannot delete a confirmed transaction', code == 403 and exists(t['uid']), (code, r))
code, t = act('owner', t, 'retract')
check('it can be returned to draft', code == 200 and t['status'] == 'draft' and t['number'], t)
for who in ('owner', 'admin'):
    code, r = remove(who, t)
    check(who + ' cannot delete a returned (numbered) draft', code == 403 and exists(t['uid'])
          and detail(who, t['uid']).json()['permissions']['delete'] is False, (code, r))
retracted = t['uid']
code, r = send('admin', dict(id=str(source.pk), version=source.version, action='delete', reason='x'))
check('an imported/historical row cannot be deleted', code == 403 and exists(str(source.pk)), (code, r))

# ---------- a transferred draft belongs to its new owner ----------
t = draft()
Personnel.objects.filter(pk=people['owner'].pk).update(role_code='accounting')
code, t = act('admin', t, 'transfer', ownerId=people['other'].pk, reason='Owner changed role')
assert code == 200, t
Personnel.objects.filter(pk=people['owner'].pk).update(role_code='sales')
code, r = remove('owner', t)
check('the former owner cannot delete a transferred draft', code == 403 and exists(t['uid']), (code, r))
code, r = remove('other', t)
check('the new owner deletes it', code == 200 and not exists(t['uid'])
      and LegacyAudit.objects.get(entity=t['uid'], action='draft_deleted').before['createdById'] == people['owner'].pk, (code, r))

# ---------- the database lets the web account delete only never-confirmed drafts ----------
def sql_error(statement, params=(), using='default'):
    try:
        with transaction.atomic(using=using):
            with connections[using].cursor() as cur:
                cur.execute(statement, params)
    except DatabaseError as exc:
        return str(exc)
    return None
with connection.cursor() as cur:
    cur.execute('SELECT CURRENT_USER()'); who = cur.fetchone()[0]
check('the backend connects as ri_runtime', who.startswith('ri_runtime@'), who)
batch = ImportBatch.objects.create(filename='', sha256='b' * 64, storage_key='', status='imported', created_by='qa')
def row(**kw):
    base = dict(reference='LDD-SQL', currency='TWD', status='draft', data=dict(kind='endorsement'), owner_id=people['owner'].pk)
    base.update(kw)
    return LegacyTransaction.objects.create(**base)
protected = {
    'a confirmed row': row(status='confirmed', number='LDD-C', first_confirmed_at=timezone.now()),
    'a confirmed row without number': row(status='confirmed'),
    'a returned draft': LegacyTransaction.objects.get(pk=retracted),
    'a draft with a number': row(number='LDD-N'),
    'a draft that was confirmed once': row(first_confirmed_at=timezone.now()),
    'an imported row': row(batch=batch),
    'a historical row': row(historical=True),
    'the source row': source,
    'a withdrawn row': row(status='withdrawn'),
    'a cancelled row': row(status='cancelled'),
}
for label, x in protected.items():
    error = sql_error('DELETE FROM ri_legacy_transactions WHERE uid=%s', [x.pk.hex])
    check('database refuses to delete ' + label, error and 'only a draft that was never confirmed' in error and exists(str(x.pk)), error)
count = LegacyTransaction.objects.count()
spare = row(reference='LDD-SPARE')
error = sql_error('DELETE FROM ri_legacy_transactions')
check('a bulk delete removes nothing, not even the drafts', error and LegacyTransaction.objects.count() == count + 1 and exists(str(spare.pk)), error)
check('database allows a never-confirmed draft', sql_error('DELETE FROM ri_legacy_transactions WHERE uid=%s', [spare.pk.hex]) is None and not exists(str(spare.pk)))
blank = row(number='')
check('database treats an empty number as unnumbered', sql_error('DELETE FROM ri_legacy_transactions WHERE uid=%s', [blank.pk.hex]) is None)
for statement in ('DROP TRIGGER ri_legacy_transactions_runtime_delete', 'DELETE FROM ri_legacy_audit', 'DELETE FROM ri_legacy_import_batches',
                  'TRUNCATE TABLE ri_legacy_transactions'):
    check('web account still cannot run: ' + statement, sql_error(statement) is not None)

# Owner-authorized maintenance (ri_app) is not limited by this trigger.
owner_db = copy.deepcopy(connections.databases['default'])
owner_db.update(USER='ri_app', PASSWORD=Path('/run/secrets/mysql_app_password').read_text().strip())
connections.databases['legacy_qa_owner'] = owner_db
class Rollback(Exception): pass
target = protected['a confirmed row']
try:
    with transaction.atomic(using='legacy_qa_owner'):
        with connections['legacy_qa_owner'].cursor() as cur:
            cur.execute('DELETE FROM ri_legacy_transactions WHERE uid=%s', [target.pk.hex])
            affected = cur.rowcount
        raise Rollback()
except Rollback:
    pass
check('the maintenance account can still delete in an authorized procedure (rolled back)', affected == 1 and exists(str(target.pk)))
print(f'{len(checks)}/{len(checks)} passed legacy draft delete checks')
