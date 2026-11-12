"""Removal of retired handlers (2026-11-12). Disposable MySQL only.

The 13 retired Accounting actions still answer 410 (403 without Finance access), the Swiss statement
reference action is still dispatched, the old payment module and PDF route are gone.
"""
import importlib, json, os, uuid
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve, Resolver404
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, (name, detail)
    checks.append(name); print('PASS ' + name, flush=True)
def client(role, dept):
    u = get_user_model().objects.create_user(username='qa-retired-' + role, password='Qa-Retired-9!')
    Personnel.objects.create(name='QA Retired ' + role, department=dept, role_code=role, auth_user_id=str(u.pk),
                             account_status='active', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost', raise_request_exception=False); c.force_login(u); return c
fin, sales = client('accounting', 'finance'), client('sales', 'reinsurance')
def act(c, action, **body):
    return c.post('/api/accounting', json.dumps({'action': action, **body}), content_type='application/json')

RETIRED = ['record_allianz_claim_followup', 'record_great_american_claim_followup', 'record_qbe_claim_followup', 'edit_payment',
           'record_payment', 'reverse_payment', 'record_premium_offset', 'confirm_facility_settlement', 'unconfirm_facility_settlement',
           'confirm_swiss_collection', 'unconfirm_swiss_collection', 'record_swiss_clearance', 'record_swiss_offset']
check('thirteen retired actions', len(RETIRED) == 13)
for action in RETIRED:
    r = act(fin, action, caseUid=str(uuid.uuid4()), rowVersion=1)
    check(f'{action}: Finance gets 410 retired', r.status_code == 410 and r.json()['error'] == 'retired_accounting_action', r.content[:200])
    check(f'{action}: no Finance access gets 403', act(sales, action).status_code == 403)
r = act(fin, 'mark_swiss_statement', caseUid=str(uuid.uuid4()), rowVersion=1, scheduleKey='single:r1', reference='SWRPA-1')
check('Swiss statement reference is still an active action (reaches the case lookup)', r.status_code == 404 and r.json()['error'] == 'case_not_found', r.content[:200])
for action in ('review_accounts', 'cancel_review_batch', 'record_transaction_payments', 'reverse_batch_payment', 'record_claim_followup', 'complete_payment_terms'):
    r = act(fin, action)
    check(f'{action} is still handled (not retired, not unsupported)', r.status_code not in (410, 500) and r.json().get('error') != 'unsupported_action', r.content[:200])
check('unknown action is unsupported', act(fin, 'no_such_action').status_code == 400)

try:
    importlib.import_module('cases.transaction_payments'); gone = False
except ModuleNotFoundError:
    gone = True
check('the old payment module is removed', gone)
import cases.accounting_views as AV, cases.swiss_accounting as SW, cases.facility_accounting as FA
check('old single-payment methods are removed', not hasattr(AV.AccountingView, 'record_payment') and not hasattr(AV.AccountingView, 'reverse_payment'))
check('old offset and manual settlement handlers are removed', not hasattr(SW, '_offset') and not hasattr(FA, 'settlement_action'))
check('settlement display helpers are kept', all(hasattr(FA, n) for n in ('apply_schedules', 'apply_transactions', 'schedule_signature', 'tx_signature', 'state_for', 'is_confirmed')))
try:
    resolve('/api/render-document-pdf'); removed = False
except Resolver404:
    removed = True
check('the PDF route is removed', removed and resolve('/api/document-generation-log').func.view_class.__name__ == 'DocumentGenerationLogView')
print(f'{len(checks)}/{len(checks)} passed')
