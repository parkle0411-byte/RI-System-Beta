from django.contrib.auth import get_user_model
from personnel.models import Personnel
from legacy.models import LegacyTransaction
from django.utils import timezone
for role,tag,name in [('sales','sales','UI Legacy Sales'),('accounting','finance','UI Legacy Finance')]:
    u=get_user_model().objects.create_user(username='ui.legacy.'+tag,password='Ui-Test-Pass-1')
    Personnel.objects.create(name=name,department='reinsurance' if role=='sales' else 'finance',role_code=role,
        auth_user_id=str(u.pk),account_status='active',created_by='qa',updated_by='qa')
LegacyTransaction.objects.create(number='UI-OLD-1',original_serial='UI-OLD-1',reference='UI-LEGACY-REF',status='confirmed',historical=True,
    currency='TWD',data=dict(reference='UI-LEGACY-REF',kind='premium',insured='UI Legacy Insured',insuredCn='測試被保險人',cedant='UI Cedant Insurance',
        party='UI Re Alpha',ae='UI Legacy Sales',currency='TWD',share=100,rule='ordinary',cedantDays=90,reinsurerDays=90,
        effectiveDate='2020-01-01',expiryDate='2020-12-31',amounts=dict(premium=1000,commission=100,tax=10,brokerage=50,claim=0,cedantNet=890,reinsurerNet=840)),
    fx_snapshot=dict(rate=1,incomeTwd=50,premiumTwd=1000,people=[dict(name='UI Legacy Sales',income=50)]),first_confirmed_at=timezone.now())
print('Legacy UI fixtures seeded')
