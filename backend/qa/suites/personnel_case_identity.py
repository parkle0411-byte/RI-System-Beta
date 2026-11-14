"""Exercise Personnel-backed Case identities and draft creator defaults."""
import io, json, os
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from cases.models import Case
from cases.personnel_identity import ae_email, resolve_ae
from personnel.models import Personnel
from masterdata.models import MasterRecord

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    checks.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ' ' + str(detail)))

with transaction.atomic():
    user = get_user_model().objects.create_user(username='qa.identity', password='QA-Test-123!')
    creator = Personnel.objects.create(name='QA Creator', department='reinsurance', role_code='sales', email='creator@example.com', auth_user_id=str(user.pk), account_status='active', created_by='qa', updated_by='qa')
    other = Personnel.objects.create(name='QA Creator', department='business_1', role_code='general_manager', email='other@example.com', created_by='qa', updated_by='qa')
    disallowed = Personnel.objects.create(name='QA Finance', department='finance', role_code='accounting', created_by='qa', updated_by='qa')
    client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
    client.force_login(user)
    client.get('/api/auth/csrf')
    def call(method, body):
        return getattr(client, method)('/api/cases', data=json.dumps(body), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    initial = {'classOfBusiness':'Commercial General Liability', 'reinsuranceStructure':'QS', 'currency':'USD'}
    r = call('post', {'case':initial, 'incompleteDraft':True})
    check('new draft created', r.status_code == 201, r.content[:500])
    case = None
    if r.status_code == 201:
        case = Case.objects.get(case_uid=r.json()['case']['caseUid'])
        check('creator defaults to both owner and AE', case.owner_personnel_id == creator.pk and case.ae_personnel_id == creator.pk and case.payload['draftInput']['aePersonnelId'] == creator.pk)
        payload = dict(case.payload['draftInput']); payload.update(aePersonnelId=other.pk, ae=other.name)
        r = call('put', {'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':payload,'incompleteDraft':True})
        case.refresh_from_db()
        check('same-name Personnel can be selected unambiguously by ID', r.status_code == 200 and case.ae_personnel_id == other.pk, r.content[:500])
        other.name = 'QA Renamed Draft'; other.save(update_fields=['name'])
        detail = client.get('/api/cases', {'caseUid':str(case.case_uid)}).json()['case']['payload']
        listed = next(row for row in client.get('/api/cases').json()['cases'] if row['caseUid'] == str(case.case_uid))
        check('draft detail and list show the current Personnel name without rewriting the saved case', detail['ae'] == other.name and listed['aeName'] == other.name and case.payload['ae'] != other.name)
        other.name = 'QA Creator'; other.save(update_fields=['name'])
        payload = dict(case.payload['draftInput']); payload.update(aePersonnelId=disallowed.pk, ae=disallowed.name)
        r = call('put', {'caseUid':str(case.case_uid),'rowVersion':case.row_version,'case':payload,'incompleteDraft':True})
        check('ineligible person cannot be newly selected', r.status_code == 400 and r.json().get('error') == 'invalid_account_executive', r.content[:500])
        check('linked AE email comes from the selected ID', ae_email(case.payload) == 'other@example.com')
        other.email = ''; other.save(update_fields=['email'])
        check('missing Personnel email never falls back to historical email', ae_email({**case.payload, 'aeEmail':'old@example.com'}) == '')
        case.status = 'posted'; case.payload['ae'] = 'Historical name'; case.save(update_fields=['status','payload'])
        other.name = 'Renamed person'; other.save(update_fields=['name'])
        edited = {'aePersonnelId':other.pk, 'ae':'Renamed person'}
        resolved = resolve_ae(edited, current=case)
        check('announced AE retains historical name', resolved.get('id') == other.pk and edited['ae'] == 'Historical name')
    preselected = None
    r = call('post', {'case':{**initial, 'ownerPersonnelId':other.pk, 'aePersonnelId':other.pk}, 'incompleteDraft':True})
    if r.status_code == 201:
        preselected = Case.objects.get(case_uid=r.json()['case']['caseUid'])
        check('both defaults can be changed before first save', preselected.owner_personnel_id == other.pk and preselected.ae_personnel_id == other.pk)
    else:
        check('both defaults can be changed before first save', False, r.content[:500])
    legacy = Case.objects.create(case_kind='original', status='posted', owner_personnel=creator,
        payload={'ae':'Historic AE', 'ownerPersonnelId':creator.pk, 'ownerPersonnelName':creator.name}, created_by='qa', updated_by='qa')
    retired = Personnel.objects.create(name='Renamed historic AE', department='finance', role_code='accounting', is_active=False,
        deactivated_by='qa', deactivated_at='2026-01-01T00:00:00Z', created_by='qa', updated_by='qa')
    def link(**changes):
        legacy.refresh_from_db()
        data = {'caseUid':str(legacy.case_uid), 'rowVersion':legacy.row_version, 'field':'ae', 'personnelId':retired.pk, **changes}
        return client.post('/api/case-personnel-history', data=json.dumps(data), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    r = link()
    check('different historical name requires a reason', r.status_code == 400 and r.json().get('error') == 'reason_required', r.content[:500])
    r = link(reason='Known rename')
    check('different historical name requires confirmation', r.status_code == 400 and r.json().get('error') == 'confirmation_required', r.content[:500])
    r = link(reason='Known rename', confirmed=True); legacy.refresh_from_db()
    check('historical link accepts retired personnel and keeps original name', r.status_code == 200 and legacy.ae_personnel_id == retired.pk and legacy.payload['ae'] == 'Historic AE' and legacy.payload['personnelIdentityHistory'][0]['reason'] == 'Known rename', r.content[:500])
    from cases.views import financial_input
    preserved = financial_input({'personnelIdentityHistory':[]}, legacy.payload)
    check('normal Case edits cannot replace historical-link audit records', preserved.get('personnelIdentityHistory') == legacy.payload['personnelIdentityHistory'])
    outsider_user = get_user_model().objects.create_user(username='qa.identity.outsider', password='QA-Test-123!')
    Personnel.objects.create(name='QA Outsider', department='reinsurance', role_code='sales', auth_user_id=str(outsider_user.pk), account_status='active', created_by='qa', updated_by='qa')
    outsider_client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
    outsider_client.force_login(outsider_user)
    r = outsider_client.get('/api/case-personnel-history', {'caseUid':str(legacy.case_uid)})
    check('other staff cannot inspect historical identity links', r.status_code in (403, 404), r.content[:500])
    manager_user = get_user_model().objects.create_user(username='qa.identity.manager', password='QA-Test-123!')
    other.auth_user_id = str(manager_user.pk); other.account_status = 'active'; other.save(update_fields=['auth_user_id','account_status'])
    manager_client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
    manager_client.force_login(manager_user); manager_client.get('/api/auth/csrf')
    master = MasterRecord.objects.create(entity_type='ae', name='QA Historic AE Master', is_active=True, payload={}, created_by='qa', updated_by='qa')
    mdm_create = manager_client.post('/api/master-data', data=json.dumps({'entityType':'ae', 'name':'New AE Master'}), content_type='application/json', HTTP_X_CSRFTOKEN=manager_client.cookies['csrftoken'].value)
    mdm_edit = manager_client.put('/api/master-data', data=json.dumps({'id':master.pk, 'rowVersion':master.row_version, 'entityType':'ae', 'name':'Changed AE Master'}), content_type='application/json', HTTP_X_CSRFTOKEN=manager_client.cookies['csrftoken'].value)
    master.refresh_from_db()
    check('AE master data remains historical and cannot be created or edited', mdm_create.status_code == 409 and mdm_edit.status_code == 409 and master.name == 'QA Historic AE Master', (mdm_create.content[:200], mdm_edit.content[:200]))
    legacy.owner_personnel_id = None; legacy.payload['ownerPersonnelId'] = None; legacy.payload['ownerPersonnelName'] = 'Historic owner'; legacy.save()
    r = manager_client.post('/api/case-personnel-history', data=json.dumps({'caseUid':str(legacy.case_uid), 'rowVersion':legacy.row_version, 'field':'owner', 'personnelId':retired.pk, 'reason':'Confirmed historical owner', 'confirmed':True}), content_type='application/json', HTTP_X_CSRFTOKEN=manager_client.cookies['csrftoken'].value)
    legacy.refresh_from_db()
    check('manager can confirm a historical owner when no owner is linked', r.status_code == 200 and legacy.owner_personnel_id == retired.pk and legacy.payload['ownerPersonnelName'] == 'Historic owner', r.content[:500])
    if case and r.status_code == 200:
        case.refresh_from_db()
        r = client.post('/api/case-personnel-history', data=json.dumps({'caseUid':str(case.case_uid), 'rowVersion':case.row_version, 'field':'ae', 'personnelId':retired.pk, 'reason':'x', 'confirmed':True}), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        check('new Personnel-backed cases cannot bypass normal selection restrictions via historical linking', r.status_code == 409 and r.json().get('error') == 'historical_link_not_applicable', r.content[:500])
    unique = Case.objects.create(case_kind='original', status='posted', ae_name_snapshot=retired.name,
        payload={'ae':retired.name}, created_by='qa', updated_by='qa')
    Personnel.objects.create(name='QA Duplicate', department='business_1', role_code='sales', created_by='qa', updated_by='qa')
    Personnel.objects.create(name='QA Duplicate', department='business_2', role_code='sales', created_by='qa', updated_by='qa')
    ambiguous = Case.objects.create(case_kind='original', status='posted', ae_name_snapshot='QA Duplicate',
        payload={'ae':'QA Duplicate'}, created_by='qa', updated_by='qa')
    output = io.StringIO(); call_command('plan_personnel_links', stdout=output)
    unique.refresh_from_db(); ambiguous.refresh_from_db()
    check('historical association dry run makes no changes', unique.ae_personnel_id is None and ambiguous.ae_personnel_id is None and 'DRY RUN' in output.getvalue(), output.getvalue())
    output = io.StringIO(); call_command('plan_personnel_links', apply=True, stdout=output)
    unique.refresh_from_db(); ambiguous.refresh_from_db()
    check('historical association links only unique names and preserves name and audit history', unique.ae_personnel_id == retired.pk and unique.payload['ae'] == retired.name and bool(unique.payload.get('personnelIdentityHistory')) and ambiguous.ae_personnel_id is None, output.getvalue())
    transaction.set_rollback(True)
print(f'{sum(checks)}/{len(checks)} Personnel Case identity checks passed')
