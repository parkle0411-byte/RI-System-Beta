# HI: 案件 History 畫面測試資料（只在用完即丟的測試環境執行）：一件走 API 建立並 Announce 的案件、一件草稿。
import json
import uuid
from django.contrib.auth import get_user_model
from django.test import Client
from cases.models import Case, CaseDocument
from personnel.models import Personnel

c = Client(HTTP_HOST='localhost')
c.force_login(get_user_model().objects.get(username='ui.sales'))


def send(url, body):
    return c.post(url, data=json.dumps(body), content_type='application/json')


# 畫面建立的案件一律帶這幾個空欄位；少了它們，Announce 後存檔會被當成「改了不能改的欄位」
FORM_DEFAULTS = dict(
    cglInformation=dict(policyForm='', retroactiveDate='', extendedReportingApplies='', extendedReportingPeriod='', territorialLimits='',
                        territorialOther='', insuredBusiness='', insuredProducts='', estimatedTurnover=[], insuredWebsite='', specialAgreementApplies=''),
    stpHubs=[dict(name='', address='', currency='', amount=None)], stpTurnover=[dict(company='', currency='', amount=None)], stpTurnoverMode='combined')


def build(insured):
    r = send('/api/cases', {'case': dict(
        reinsuranceStructure='QS', ae='UI AE One', aePersonnelId=Personnel.objects.get(name='UI AE One').pk, basisOfValuation='Reinstatement Value', currency='USD', classOfBusiness='Property', classCode='PAR', newOrRenew='New',
        typePrefix='Commercial', reinsured='UI Cedant Insurance', originalInsured=insured, originalInsuredCn='畫面測試被保險人',
        policyFrom='2026-03-01', policyTo='2027-03-01', interest='Buildings', situations=[dict(address='1 UI Road', postcode='100')],
        reinsurers=[dict(name='UI Re Alpha', sharePct=100, premium=1000, riCommPct=5, taxPct=0, paymentTermsDays=30)],
        limitOfLiability=1000000, deductibles='10%', originalConditions='As original',
        occupation='Loc 1: Chemical Factory\n Loc 2: Outdoor Tank', construction='Concrete', constructionSelections=['A2 Class'],
        sumInsured=[dict(category='Building', amount=1000000)], lossAdvisedDate='2026-02-01', lossRecordYears=0, lossRecord=[],
        originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0, **FORM_DEFAULTS)})
    assert r.status_code == 201, r.content
    return Case.objects.get(case_uid=r.json()['case']['caseUid'])


case = build('UI History Insured')
docs = [CaseDocument.objects.create(case=case, kind=kind, reinsurers=names, filename=f'{kind}.pdf', content_type='application/pdf', byte_size=5,
                                    sha256='0' * 64, storage_key=f'ui-history-{uuid.uuid4()}', is_selected=True, uploaded_by='seed')
        for kind, names in (('offer', []), ('signed', ['UI Re Alpha']))]
r = send('/api/case-announce', {'caseUid': str(case.case_uid), 'rowVersion': case.row_version, 'confirmed': True,
                                'documentIds': [str(d.pk) for d in docs]})
assert r.status_code == 200, r.content
build('UI History Draft')
print('case history seeded')
