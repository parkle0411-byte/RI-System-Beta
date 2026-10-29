"""2026-10-29 業主：Dashboard 跳過「帳款標記為整件已銷帳」的案件；Accounting 每次核對標記與實際收付款，不一致就列入警告。
只在拋棄式 QA 資料庫執行；所有變更在交易內回滾。"""
import copy
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client

from cases.accounting_policy import stored_all_settled, SETTLED_FLAG_WARNING
from cases.models import Case
from cases.property_original import enabled, refresh_transactions
from dashboard.calc import build_dashboard
from personnel.models import Personnel

assert os.environ.get('RI_DISPOSABLE_QA') == 'true'
checks = []
def check(name, ok, detail=''):
    assert ok, f'{name} {detail}'
    checks.append(name); print('PASS ' + name, flush=True)

TAIPEI = ZoneInfo('Asia/Taipei')
NOW = datetime.now(timezone.utc)
BASE = dict(reinsuranceStructure='QS', classOfBusiness='Property', classCode='PD', currency='TWD', originalPremium=100000,
            riCommPct=10, taxPct=1, paymentTermsDays=90, policyFrom='2026-01-15', policyTo='2027-01-15', reinsured='QA Cedant',
            reinsurers=[dict(name='QA Ordinary Re', sharePct=50, premium=100000, riCommPct=20, taxPct=1, paymentTermsDays=90)],
            transactions=[], paymentEntries=[], claims=[])

def payload(ref, flags):
    p = copy.deepcopy(BASE); p['twRef'] = ref
    assert enabled(p)
    stamp = NOW.isoformat()
    p['announcedAt'] = stamp
    refresh_transactions(p, stamp)
    for t, flag in zip(p['transactions'], flags(len(p['transactions']))):
        t['settlement'] = flag
    return p

def outstanding(*ps):
    rows = [{'id': i, 'parent_case_id': None, 'status': 'closed', 'payload': p, 'announced_at': None, 'created_at': None} for i, p in enumerate(ps, 1)]
    m = build_dashboard(rows, [], [], NOW, tz=TAIPEI, production_rules=True)['metrics']
    return round(m['outstandingLeg1Ntd'] + m['outstandingLeg2Ntd'], 2)

open_p = payload('QASKIP001', lambda n: ['open'] * n)
partly = payload('QASKIP002', lambda n: ['settled'] + ['open'] * (n - 1))
flagged = payload('QASKIP003', lambda n: ['settled'] * n)          # 標記全部已銷帳，但其實沒有任何收付款
reversed_p = payload('QASKIP004', lambda n: ['settled'] * n)
reversed_p['transactions'].append({**reversed_p['transactions'][0], 'txNo': 'QASKIP004-OLD', 'settlement': 'open', 'reversed': True})

check('helper: all live entries settled -> True; any open -> False; no entries -> False',
      stored_all_settled(flagged) and not stored_all_settled(open_p) and not stored_all_settled(partly) and not stored_all_settled({'transactions': []}))
check('helper: reversed entries are ignored', stored_all_settled(reversed_p))
full = outstanding(open_p)
check('an unsettled case is counted on the Dashboard', full > 0, full)
check('a partly settled case is still recomputed and counted', outstanding(partly) == full)
check('a case flagged fully settled is skipped on the Dashboard', outstanding(flagged) == 0)
check('skipping one case does not affect the others', outstanding(open_p, flagged, partly) == round(full * 2, 2))

with transaction.atomic():
    U = get_user_model()
    u = U.objects.create_user(username='zz.skip.fin', password='Skip-Probe-Pass-9!')
    Personnel.objects.create(name='ZZ Skip Fin', department='finance', role_code='accounting_manager', auth_user_id=str(u.pk),
                             account_status='active', created_by='qa', updated_by='qa')
    c = Client(HTTP_HOST='localhost'); c.force_login(u)
    made = {}
    for ref, p in (('QASKIP001', open_p), ('QASKIP002', partly), ('QASKIP003', flagged)):
        made[ref] = Case.objects.create(status='closed', tw_ref=ref, payload=p, currency='TWD', created_by='qa', updated_by='qa')
    for path in ('/api/accounting', '/api/accounting?view=list'):
        body = c.get(path).json()
        mine = {w['twRef']: w for w in body['warnings'] if SETTLED_FLAG_WARNING in (w.get('issues') or [])}
        check(f'{path}: the mismatched case is listed in warnings', set(mine) == {'QASKIP003'}, sorted(mine))
        check(f'{path}: its rows are still shown in full (nothing hidden in Accounting)',
              any(r['caseUid'] == str(made['QASKIP003'].case_uid) for r in body['transactionRows']))
    transaction.set_rollback(True)
print(f'{len(checks)}/{len(checks)} passed; database changes rolled back', flush=True)
