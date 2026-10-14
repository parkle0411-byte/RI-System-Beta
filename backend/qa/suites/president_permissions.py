"""President sees business data across owners; every business mutation stays denied."""
import hashlib
import json
import os

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from cases.models import Case, CaseDocument, DraftRecycleBin
from audit.models import AuditLog, EntitySnapshot
from personnel.models import Personnel
from masterdata.models import MasterRecord
from production.models import ProductionReport, ProductionExclusion
from fxrates.models import FxRate
from ri_system.authz import serialize_principal

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
User = get_user_model()
checks = []
def check(name, ok):
    assert ok, name
    checks.append(name)
    print('PASS ' + name)

def client(person):
    user = User.objects.create_user(username='qa.president.' + str(person.pk), password='Qa-President-Password-9!')
    person.auth_user_id, person.account_status = str(user.pk), 'active'
    person.save()
    c = Client(enforce_csrf_checks=True, HTTP_HOST='localhost')
    c.force_login(user)
    c.get('/api/auth/csrf')
    return c

def call(c, method, path, body):
    return getattr(c, method)(path, data=json.dumps(body), content_type='application/json',
                             HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)

def person(name, dept, role):
    return Personnel.objects.create(name=name, department=dept, role_code=role, created_by='qa', updated_by='qa')

def fingerprint():
    models = [Personnel, User, Case, CaseDocument, DraftRecycleBin, MasterRecord, FxRate,
              ProductionReport, ProductionExclusion, AuditLog, EntitySnapshot]
    return {m.__name__: hashlib.sha256(json.dumps(list(m.objects.order_by('pk').values()),
            sort_keys=True, default=str).encode()).hexdigest() for m in models}

class Rollback(Exception): pass

try:
    with transaction.atomic():
        admin_person = person('QA President Administrator', 'admin', 'admin')
        admin = client(admin_person)
        user_count = User.objects.count()
        created = call(admin, 'post', '/api/personnel', {
            'name': 'David Kao', 'department': 'board_of_directors', 'email': 'david.kao@tw-insure.com',
            'isActive': True,
        })
        check('admin can create Board Personnel with default President role', created.status_code == 201)
        david = Personnel.objects.get(pk=created.json()['person']['id'])
        check('David is active, no split eligibility, no login account', david.role_code == 'president'
              and david.is_active and not david.is_split_eligible and not david.auth_user_id
              and david.account_status == 'not_configured' and User.objects.count() == user_count)
        dup = call(admin, 'post', '/api/personnel', {
            'name': 'David Kao', 'department': 'board_of_directors', 'roleCode': 'president',
            'email': 'david.kao@tw-insure.com',
        })
        check('duplicate creation rejected without extra personnel', dup.status_code == 409)
        updated = call(admin, 'put', '/api/personnel', {
            **created.json()['person'], 'name': 'David Kao', 'roleCode': 'president', 'isActive': True,
            'isSplitEligible': False,
        })
        check('formal department and role remain editable by administrator', updated.status_code == 200
              and updated.json()['person']['roleCode'] == 'president')
        for field in ['department', 'role_code']:
            try:
                with transaction.atomic():
                    values = dict(name='QA invalid ' + field, department='board_of_directors',
                                  role_code='president', created_by='qa', updated_by='qa')
                    values[field] = 'unapproved'
                    Personnel.objects.create(**values)
                check('DB constraint still rejects unknown ' + field, False)
            except IntegrityError:
                check('DB constraint still rejects unknown ' + field, True)

        president_person = person('QA Formal President', 'board_of_directors', 'president')
        president_person.is_split_eligible = False
        president_person.save()
        president = client(president_person)
        perms = set(serialize_principal(president_person)['permissions'])
        check('President has only the agreed business read permissions', perms == {
            'dashboard.read', 'dashboard.read.all', 'cases.read.all',
            'mdm.read', 'production.read', 'fx.read', 'accounting.read', 'personnel.read',
        })
        check('principal has the formal President label', president.get('/api/app-context').json()['principal']['roleLabel'] == 'President')

        owner = person('QA Different Owner', 'reinsurance', 'sales')
        rows = []
        for status in ['draft', 'posted', 'closed', 'reversed']:
            rows.append(Case.objects.create(status=status, owner_personnel=owner,
                tw_ref=None if status == 'draft' else 'QA-PRES-' + status,
                payload={'originalInsured': 'QA Different Owner ' + status, 'currency': 'TWD',
                         'reinsurers': [], 'transactions': [], 'claims': []},
                created_by='qa', updated_by='qa'))
        recycled = Case.objects.create(status='draft', owner_personnel=owner,
            recycled_at=timezone.now(), payload={'originalInsured': 'QA excluded recycled'},
            created_by='qa', updated_by='qa')
        listed = president.get('/api/cases').json()['cases']
        check('President sees all owners and all live case statuses including drafts',
              {str(r.case_uid) for r in rows} <= {r['caseUid'] for r in listed})
        check('recycled case omitted from Account List', str(recycled.case_uid) not in {r['caseUid'] for r in listed})
        before = fingerprint()
        for row in rows:
            r = president.get('/api/cases', {'caseUid': str(row.case_uid)})
            check('read other owner ' + row.status + ' detail', r.status_code == 200)
        posted = rows[1]
        uid = str(posted.case_uid)
        for path in ['/api/dashboard', '/api/master-data', '/api/fx-rates', '/api/accounting',
                     '/api/production-report?month=2026-10', '/api/case-workflow?caseUid=' + uid,
                     '/api/claims?caseUid=' + uid,
                     '/api/case-reminders?caseUid=' + uid]:
            r = president.get(path)
            check('business read allowed: ' + path, r.status_code == 200)
        check('Accounting advertises no editing', president.get('/api/accounting').json()['scope']['canEdit'] is False)
        scope = president.get('/api/production-report?month=2026-10').json()['scope']
        check('Production cannot operate, generate or close', not any(scope[k] for k in
              ['canOperate', 'canClose', 'canGenerate', 'canCloseLatest']))
        check('President can read all Personnel without editing', president.get('/api/personnel').status_code == 200 and president.get('/api/personnel').json()['scope']['readAll'] and not president.get('/api/personnel').json()['scope']['canEdit'])
        for path in ['/api/personnel-options', '/api/audit-log',
                     '/api/draft-recycle-bin', '/api/dashboard-targets', '/health/',
                     '/api/case-documents?caseUid=' + uid,
                     '/api/case-documents?caseUid=' + uid + '&fileId=00000000-0000-0000-0000-000000000001']:
            r = president.get(path)
            check('excluded endpoint denied: ' + path, r.status_code == 403)
        check('direct recycled case detail is unavailable', president.get('/api/cases',
              {'caseUid': str(recycled.case_uid)}).status_code == 404)
        check('Django admin cannot expose Personnel or Audit', president.get('/admin/personnel/personnel/').status_code == 302)

        attempts = [('post', '/api/cases', {}), ('put', '/api/cases', {'caseUid': uid, 'rowVersion': 1}),
                    ('post', '/api/render-document-pdf', {'caseUid': uid, 'kind': 'cover', 'markup': '<div>Denied</div>'}),
                    ('post', '/api/document-generation-log', {'caseUid': uid, 'kind': 'cover', 'format': 'docx'}),
                    ('post', '/api/case-announce', {'caseUid': uid, 'rowVersion': 1})]
        for action in ['create_endorsement', 'create_renewal', 'reverse_case', 'notify_accounting']:
            attempts.append(('post', '/api/case-workflow', {'caseUid': uid, 'rowVersion': 1, 'action': action}))
        for action in ['create_claim', 'update_reserve', 'record_claim_payment']:
            attempts.append(('post', '/api/claims', {'caseUid': uid, 'rowVersion': 1, 'action': action}))
        for action in ['record_payment', 'reverse_payment']:
            attempts.append(('post', '/api/accounting', {'caseUid': uid, 'rowVersion': 1, 'action': action}))
        for action in ['generate', 'exclude', 'close']:
            attempts.append(('post', '/api/production-report', {'month': '2026-10', 'action': action}))
        for method in ['post', 'put', 'delete']:
            attempts.append((method, '/api/case-documents', {'caseUid': uid}))
        for path, methods in [('/api/master-data', ['post', 'put']), ('/api/fx-rates', ['post']),
                ('/api/personnel', ['post', 'put']), ('/api/dashboard-targets', ['post', 'put']),
                ('/api/draft-recycle-bin', ['post']), ('/api/personnel-accounts', ['post']),
                ('/api/personnel-accounts/disable', ['post']), ('/api/personnel-accounts/enable', ['post']),
                ('/api/personnel-accounts/reset-password', ['post'])]:
            attempts.extend((method, path, {}) for method in methods)
        for method, path, body in attempts:
            resp = call(president, method, path, body)
            check('mutation denied: ' + method.upper() + ' ' + path + ' ' + str(body.get('action', '')),
                  resp.status_code == 403)
        check('all business reads and rejected writes leave data unchanged', fingerprint() == before)
        raise Rollback()
except Rollback:
    pass
print(f'{len(checks)}/{len(checks)} President permission checks passed; database changes rolled back')
