"""Owner-selected CGL coverage input: persistence and required milestones."""
import copy
import json
import os
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone
from cases.cgl_risk_details import COVERAGES, risk_details_issues
from cases.draft import normalize_draft, validate_announce_ready
from cases.models import Case
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []


def check(name, ok, detail=''):
    checks.append((name, bool(ok), str(detail)))
    if not ok:
        print('FAIL', name, detail)


def ready():
    return dict(reinsuranceStructure='QS', classOfBusiness='Commercial General Liability', classCode='GL',
        currency='USD', newOrRenew='New', ae='Coverage QA AE', aeEmail='qa@example.invalid',
        typePrefix='Commercial General Liability', originalInsured='QA Insured', reinsured='QA Cedant',
        policyFrom='2026-01-01', policyTo='2027-01-01', situations=[dict(address='QA Road', postcode='100')],
        interest='Liability under original policy', limitOfLiability=1000000, deductibles='As original',
        originalConditions='As original', reinsuredRetention='Advice waived', originalPremium=1000,
        paymentTermsDays=90, lossAdvisedDate='2026-01-01', lossRecordYears=5,
        reinsurers=[dict(name='QA General Re', sharePct=100, premium=1000, riCommPct=10, taxPct=0, paymentTermsDays=90)],
        coverages=[COVERAGES[0]], coveragesOther='', selfInsuredRetention='',
        cglInformation=dict(policyForm='Occurrence Form', territorialLimits='Worldwide excluding USA/Canada',
            insuredBusiness='Business', insuredProducts='Products', specialAgreementApplies='notApplicable',
            estimatedTurnover=[dict(region='USA/Canada', currency='USD', amount=1000000)]))


class Rollback(Exception):
    pass


try:
    with transaction.atomic():
        person = Personnel.objects.create(name='Coverage QA AE', email='qa@example.invalid', department='reinsurance', role_code='sales', created_by='qa', updated_by='qa')
        user = get_user_model().objects.create_user(username='cgl.coverage.qa', password='CGL-QA-only-9!')
        person.auth_user_id = str(user.pk); person.account_status = 'active'; person.save()
        client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)

        def call(method, path, body):
            client.get('/api/auth/csrf')
            return getattr(client, method)(path, data=json.dumps(body), content_type='application/json',
                HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)

        response = call('post', '/api/auth/login', dict(username=user.username, password='CGL-QA-only-9!'))
        assert response.status_code == 200, response.content
        base = ready(); base['ownerPersonnelId'] = person.pk
        for structure in ['QS', 'XOL']:
            p = {**base, 'reinsuranceStructure': structure, 'underlyingLimits': 'USD500,000'}
            value = normalize_draft(p)['value']
            check(structure + ' one coverage and blank SIR ready', not validate_announce_ready(value, allow_zero_loss_years=True))
        for missing in [[], None]:
            p = {**base, 'coverages': missing}
            result = normalize_draft(p)
            check('incomplete coverages can save ' + str(missing), not result['errors'], result['errors'])
            check('missing coverages blocks milestone ' + str(missing), any(i['field'] == 'coverages' for i in validate_announce_ready(result['value'])))
        for bad in ['Medical Payment', ['Unknown'], [None], [{}]]:
            check('invalid selection rejected ' + str(bad), bool(normalize_draft({**base, 'coverages': bad})['errors']))
        value = normalize_draft({**base, 'coverages': ['Other', COVERAGES[0], COVERAGES[0]], 'coveragesOther': '  Extra & liability\nLine 2  '})['value']
        check('selection de-duplicates in template order', value['coverages'] == [COVERAGES[0], 'Other'])
        check('Other retains multiline wording', value['coveragesOther'] == 'Extra & liability\nLine 2')
        check('Other-only accepted', not risk_details_issues({**base, 'coverages': ['Other'], 'coveragesOther': 'Extra liability'}))
        for blank in ['', ' \n\t ', '\ufeff']:
            check('Other requires nonblank text ' + repr(blank), risk_details_issues({**base, 'coverages': ['Other'], 'coveragesOther': blank})[0]['field'] == 'coveragesOther')
        for scope, patch in [('Property', dict(classOfBusiness='Property')), ('Treaty', dict(reinsuranceStructure='TREATY')),
                ('Facility', dict(reinsurers=[dict(name='QA (Facility)')])), ('PWS', dict(reinsurers=[dict(name='QA', foreignBroker='PWS')])),
                ('Swiss', dict(reinsurers=[dict(name='Swiss Re Asia Pte. Ltd.')]))]:
            check(scope + ' has no new requirements', not risk_details_issues({**base, **patch, 'coverages': []}))
        response = call('post', '/api/cases', {'case': {**base, 'coverages': []}})
        check('API saves incomplete coverage draft', response.status_code == 201, response.content[:400])
        uid = response.json()['case']['caseUid']; case = Case.objects.get(case_uid=uid)
        check('new field persisted as empty', case.payload['coverages'] == [])
        response = call('post', '/api/case-announce', dict(caseUid=uid, rowVersion=case.row_version, confirmed=True))
        check('Announce blocks no coverage', response.status_code == 400 and 'Coverages' in response.content.decode(), response.content[:400])
        response = call('put', '/api/cases', dict(caseUid=uid, rowVersion=case.row_version, case={**base, 'coverages': ['Other']}))
        check('API saves Other description pending draft', response.status_code == 200, response.content[:400]); case.refresh_from_db()
        response = call('post', '/api/case-announce', dict(caseUid=uid, rowVersion=case.row_version, confirmed=True))
        check('Announce blocks missing Other text', response.status_code == 400 and 'Coverages' in response.content.decode())
        complete = {**base, 'coverages': list(COVERAGES), 'coveragesOther': 'Extra & liability\nLine 2',
            'selfInsuredRetention': 'USD10,000 each claim\nCosts included'}
        response = call('put', '/api/cases', dict(caseUid=uid, rowVersion=case.row_version, case=complete))
        check('API saves all selections and optional SIR', response.status_code == 200, response.content[:400]); case.refresh_from_db()
        check('all coverage selections round-trip', case.payload['coverages'] == list(COVERAGES))
        check('Other wording round-trips', case.payload['coveragesOther'] == complete['coveragesOther'])
        check('SIR round-trips separately from RI retention', case.payload['selfInsuredRetention'] == complete['selfInsuredRetention'] and case.payload['reinsuredRetention'] == 'Advice waived')
        check('complete risk readiness', not validate_announce_ready(case.payload, allow_zero_loss_years=True))
        stored_complete = copy.deepcopy(case.payload)
        Case.objects.filter(pk=case.pk).update(status='posted', tw_ref='ZZ-COVERAGE-QA-001', announced_at=timezone.now())
        response = call('post', '/api/document-generation-log', dict(caseUid=uid, kind='cover', format='docx'))
        check('complete stored cover authorized', response.status_code == 204, response.content[:400])
        for patch in [dict(coverages=[]), dict(coverages=['Other'], coveragesOther='')]:
            stored = {**stored_complete, **patch}; Case.objects.filter(pk=case.pk).update(payload=stored)
            response = call('post', '/api/document-generation-log', dict(caseUid=uid, kind='cover', format='docx', **complete))
            check('Cover validates stored coverage despite request override ' + str(patch), response.status_code == 409 and response.json().get('error') == 'cgl_coverages_required', response.content[:400])
        Case.objects.filter(pk=case.pk).update(payload={**stored_complete, 'selfInsuredRetention': ''})
        response = call('post', '/api/document-generation-log', dict(caseUid=uid, kind='cover', format='docx'))
        check('blank SIR does not block Cover', response.status_code == 204, response.content[:400])
        raise Rollback()
except Rollback:
    pass
assert all(ok for _, ok, _ in checks), [row for row in checks if not row[1]]
print(f'cgl_coverages: {len(checks)} passed')
