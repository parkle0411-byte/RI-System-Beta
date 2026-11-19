# V：一件 Swiss Re Asia（Facility）案件與一件一般再保人案件，供 Reinsurance Staff 審核畫面測試（2026-11-19）。
from django.utils import timezone
from cases.models import Case
from cases.property_original import transactions
def make(ref, reinsurer, premium=1000, claim=False):
    p = {'currency': 'USD', 'reinsured': 'UI Facility Cedant', 'originalInsured': 'UI Facility Insured ' + ref, 'originalInsuredCn': '畫面測試保戶',
         'classCode': 'PD', 'classOfBusiness': 'Property', 'reinsuranceStructure': 'QS', 'policyFrom': '2026-09-01', 'policyTo': '2027-09-01',
         'paymentTermsDays': 90, 'originalPremium': premium, 'riCommPct': 0, 'taxPct': 0, 'premiumLedgerLayout': 'per-reinsurer-v1',
         'accountingRules': 'accounting-v1', 'financeWorkflowVersion': 'finance-review-v1',
         'reinsurers': [{'name': reinsurer, 'sharePct': 100, 'premium': premium, 'riCommPct': 20, 'taxPct': 0, 'paymentTermsDays': 90}],
         'paymentEntries': [], 'claims': [], 'twRef': ref, 'announcedAt': '2026-09-01T00:00:00Z'}
    p['transactions'] = transactions(p, '2026-09-01T00:00:00Z')
    if claim:   # 理賠：T1＝向再保人收、T2＝付給 Cedant（對象名稱與系統產生的理賠帳款相同）
        for leg in (1, 2):
            p['transactions'].append({'txNo': f'{ref}-C1-P1-R1-T{leg}', 'source': 'claim', 'legType': f'Claim Leg {leg}', 'claimId': 1, 'paymentId': 1,
                'reinsurerIdx': 0, 'reinsurer': 'Swiss Re Asia Pte. Ltd., Hong Kong Branch', 'amount': 300, 'createdAt': '2026-11-01T00:00:00Z', 'dueDate': '2026-11-16'})
    Case.objects.create(tw_ref=ref, status='posted', currency='USD', reinsured_name_snapshot='UI Facility Cedant', payload=p,
                        announced_at=timezone.now(), created_by='ui-seed', updated_by='ui-seed')
make('UIFR-SW-1', 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)', claim=True)
make('UIFR-OR-1', 'UI Ordinary Reinsurer')
make('UIFR-SW-2', 'Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)', -1000)   # 退保：向 Swiss Re 收回保費（應收）
# 專用的 Reinsurance Staff 測試帳號（ui.sales 的密碼會在前面的重設密碼階段被改掉）
from django.contrib.auth import get_user_model
from personnel.models import Personnel
u = get_user_model().objects.create_user(username='ui.facility.rs', password='Ui-Facility-Pass-1')
Personnel.objects.create(name='UI Facility Reviewer', department='reinsurance', role_code='sales', auth_user_id=str(u.pk),
                         account_status='active', must_change_password=False, email='ui.facility.rs@example.test',
                         created_by='ui-seed', updated_by='ui-seed')
print('facility review cases seeded')
