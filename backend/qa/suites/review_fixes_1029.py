"""2026-10-29 全系統檢查後的修正：
1. Case Viewer 不能看 Insured Master（業主：本來就不該看）；可看全部案件的角色照舊。原本 Case Viewer 讀清單會 500。
2. PUT /api/cases 沒有 case 物件時回 400 validation_failed（原本批單會 500）。
只在拋棄式 QA 資料庫執行；所有變更在交易內回滾。"""
import json, os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.models import Case
from cases import insured_master as im
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, f'{name} {detail}'
    checks.append(name); print('PASS ' + name, flush=True)

U = get_user_model()
DEPT = {'admin': 'admin', 'sales': 'reinsurance', 'accounting': 'finance', 'accounting_manager': 'finance',
        'general_manager': 'reinsurance', 'viewer': 'business_1', 'president': 'board_of_directors'}
def login(role):
    u = U.objects.create_user(username='zz.fix1029.' + role, password='Fix-1029-Pass-9!')
    p = Personnel.objects.create(name='ZZ Fix ' + role, department=DEPT[role], role_code=role, auth_user_id=str(u.pk),
                                 account_status='active', created_by='qa', updated_by='qa')
    c = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False); c.force_login(u); c.get('/api/auth/csrf')
    return c, p

with transaction.atomic():
    clients = {role: login(role) for role in DEPT}
    actor = {'id': 'qa', 'name': 'qa'}
    rec = im.find_or_create('測試修正被保險人', actor)
    viewer_c, viewer_p = clients['viewer']
    own = Case.objects.create(status='posted', tw_ref='ZZFIX001', payload={'originalInsuredCn': rec.name, 'insuredDirectoryEnabled': True},
                              owner_personnel=viewer_p, insured_master=rec, created_by='qa', updated_by='qa')

    # 1) Insured Master：Case Viewer 一律 403（清單、單筆、搜尋），不再 500；其他可看全部案件的角色 200
    for path in ('/api/insured-masters', f'/api/insured-masters?id={rec.pk}', '/api/insured-masters?search=%E6%B8%AC'):
        r = viewer_c.get(path)
        check(f'Case Viewer cannot read {path.split("?")[0]}{"?" + path.split("?")[1].split("=")[0] if "?" in path else ""} (403, not 500)', r.status_code == 403, r.status_code)
    for role in ('admin', 'sales', 'accounting', 'accounting_manager', 'general_manager', 'president'):
        c, _ = clients[role]
        r = c.get('/api/insured-masters')
        check(f'{role} can still list insured masters', r.status_code == 200 and any(x['id'] == rec.pk for x in r.json()['records']), r.status_code)
        r = c.get(f'/api/insured-masters?id={rec.pk}')
        check(f'{role} can still open one insured master', r.status_code == 200 and r.json()['record']['name'] == rec.name, r.status_code)
    r = viewer_c.get(f'/api/cases?caseUid={own.case_uid}')
    check('Case Viewer still sees the insured master name on an own case', r.status_code == 200 and (r.json().get('case') or r.json()).get('insuredMaster', {}).get('name') == rec.name
          if r.status_code == 200 else False, r.status_code)

    # 2) PUT /api/cases 沒有 case 物件：一般案件與批單都回 400 validation_failed
    sales_c, sales_p = clients['sales']
    root = Case.objects.create(status='closed', tw_ref='ZZFIX002', payload={'reinsuranceStructure': 'QS', 'classOfBusiness': 'Property', 'currency': 'TWD'},
                               owner_personnel=sales_p, created_by='qa', updated_by='qa')
    endo = Case.objects.create(status='draft', case_kind='endorsement', parent_case=root, payload={'parentTwRef': 'ZZFIX002', 'reinsuranceStructure': 'QS'},
                               owner_personnel=sales_p, created_by='qa', updated_by='qa')
    draft = Case.objects.create(status='draft', payload={'reinsuranceStructure': 'QS'}, owner_personnel=sales_p, created_by='qa', updated_by='qa')
    for label, case in (('endorsement', endo), ('ordinary draft', draft)):
        for bad in (None, 'x', 5, [], [1]):
            body = {'caseUid': str(case.case_uid), 'rowVersion': case.row_version}
            if bad is not None:
                body['case'] = bad
            r = sales_c.put('/api/cases', data=json.dumps(body), content_type='application/json', HTTP_X_CSRFTOKEN=sales_c.cookies['csrftoken'].value)
            check(f'{label}: case={bad!r} returns 400 validation_failed', r.status_code == 400 and r.json().get('error') == 'validation_failed', (r.status_code, r.content[:120]))
        case.refresh_from_db()
        check(f'{label}: nothing was saved', case.row_version == 1)
    transaction.set_rollback(True)
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back', flush=True)
