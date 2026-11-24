"""Isolated Product Recall validation and draft persistence checks."""
import copy, io, json, os, zipfile
from xml.etree import ElementTree as ET
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from cases.draft import normalize_draft, validate_announce_ready
from cases.draft_input import normalize as draft_normalize
from cases.product_recall import initial, ordered_rows

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    checks.append(bool(ok))
    print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ' ' + str(detail)))

risk = initial()
risk['choiceOfLaw'] = 'QA bespoke jurisdiction'
for item in risk['losses']:
    item['amount'] = 100
risk['events'].reverse()
risk['losses'].reverse()
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
    check('default sub-limit currency is stored in the draft', draft['value']['productRecall']['losses'][0]['currency'] == 'USD' and draft['value']['draftInput']['productRecall']['losses'][0]['currency'] == 'USD' and draft['value']['productRecall']['losses'][0]['currencyAuto'] is True)
    changed_case_currency = copy.deepcopy(draft['value']['draftInput'])
    changed_case_currency['currency'] = 'TWD'
    retained = draft_normalize(changed_case_currency)
    check('Case currency change preserves saved sub-limit currency', not retained['errors'] and retained['value']['productRecall']['losses'][0]['currency'] == 'USD', retained.get('errors'))
    cleared = copy.deepcopy(case); cleared['productRecall']['losses'][0]['currency'] = ''
    check('explicitly clearing sub-limit currency blocks saving', bool(draft_normalize(cleared)['errors']) and bool(normalize_draft(cleared)['errors']))
    result = normalize_draft(case)
    check('Product Recall normalizes without errors', not result['errors'], result['errors'])
    no_form = copy.deepcopy(case); no_form['cglInformation'].pop('policyForm')
    normal_new = normalize_draft(no_form); relaxed_new = draft_normalize(no_form)
    check('new Product Recall defaults Policy Form in normal and draft inputs', normal_new['value']['cglInformation']['policyForm'] == 'Occurrence Form' and relaxed_new['value']['draftInput']['cglInformation']['policyForm'] == 'Occurrence Form')
    blank_form = copy.deepcopy(case); blank_form['cglInformation']['policyForm'] = ''
    check('explicitly cleared Policy Form remains blank', normalize_draft(blank_form)['value']['cglInformation']['policyForm'] == '')
    renewal_no_form = copy.deepcopy(no_form); renewal_no_form['newOrRenew'] = 'Renew'; renewal_no_form['renewedFromTwRef'] = 'TWPR2601001'
    check('renewal missing Policy Form is not silently defaulted', normalize_draft(renewal_no_form, existing_premiums=case)['value']['cglInformation']['policyForm'] == '')
    extra_clause = {**case, 'manualClauses':[{'code':'LMA9999','title':'Not applicable'}], 'clauseDetails':[{'code':'LMA9999','title':'Not applicable'}]}
    fixed = draft_normalize(extra_clause)
    check('Product Recall keeps only its two fixed reinsurance clauses', not fixed['errors'] and fixed['value']['clauses'] == ['LMA3333','INTERMEDIARY']
          and fixed['value']['manualClauses'] == [] and fixed['value']['draftInput']['manualClauses'] == [], fixed.get('errors'))
    value = result['value']
    check('Product Recall type and class code are fixed', value.get('type') == 'Product Recall Facultative Reinsurance' and value.get('classCode') == 'PR')
    check('Product Recall fixed Interest is retained', value.get('interest') == 'Reinsurance of the Reinsured’s liability under the original policy.')
    ready = validate_announce_ready(value, allow_zero_loss_years=True)
    check('complete Product Recall is ready', not ready, ready)
    without_law = copy.deepcopy(value); without_law['productRecall']['choiceOfLaw'] = ''
    check('fixed jurisdiction is not an editable required field', not any(i['field'] == 'productRecall.choiceOfLaw' for i in validate_announce_ready(without_law, allow_zero_loss_years=True)))
    sample = [{'id':'event-3'}, {'id':'custom-b'}, {'id':'event-1'}, {'id':'custom-a'}, {'id':'event-2'}]
    check('standard order precedes custom items in their existing relative order', [x['id'] for x in ordered_rows(sample, 'events')] == ['event-1', 'event-2', 'event-3', 'custom-b', 'custom-a'])
    sample_case = copy.deepcopy(case)
    sample_risk = sample_case['productRecall']
    sample_risk['lossesOtherSelected'] = True
    sample_risk['losses'].append({'id': 'custom-1', 'name': ' Extra costs ', 'fixed': False, 'selected': True, 'currency': ' eur ', 'amount': 5000})
    sample_risk['losses'].append({'id': 'custom-2', 'name': 'Other costs', 'fixed': False, 'selected': True, 'currency': 'TWD', 'amount': 100})
    sample_risk['additionalSublimits'] = [{'id': 'unused', 'name': 'DO NOT DISPLAY', 'amount': 999}]
    saved = draft_normalize(sample_case)
    check('multiple Other loss entries retain currencies and trim names', not saved['errors'] and saved['value']['productRecall']['losses'][-2]['name'] == 'Extra costs' and saved['value']['productRecall']['losses'][-2]['currency'] == 'EUR', saved.get('errors'))
    check('additional sublimits removed from draft', 'additionalSublimits' not in saved['value']['productRecall'])
    bad = copy.deepcopy(sample_case); bad['productRecall']['losses'][-1]['name'] = 'extra COSTS'
    check('duplicate other names rejected while saving', bool(draft_normalize(bad)['errors']))
    invalid = copy.deepcopy(sample_case); invalid['productRecall']['losses'][-1]['amount'] = '1.50'
    check('TWD decimal amount rejected while saving', bool(draft_normalize(invalid)['errors']))
    hidden = copy.deepcopy(invalid); hidden['productRecall']['lossesOtherSelected'] = False
    check('hidden Other values are retained without validation', not draft_normalize(hidden)['errors'])
    hidden_value = normalize_draft(hidden)['value']
    check('normalization deactivates hidden Other even if an API row claims selected', not hidden_value['productRecall']['losses'][-1]['selected'])
    from cases.placing_word import document_values
    values = document_values(saved['value'], True)
    check('placing sublimits use each currency and omit additional items', 'EUR 5,000.00 in respect of Extra costs' in values['SUB-LIMITS'] and 'TWD 100 in respect of Other costs' in values['SUB-LIMITS'] and 'DO NOT DISPLAY' not in values['SUB-LIMITS'], values['SUB-LIMITS'])
    from cases.placing_word import render
    doc = render(case, 'qa@example.com')
    xml = zipfile.ZipFile(io.BytesIO(doc)).read('word/document.xml')
    root = ET.fromstring(xml)
    content = ' '.join(node.text or '' for node in root.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
    expected = ['COVERED EVENTS', 'Defect', 'COVERED LOSS', 'First Party Recall Costs',
                'LIMIT OF INDEMNITY', 'each occurrence and in the aggregate', 'in respect of',
                'each and every Insured Event', 'No previous recalls or product withdrawals since start selling.',
                'LSW3001 Premium Payment Clause', 'All other terms and conditions are as per the original policy wordings.',
                'exclusive jurisdiction of the Courts of the Republic of China, Taiwan']
    check('Product Recall Placing Slip contains its risk details and wording', all(s in content for s in expected) and 'BREAKDOWN OF SUM INSURED' not in content, content[:1000])
    check('Product Recall Placing Slip keeps risk order', content.index('COVERED EVENTS') < content.index('COVERED LOSS') < content.index('LIMIT OF INDEMNITY'))
    check('Placing Slip fixes standard event and loss order, and ignores saved jurisdiction', content.index('Defect') < content.index('Malicious Product Tampering') < content.index('Product Extortion') < content.index('Government Recall') and content.index('First Party Recall Costs') < content.index('Third Party Recall Costs') < content.index('Consultant and Advisor Costs') < content.index('Extortion Costs') and 'QA bespoke jurisdiction' not in content)
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
