"""2026-10-29 批單的 Debit Note（加費）與 Credit Note（退費，只開放 TWD）：伺服器端的開放條件。
只在拋棄式 QA 資料庫執行；所有變更在交易內回滾。"""
import copy, json, os
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from audit.models import AuditLog
from cases.models import Case
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok):
    assert ok, name
    checks.append(name); print('PASS ' + name, flush=True)

with transaction.atomic():
    user = get_user_model().objects.create_user(username='zz.endorsement.notes', password='QA-Endorsement-Notes-9!')
    person = Personnel.objects.create(name='QA Endorsement Notes', department='reinsurance', role_code='sales', auth_user_id=str(user.pk),
                                      account_status='active', created_by='qa', updated_by='qa')
    client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False); client.force_login(user)
    def call(case, kind):
        client.get('/api/auth/csrf')
        return client.post('/api/document-generation-log', data=json.dumps({'caseUid': str(case.case_uid), 'kind': kind, 'format': 'docx'}),
                           content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    def error(response):
        return response.json().get('error') if response.status_code != 204 else None

    base = dict(currency='TWD', reinsuranceStructure='QS', ae='QA Endorsement Notes', aeEmail='qa@example.invalid', reinsured='QA Cedant',
                originalInsured='QA Insured', type='Property', policyFrom='2026-01-01', policyTo='2027-01-01', originalPremium=1000,
                riCommPct=15, taxPct=1, paymentTermsDays=90, reinsurers=[dict(name='QA RI A', sharePct=60, premium=900, paymentTermsDays=90)])
    original = Case.objects.create(status='posted', tw_ref='QA-NOTE-001', payload=base, owner_personnel=person, created_by='qa', updated_by='qa')
    endo_base = {**copy.deepcopy(base), 'parentTwRef': 'QA-NOTE-001', 'endorsementSeq': 1, 'endoEffectiveDate': '2026-03-01', 'endoTypes': ['Premium']}
    endo = Case.objects.create(status='posted', tw_ref='QA-NOTE-001-E01', parent_case=original, payload=endo_base, owner_personnel=person, created_by='qa', updated_by='qa')

    def set_payload(**changes):
        Case.objects.filter(pk=endo.pk).update(payload={**copy.deepcopy(endo_base), **changes})

    # 加費：Debit Note 可以、Credit Note 不行
    set_payload(originalPremium=5842)
    before = AuditLog.objects.filter(action='generate_document').count()
    r = call(endo, 'debit')
    check('additional premium: Debit Note is allowed', r.status_code == 204)
    audit = AuditLog.objects.filter(action='generate_document').order_by('-id').first()
    check('additional premium: one audit record with kind debit', AuditLog.objects.filter(action='generate_document').count() == before + 1 and audit.after_data.get('kind') == 'debit')
    check('additional premium: Credit Note is refused', error(call(endo, 'credit')) == 'endorsement_additional_premium')

    # 退費：Credit Note 可以（TWD）、Debit Note 不行
    set_payload(originalPremium=-5842, reinsurers=[dict(name='QA RI A', sharePct=60, premium=-900, paymentTermsDays=90)])
    r = call(endo, 'credit')
    audit = AuditLog.objects.filter(action='generate_document').order_by('-id').first()
    check('return premium: Credit Note is allowed for TWD', r.status_code == 204 and audit.after_data.get('kind') == 'credit')
    check('return premium: Debit Note is refused', error(call(endo, 'debit')) == 'endorsement_return_premium')
    for currency in ('USD', 'EUR', '', None):
        set_payload(originalPremium=-5842, currency=currency)
        check(f'return premium in {currency!r}: Credit Note is not available yet', error(call(endo, 'credit')) == 'credit_currency_unsupported')

    # 保費 0：兩種都不出
    for premium in (0, '', None):
        set_payload(originalPremium=premium)
        check(f'premium {premium!r}: no Debit Note', error(call(endo, 'debit')) == 'endorsement_note_zero_premium')
        check(f'premium {premium!r}: no Credit Note', error(call(endo, 'credit')) == 'endorsement_note_zero_premium')

    # 付款日需要批單生效日與 Cedant Collection Days
    for value in ('', None, '2026-02-30', '01/03/2026'):
        set_payload(originalPremium=5842, endoEffectiveDate=value)
        check(f'effective date {value!r}: refused', error(call(endo, 'debit')) == 'endorsement_effective_date_required')
    for days in (None, '', 10, 30.5):
        set_payload(originalPremium=-5842, paymentTermsDays=days)
        check(f'Cedant Collection Days {days!r}: refused', error(call(endo, 'credit')) == 'cedant_collection_days_required')

    # 一般 Debit Note 的資料檢查也照樣套用
    set_payload(originalPremium=-5842, reinsured='')
    check('Credit Note still requires the usual Debit Note data (Reinsured)', error(call(endo, 'credit')) == 'reinsured_required')

    # 還沒 Announce 的批單
    set_payload(originalPremium=5842)
    Case.objects.filter(pk=endo.pk).update(status='draft', tw_ref=None)
    check('draft endorsement: Debit Note waits for Announce', error(call(endo, 'debit')) == 'endorsement_note_requires_announce')
    Case.objects.filter(pk=endo.pk).update(status='closed', tw_ref='QA-NOTE-001-E01')
    check('Confirmed endorsement: Debit Note is allowed', call(endo, 'debit').status_code == 204)

    # 原單：Debit Note 照舊；Credit Note 不開放
    check('original case: Debit Note unchanged', call(original, 'debit').status_code == 204)
    check('original case: Credit Note is refused', error(call(original, 'credit')) == 'credit_endorsement_only')
    client.get('/api/auth/csrf')
    bad = client.post('/api/document-generation-log', data=json.dumps({'caseUid': str(endo.case_uid), 'kind': 'invoice', 'format': 'docx'}),
                      content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    check('unknown kind lists credit among the valid kinds', bad.status_code == 400 and 'credit' in bad.json()['message'])
    endo.refresh_from_db()
    check('checking never changes the saved endorsement', endo.payload.get('originalPremium') == 5842)
    transaction.set_rollback(True)
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back', flush=True)
