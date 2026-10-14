"""2026-10-07 Finance case reads, President document denial and Supervisor creation boundaries."""
import hashlib
import json
import os

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case, CaseDocument, DraftRecycleBin
from masterdata.models import MasterRecord
from personnel.models import Personnel
from ri_system.authz import serialize_principal
from personnel.supervision import is_supervisor

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
User = get_user_model()
checks = []


def check(name, ok, detail=''):
    assert ok, name + ': ' + str(detail)
    checks.append(name)
    print('PASS ' + name, flush=True)


def person(name, dept, role, **kw):
    return Personnel.objects.create(name=name, department=dept, role_code=role,
                                   created_by='qa', updated_by='qa', **kw)


def client(p):
    u = User.objects.create_user(username='qa.permission.' + str(p.pk), password='Qa-Permissions-Password-9!')
    p.auth_user_id, p.account_status = str(u.pk), 'active'
    p.save()
    c = Client(enforce_csrf_checks=True, HTTP_HOST='localhost')
    c.force_login(u)
    c.get('/api/auth/csrf')
    return c


def call(c, method, path, body):
    return getattr(c, method)(path, data=json.dumps(body), content_type='application/json',
                             HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value)


def fingerprint():
    return {m.__name__: hashlib.sha256(json.dumps(list(m.objects.order_by('pk').values()),
            sort_keys=True, default=str).encode()).hexdigest()
            for m in [Personnel, User, Case, CaseDocument, DraftRecycleBin, MasterRecord, AuditLog, EntitySnapshot]}


class Rollback(Exception):
    pass


try:
    with transaction.atomic():
        owner = person('QA Permission Other Owner', 'reinsurance', 'sales')
        case_rows = [Case.objects.create(status=status, owner_personnel=owner,
            tw_ref=None if status == 'draft' else 'QA-PERM-' + status,
            payload={'originalInsured': 'QA Permissions ' + status, 'currency': 'TWD',
                     'reinsurers': [], 'transactions': [], 'claims': []}, created_by='qa', updated_by='qa')
            for status in ['draft', 'posted', 'closed', 'reversed']]
        for role in ['accounting', 'accounting_manager']:
            p = person('QA Permission ' + role, 'finance', role)
            c = client(p)
            listed = c.get('/api/cases')
            check(role + ' can read all owners in Account List', listed.status_code == 200
                  and {str(r.case_uid) for r in case_rows} <= {r['caseUid'] for r in listed.json()['cases']})
            for case in case_rows:
                uid = str(case.case_uid)
                for path in ['/api/cases?caseUid=' + uid, '/api/case-workflow?caseUid=' + uid,
                             '/api/claims?caseUid=' + uid, '/api/case-reminders?caseUid=' + uid]:
                    check(role + ' reads ' + case.status + ' ' + path, c.get(path).status_code == 200)
            check(role + ' retains Accounting writes', c.get('/api/accounting').json()['scope']['canEdit'])
            production = c.get('/api/production-report?month=2026-10').json()['scope']
            check(role + ' retains Production responsibilities', production['canOperate'] is (role == 'accounting_manager')
                  and production['canClose'] is (role == 'accounting_manager'))
            before = fingerprint()
            for method, path in [('post', '/api/cases'), ('put', '/api/cases'),
                                 ('post', '/api/case-announce'), ('post', '/api/case-workflow'),
                                 ('post', '/api/claims'), ('post', '/api/render-document-pdf'),
                                 ('post', '/api/document-generation-log'), ('post', '/api/case-documents')]:
                check(role + ' denied ' + method + ' ' + path, call(c, method, path, {}).status_code == 403)
            check(role + ' cannot read or download case documents', c.get('/api/case-documents',
                  {'caseUid': str(case_rows[1].case_uid)}).status_code == 403)
            check(role + ' rejected writes change no records', before == fingerprint())

        president = client(person('QA Permission President', 'board_of_directors', 'president'))
        uid = str(case_rows[1].case_uid)
        check('President retains case detail access', president.get('/api/cases?caseUid=' + uid).status_code == 200)
        check('President has no document permission', not any(x.startswith('documents.')
              for x in president.get('/api/app-context').json()['principal']['permissions']))
        for path in ['/api/case-documents?caseUid=' + uid,
                     '/api/case-documents?caseUid=' + uid + '&fileId=00000000-0000-0000-0000-000000000001']:
            check('President denied document read/download ' + path, president.get(path).status_code == 403)
        for method, path in [('post', '/api/render-document-pdf'), ('post', '/api/document-generation-log'),
                             ('post', '/api/case-documents'), ('put', '/api/case-documents'),
                             ('delete', '/api/case-documents')]:
            check('President denied ' + method + ' ' + path, call(president, method, path, {}).status_code == 403)

        for dept, role, staff_role in [('reinsurance', 'sales', 'sales'), ('finance', 'accounting_manager', 'accounting'),
                                      ('business_1', 'viewer', 'viewer'), 
                                      ('admin', 'viewer', 'viewer'), ('reinsurance', 'general_manager', 'sales')]:
            p = person('QA Supervisor ' + dept + ' ' + role, dept, role, email=dept + '.' + role + '@example.test')
            c = client(p)
            check(p.name + ' no subordinate means no creation privilege',
                  not serialize_principal(p)['isSupervisor'] and call(c, 'post', '/api/personnel',
                  {'name': 'Unauthorized'}).status_code == 403)
            subordinate = person('QA Existing Team ' + str(p.pk), dept, staff_role,
                                 supervisor_name=p.name, supervisor_email=p.email)
            peer = person('QA Unrelated Peer ' + str(p.pk), dept, staff_role)
            ctx = c.get('/api/app-context').json()['principal']
            check(p.name + ' existing assignment grants narrow creation', ctx['isSupervisor']
                  and {'personnel.read.team', 'personnel.create.subordinate'} <= set(ctx['permissions'])
                  and 'personnel.write' not in ctx['permissions'] and 'accounts.manage' not in ctx['permissions'])
            roster = c.get('/api/personnel')
            check(p.name + ' sees roster and creation scope', roster.status_code == 200
                  and roster.json()['scope']['subordinateCreationOnly']
                  and roster.json()['scope']['creationDepartment'] == dept
                  and roster.json()['scope']['creationRoleCode'] == staff_role)
            if role != 'general_manager':
                check(p.name + ' roster limited to own record and direct same-department team',
                      {r['id'] for r in roster.json()['personnel']} == {p.pk, subordinate.pk}
                      and all('accountUsername' not in r for r in roster.json()['personnel'] if r['id'] == p.pk))
            counts = (Personnel.objects.count(), User.objects.count())
            before = fingerprint()
            for override in [{'department': 'business_2'}, {'roleCode': 'admin'}, {'roleCode': 'president'},
                             {'roleCode': 'general_manager'}, {'roleCode': 'accounting_manager'},
                             {'supervisorName': owner.name}, {'supervisorName': ''}]:
                r = call(c, 'post', '/api/personnel', {'name': 'QA Forbidden ' + str(p.pk), **override})
                check(p.name + ' scope enforcement ' + str(override), r.status_code == 403, r.content)
            check(p.name + ' cannot edit existing personnel', call(c, 'put', '/api/personnel',
                  {'id': subordinate.pk, 'rowVersion': subordinate.row_version, 'name': 'Changed'}).status_code == 403)
            check(p.name + ' account creation validates Username for an eligible subordinate',
                  call(c, 'post', '/api/personnel-accounts', {'personnelId': subordinate.pk}).status_code == 400)
            for path in ['/api/personnel-accounts/enable',
                         '/api/personnel-accounts/disable', '/api/personnel-accounts/reset-password']:
                check(p.name + ' account management denied ' + path,
                      call(c, 'post', path, {'personnelId': subordinate.pk}).status_code == 403)
            check(p.name + ' rejected writes change no records', before == fingerprint())
            created = call(c, 'post', '/api/personnel', {'name': 'QA New Team ' + str(p.pk),
                'department': dept, 'roleCode': staff_role, 'supervisorName': p.name.upper(),
                'supervisorEmail': 'wrong@example.test', 'authUserId': '999999', 'accountStatus': 'active'})
            check(p.name + ' creates own-department general staff', created.status_code == 201, created.content)
            new = Personnel.objects.get(pk=created.json()['person']['id'])
            check(p.name + ' creation assigns current Supervisor and canonical email',
                  new.department == dept and new.role_code == staff_role and new.supervisor_name == p.name
                  and new.supervisor_email == p.email)
            check(p.name + ' creation never enables login or creates User', new.account_status == 'not_configured'
                  and new.auth_user_id is None and User.objects.count() == counts[1]
                  and Personnel.objects.count() == counts[0] + 1)
            check(p.name + ' creation is attributed and snapshotted', new.created_by == 'personnel:' + str(p.pk)
                  and EntitySnapshot.objects.filter(entity_type='personnel', entity_id=str(new.pk),
                                                    snapshot_reason='personnel_created').exists())
            p.must_change_password = True
            p.save()
            check(p.name + ' required password change still blocks creation', call(c, 'post', '/api/personnel',
                  {'name': 'QA Locked'}).status_code == 403)
            p.must_change_password = False
            p.save()
            Personnel.objects.filter(pk__in=[subordinate.pk, new.pk]).update(supervisor_name=None, supervisor_email=None)
            check(p.name + ' removal of last assignment revokes creation immediately',
                  not c.get('/api/app-context').json()['principal']['isSupervisor']
                  and call(c, 'post', '/api/personnel', {'name': 'QA Revoked'}).status_code == 403)
            if role != 'general_manager':
                check(p.name + ' removal of last assignment revokes team reads', c.get('/api/personnel').status_code == 403)

        # Same name in different departments must not grant the other person privileges.
        twin_gm = person('QA Supervisor Twin', 'reinsurance', 'general_manager')
        twin_viewer = person('QA Supervisor Twin', 'business_2', 'viewer')
        direct = person('QA Twin Direct', 'business_2', 'viewer', supervisor_name='qa supervisor twin')
        check('same-department resolution qualifies the correct same-name Supervisor only',
              is_supervisor(twin_viewer) and not is_supervisor(twin_gm))
        person('QA Twin Cross Dept', 'finance', 'accounting', supervisor_name='QA Supervisor Twin')
        check('cross-department GM assignment is recognized independently', is_supervisor(twin_gm))
        viewer_client = client(twin_viewer)
        check('Supervisor status does not grant other business privileges',
              viewer_client.get('/api/accounting').status_code == 403 and
              call(viewer_client, 'post', '/api/cases', {}).status_code == 403)
        direct.supervisor_name = None
        direct.save()
        check('different same-name person cannot retain Supervisor access', not is_supervisor(twin_viewer))
        raise Rollback()
except Rollback:
    pass
print(f'{len(checks)}/{len(checks)} personnel permission checks passed; database changes rolled back')
