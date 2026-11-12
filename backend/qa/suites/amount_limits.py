"""Amount limits and malformed-list guards (owner decision 2026-11-12). Disposable MySQL only.

1. Premium / brokerage amounts are limited to +-999,999,999,999 on save (sum insured and limits are not).
2. A stored case with an out-of-range amount is reported as invalid data: the Account List and the case
   itself still open, other cases are unaffected, and no amount is computed for the damaged case.
3. `reinsurers` / `performanceInstallments` sent as a non-list value return 400, never a server error.
"""
import copy, json, os, uuid
from django.contrib.auth import get_user_model
from django.test import Client
from personnel.models import Personnel
from cases.models import Case
from cases.data_integrity import AMOUNT_MAX, financial_issues
from cases.calc.totals import case_totals, list_financials
from cases.draft import normalize_draft
from cases.property_original import money, totals as property_totals

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)

LIMIT = 999999999999
check('limit is 999,999,999,999', AMOUNT_MAX == LIMIT)

user = get_user_model().objects.create_user(username='qa-amount-limit', password='Qa-Amount-9!')
person = Personnel.objects.create(name='QA Amount Limit', department='reinsurance', role_code='sales', auth_user_id=str(user.pk),
                                  account_status='active', email='qa-amount@example.test', created_by='qa', updated_by='qa')
c = Client(HTTP_HOST='localhost', raise_request_exception=False); c.force_login(user)
def post(body): return c.post('/api/cases', json.dumps(body), content_type='application/json')
def put(body): return c.put('/api/cases', json.dumps(body), content_type='application/json')

def prop(**over):
    p = dict(classOfBusiness='Property', classCode='PF', typePrefix='Property', reinsuranceStructure='QS', currency='TWD',
             originalInsured='QA Amount Insured', originalInsuredCn='金額上限測試', reinsured='QA Amount Cedant', newOrRenew='New',
             policyFrom='2026-01-01', policyTo='2027-01-01', interest='Stock', situations=[{'address': 'Taipei', 'postcode': '100'}],
             sumInsured=[{'item': 'Building', 'amount': 1000000}], basisOfValuation='Actual Cash Value',
             originalPremium=1000, riCommPct=0, taxPct=1, paymentTermsDays=90,
             reinsurers=[{'name': 'QA Amount Re', 'sharePct': 20, 'premium': 1000, 'riCommPct': 10, 'taxPct': 0, 'paymentTermsDays': 90}],
             deductibles='TWD 1,000', originalConditions='A', reinsuredRetention='Waived', lossAdvisedDate='2026-01-01', lossRecordYears=5,
             ae=person.name, ownerPersonnelId=person.pk, ownerPersonnelName=person.name)
    p.update(over); return p
def with_reinsurer(**row):
    p = prop(); p['reinsurers'][0].update(row); return p

# ---- 1. Save-time limit ----
r = post({'case': prop(originalPremium=LIMIT)})
check('a premium exactly at the limit is accepted', r.status_code == 201, r.content[:300])
for label, body in (('100% Premium over the limit', prop(originalPremium=LIMIT + 1)),
                    ('100% Premium astronomically large', prop(originalPremium=1e30)),
                    ('100% Premium large numeric text', prop(originalPremium='1' + '0' * 30)),
                    ('Reinsurer Premium over the limit', with_reinsurer(premium=LIMIT + 1)),
                    ('Reinsurer Premium astronomically large', with_reinsurer(premium=1e30))):
    for incomplete in (False, True):
        before = Case.objects.count()
        r = post({'case': body, 'incompleteDraft': incomplete})
        stored = Case.objects.order_by('-id').first() if Case.objects.count() > before else None
        safe = r.status_code == 400 or (stored is not None and not financial_issues(stored.payload))
        check(f'{label} is rejected or kept out of the computed amounts (incomplete={incomplete})', r.status_code < 500 and safe,
              (r.status_code, r.content[:200]))
r = post({'case': prop(originalPremium=LIMIT + 1)})
check('the rejection names the field and the limit', r.status_code == 400 and '999999999999' in r.json().get('message', ''), r.content[:300])
errors = normalize_draft(prop(originalPremium=-5), allow_negative_premiums=True)['errors']
check('negative premiums stay allowed where they already were (endorsements)', not [e for e in errors if 'Premium' in e], errors)
errors = normalize_draft(prop(originalPremium=-(LIMIT + 1)), allow_negative_premiums=True)['errors']
check('negative premiums are limited too', any('100% Premium' in e for e in errors), errors)
p = prop(); p['sumInsured'] = [{'item': 'Building', 'amount': 5e15}]; p['aggregateLimit'] = 5e15
errors = normalize_draft(p)['errors']
check('sum insured and limits are not capped by the premium limit', not [e for e in errors if 'exceed' in e], errors)
check('installment premium is limited', any('Installment 1 Premium' in e for e in normalize_draft(prop(installmentEnabled=True,
      performanceInstallments=[dict(id='I1', premium=LIMIT + 1, paymentBaseDate='2026-01-01', paymentTermsDays=90)]))['errors']))

# ---- 2. Stored out-of-range data is invalid data, not a broken page ----
for bad in (LIMIT + 1, 1e26, 1e28, 1e30, '1' + '0' * 40, -1e30):
    for field in ('originalPremium', 'reinsurers.0.premium'):
        p = prop()
        if field == 'originalPremium': p['originalPremium'] = bad
        else: p['reinsurers'][0]['premium'] = bad
        before = copy.deepcopy(p)
        issues = financial_issues(p)
        check(f'out-of-range {field}={str(bad)[:12]} is reported as invalid data', any(i['field'] == field for i in issues), issues)
        check(f'out-of-range {field}={str(bad)[:12]} leaves totals pending and the payload untouched',
              all(v is None for v in case_totals(p).values()) and list_financials(p).get('dataError') is True and p == before)
        property_totals(p)   # must not raise
check('amounts at the limit are valid data', not financial_issues(prop(originalPremium=LIMIT)) and not financial_issues(with_reinsurer(premium=-LIMIT)))
check('ordinary totals are unchanged', case_totals(prop())['cedantPremium'] is not None and not financial_issues(prop()))
check('money() never raises on astronomically large values', money(1e30, {'currency': 'TWD'}) == 0.0 and money('9' * 60, {'currency': 'USD'}) == 0.0
      and money(1234.5, {'currency': 'TWD'}) == 1235.0 and money(1234.567, {'currency': 'USD'}) == 1234.57)

good = post({'case': prop(originalInsured='QA Healthy Neighbour')}); assert good.status_code == 201, good.content[:300]
poisoned = post({'case': prop(originalInsured='QA Poisoned Draft')}); assert poisoned.status_code == 201
row = Case.objects.get(case_uid=poisoned.json()['case']['caseUid'])
for bad in (1e30, 1e27):   # written directly, as legacy rows or a direct database edit could be
    payload = copy.deepcopy(row.payload); payload['originalPremium'] = bad; payload['reinsurers'][0]['premium'] = bad
    if isinstance(payload.get('draftInput'), dict):
        payload['draftInput']['originalPremium'] = bad
    Case.objects.filter(pk=row.pk).update(payload=payload)
    listing = c.get('/api/cases')
    check(f'Account List still opens with a damaged draft ({bad:g})', listing.status_code == 200, listing.content[:200])
    rows_ = {x['caseUid']: x for x in listing.json()['cases']}
    check(f'only the damaged case is flagged ({bad:g})', rows_[str(row.case_uid)].get('dataError') is True
          and not rows_[good.json()['case']['caseUid']].get('dataError') and rows_[good.json()['case']['caseUid']]['ourSharePremium'] is not None)
    for url in (f'/api/cases?caseUid={row.case_uid}', f'/api/case-workflow?caseUid={row.case_uid}', f'/api/case-documents?caseUid={row.case_uid}',
                '/api/dashboard', '/api/accounting?view=list'):
        res = c.get(url)
        check(f'{url.split("?")[0]} does not fail with a damaged draft ({bad:g})', res.status_code < 500, (url, res.status_code))
    row.refresh_from_db()
    res = c.post('/api/case-announce', json.dumps({'caseUid': str(row.case_uid), 'rowVersion': row.row_version, 'confirmed': True}), content_type='application/json')
    check(f'a damaged draft cannot be announced ({bad:g})', res.status_code in (400, 409), (res.status_code, res.content[:200]))
row.refresh_from_db()
fixed = copy.deepcopy(prop(originalInsured='QA Poisoned Draft'))
res = put({'caseUid': str(row.case_uid), 'rowVersion': row.row_version, 'case': fixed})
check('the damaged draft can be corrected through the normal form', res.status_code == 200, res.content[:300])
row.refresh_from_db()
check('after correction the case is valid again', not financial_issues(row.payload) and c.get('/api/cases').status_code == 200)

# ---- 3. Non-list rows ----
for value in (5, 10 ** 30, 1.5, True, 'abc'):
    for incomplete in (False, True):
        r = post({'case': prop(reinsurers=value), 'incompleteDraft': incomplete})
        # A non-list is either rejected (400) or, as before for other containers, replaced by well-formed blank rows; never a server error.
        stored = Case.objects.get(case_uid=r.json()['case']['caseUid']).payload if r.status_code == 201 else None
        check(f'reinsurers={value!r} never causes a server error or a malformed stored list (incomplete={incomplete})',
              r.status_code == 400 or (stored is not None and isinstance(stored.get('reinsurers'), list) and all(isinstance(x, dict) for x in stored['reinsurers']) and not financial_issues(stored)), (r.status_code, r.content[:200]))
OVERSEA = dict(reinsuranceStructure='OVERSEA', classOfBusiness='Fine Art', classCode='FA', currency='USD', reinsured='QA Amount Cedant',
               originalPremium=1000, receiptPaymentDate='2026-06-01', ae=person.name, ownerPersonnelId=person.pk, ownerPersonnelName=person.name,
               originalInsured='QA Oversea', originalInsuredCn='海外', policyFrom='2026-01-01', policyTo='2027-01-01',
               reinsurers=[{'name': 'QA Oversea Broker', 'sharePct': 25, 'brokerageAmount': 100}])
for value in (-1, 1e25, 7, 2.5, 'abc', True):
    r = post({'case': {**OVERSEA, 'installmentEnabled': True, 'performanceInstallments': value}})
    check(f'Oversea performanceInstallments={value!r} never causes a server error', r.status_code < 500, (r.status_code, r.content[:200]))
for label, patch in (('Oversea Brokerage over the limit', {'reinsurers': [{'name': 'QA Oversea Broker', 'sharePct': 25, 'brokerageAmount': LIMIT + 1}]}),
                     ('Oversea negative Brokerage over the limit', {'reinsurers': [{'name': 'QA Oversea Broker', 'sharePct': 25, 'brokerageAmount': -1e30}]}),
                     ('Oversea 100% Premium over the limit', {'originalPremium': 1e30})):
    r = post({'case': {**OVERSEA, **patch}})
    check(f'{label} is rejected', r.status_code == 400, (r.status_code, r.content[:200]))
    check(f'{label} is invalid data if stored', bool(financial_issues({**OVERSEA, **patch})))
check('Oversea premium adjustment is limited', any('100% Premium Adjustment' in e for e in normalize_draft(
      {**OVERSEA, 'parentTwRef': 'TWFA2601001', 'premiumAdjustment': -(LIMIT + 1)}, allow_negative_premiums=True)['errors']))
print(f'{len(checks)}/{len(checks)} passed')
