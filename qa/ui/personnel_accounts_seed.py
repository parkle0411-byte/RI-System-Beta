# U: a synthetic person with an active login account for the account-lifecycle checks (2026-11-17).
from django.contrib.auth import get_user_model
from personnel.models import Personnel
u = get_user_model().objects.create_user(username='ui.lifecycle', password='Ui-Lifecycle-Pass-1')
Personnel.objects.create(name='UI Account Lifecycle', department='reinsurance', role_code='sales', auth_user_id=str(u.pk),
                         account_status='active', email='ui.lifecycle@example.test', created_by='ui-seed', updated_by='ui-seed')
print('personnel account lifecycle seeded')
