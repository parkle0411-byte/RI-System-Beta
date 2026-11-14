"""Isolated Product Recall validation and draft persistence checks."""
import copy, io, json, os, zipfile
from xml.etree import ElementTree as ET
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.draft import normalize_draft, validate_announce_ready
from cases.draft_input import normalize as draft_normalize
from cases.product_recall import initial

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    checks.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ' ' + str(detail)))

risk = initial()
risk['choiceOfLaw'] = 'QA bespoke jurisdiction'
for item in risk['losses']:
    item['amount'] = 100
case = {'classOfBusiness': 'Product Recall', 'classCode': 'PR', 'reinsuranceStructure': 'QS', 'newOrRenew': 'New', 'currency': 'USD',
        'ownerPersonnelId': 1, 'ae': 'QA', 'originalInsured': 'Test', 'originalInsuredCn': '測試', 'reinsured': 'Cedant',
        'policyFrom': '2026-01-01', 'policyTo': '2027-01-01', 'situations': [], 'interest': '',
        'limitOfLiability': 1000, 'deductibles': '10', 'selfInsuredRetention': '', 'originalConditions': 'As original',
        'originalExclusions': 'None', 'reinsuredRetention': 'Waived', 'expressWarranties': 'None',
        'conditionsPrecedent': 'None', 'subjectivities': 'None', 'productRecall': risk,
        'lossAdvisedDate': '2026-01-01', 'lossRecordYears': 0, 'lossRecord': [],
        'originalPremium': 100, 'riCommPct': 0, 'taxPct': 0, 'paymentTermsDays': 90,
        'reinsurers': [{'name':'Example', 'sharePct':100, 'premium':100, 'riCommPct':0, 'taxPct':0, 'paymentTermsDays':90}],
        'cglInformation': {'policyForm':'Occurrence Form', 'territorialLimits':'Worldwide including USA/Canada',
            'insuredBusinessSelections':['Manufacturer'], 'insuredProducts':'Products',
            'estimatedTurnover':[{'region':'USA/Canada','currency':'USD','amount':100}], 'specialAgreementApplies':'notApplicable'}}
with transaction.atomic():
    from masterdata.models import MasterRecord
    from cases.resolve import resolve_master_references
    master = MasterRecord.objects.filter(entity_type='class', name='Product Recall', code='PR', is_active=True).first()
    check('Product Recall is an independent active Insurance Type', bool(master) and resolve_master_references(case)['classMasterId'] == master.pk)
    draft = draft_normalize(case)
    check('Product Recall incomplete draft retains risk details', not draft['errors'] and draft['value']['productRecall']['losses'][0]['amount'] == 100, draft.get('errors'))
    result = normalize_draft(case)
    check('Product Recall normalizes without errors', not result['errors'], result['errors'])
    extra_clause = {**case, 'manualClauses':[{'code':'LMA9999','title':'Not applicable'}], 'clauseDetails':[{'code':'LMA9999','title':'Not applicable'}]}
    fixed = draft_normalize(extra_clause)
    check('Product Recall keeps only its two fixed reinsurance clauses', not fixed['errors'] and fixed['value']['clauses'] == ['LMA3333','INTERMEDIARY']
          and fixed['value']['manualClauses'] == [] and fixed['value']['draftInput']['manualClauses'] == [], fixed.get('errors'))
    value = result['value']
    check('Product Recall type and class code are fixed', value.get('type') == 'Product Recall Facultative Reinsurance' and value.get('classCode') == 'PR')
    check('Product Recall fixed Interest is retained', value.get('interest') == 'Reinsurance of the Reinsured’s liability under the original policy.')
    ready = validate_announce_ready(value, allow_zero_loss_years=True)
    check('complete Product Recall is ready', not ready, ready)
    from cases.placing_word import render
    doc = render(case, 'qa@example.com')
    xml = zipfile.ZipFile(io.BytesIO(doc)).read('word/document.xml')
    root = ET.fromstring(xml)
    content = ' '.join(node.text or '' for node in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
    expected = ['COVERED EVENTS', 'Defect', 'COVERED LOSS', 'First Party Recall Costs',
                'LIMIT OF INDEMNITY', 'each occurrence and in the aggregate', 'in respect of',
                'each and every Insured Event', 'No previous recalls or product withdrawals since start selling.',
                'LSW3001 Premium Payment Clause', 'All other terms and conditions are as per the original policy wordings.',
                'QA bespoke jurisdiction']
    check('Product Recall Placing Slip contains its risk details and wording', all(s in content for s in expected) and 'BREAKDOWN OF SUM INSURED' not in content, content[:1000])
    check('Product Recall Placing Slip keeps risk order', content.index('COVERED EVENTS') < content.index('COVERED LOSS') < content.index('LIMIT OF INDEMNITY'))
    from cases import placing_rules
    from cases.placing_views import signature
    placing_case = placing_rules.promote(copy.deepcopy(case))
    check('Product Recall is eligible for ordinary Placing Slip', placing_rules.enabled(placing_case) and placing_rules.has_ordinary(placing_case))
    missing_retention = copy.deepcopy(placing_case)
    missing_retention['reinsuredRetention'] = ''
    check('Product Recall retention remains required with placing rules enabled', any(i['field'] == 'reinsuredRetention' for i in validate_announce_ready(missing_retention, allow_zero_loss_years=True)))
    changed = copy.deepcopy(placing_case)
    changed['productRecall']['losses'][0]['amount'] = 200
    check('Product Recall risk edits invalidate existing Placing Slips', signature(placing_case) != signature(changed))
    from personnel.models import Personnel
    from cases.models import Case, CaseDocument
    user = get_user_model().objects.create_user(username='qa.product.recall', password='QA-Test-123!')
    creator = Personnel.objects.create(name='QA Product Recall Staff', department='reinsurance', role_code='sales', email='qa.recall@example.test', auth_user_id=str(user.pk), account_status='active', created_by='qa', updated_by='qa')
    client = Client(enforce_csrf_checks=True, HTTP_HOST='localhost', raise_request_exception=False)
    client.force_login(user); client.get('/api/auth/csrf')
    def post(path, body):
        return client.post(path, data=json.dumps(body), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
    submitted = {**case, 'ownerPersonnelId':creator.pk, 'aePersonnelId':creator.pk, 'ae':creator.name}
    response = post('/api/cases', {'case':submitted, 'incompleteDraft':True})
    check('Product Recall API creates a draft', response.status_code == 201, response.content[:500])
    if response.status_code == 201:
        root = Case.objects.get(case_uid=response.json()['case']['caseUid'])
        files=[]
        for kind, reinsurers in [('offer', []), ('signed', ['Example'])]:
            doc = CaseDocument.objects.create(case=root, kind=kind, reinsurers=reinsurers, filename=kind+'.pdf', content_type='application/pdf', byte_size=1, sha256='a'*64, storage_key='qa-recall-'+kind, is_selected=True, uploaded_by='qa')
            files.append(str(doc.pk))
        response = post('/api/case-announce', {'caseUid':str(root.case_uid), 'rowVersion':root.row_version, 'confirmed':True, 'documentIds':files})
        root.refresh_from_db()
        check('Product Recall announces with its PR reference', response.status_code == 200 and root.tw_ref == 'TWPR2601001', response.content[:700])
        if response.status_code == 200:
            root.status = 'closed'; root.save(update_fields=['status'])
            renewal = post('/api/case-workflow', {'action':'create_renewal', 'caseUid':str(root.case_uid), 'rowVersion':root.row_version})
            check('Product Recall renewal inherits risk selections', renewal.status_code == 201 and renewal.json()['case']['payload']['productRecall']['losses'][0]['amount'] == 100, renewal.content[:600])
            endorsement = post('/api/case-workflow', {'action':'create_endorsement', 'caseUid':str(root.case_uid), 'rowVersion':root.row_version})
            check('Product Recall endorsement inherits risk selections', endorsement.status_code == 201 and endorsement.json()['case']['payload']['productRecall']['events'][0]['selected'] is True, endorsement.content[:600])
    transaction.set_rollback(True)
print(f'{sum(checks)}/{len(checks)} Product Recall checks passed')
