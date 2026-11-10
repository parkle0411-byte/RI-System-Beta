from qa.finance_fixtures import review_case
import copy
import json
import uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog, EntitySnapshot
from cases.calc.jsnum import money
from cases.calc.payment_terms import build_payment_schedule, taipei_date
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from cases.models import Case
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=kw.pop("name", f"ZZ ACC {role} {_seq[0]}"), department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.acc.{tag}", password="Acc-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Acc-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Acc Cedant", originalInsured="ZZ Acc Insured", originalInsuredCn='合成測試被保險人', policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0, paymentTermsDays=30), dict(name="ZZ Re B", sharePct=40, premium=400, riCommPct=5, taxPct=0, paymentTermsDays=30)],   # 2026-10-16：每家再保人天數獨立填寫、不繼承
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction='Concrete', constructionSelections=['A2 Class'],
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make_case(c, status="posted", **over):
    r = call(c, "post", "/api/cases", {"case": ready(**over)}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
    if status != "draft":
        _ref[0] += 1
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-ACC-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db()
    if status != 'draft' and not case.payload.get('transactions'):
        payload=copy.deepcopy(case.payload);payload['twRef']=case.tw_ref;payload['transactions']=build_premium_transactions(payload);case.payload=payload;case.save()
    review_case(case,globals().get('fin'))
    return case
def ledger(c, case=None):
    r = call(c, "get", "/api/accounting"); j = r.json()
    rows = [x for x in j.get("rows", []) if case is None or x["caseUid"] == str(case.case_uid)]
    return r, j, rows
def post(c, action, case, **extra):
    body = {"action": action, "caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version, **extra}
    return call(c, "post", "/api/accounting", body)
def pay(c, case, key, amount, date="2026-09-20", **extra): return post(c, "record_payment", case, scheduleKey=key, amount=amount, paymentDate=date, **{'note':'QA synthetic registration',**extra})
def audit(uid, action=None):
    q = AuditLog.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(action=action) if action else q
def snaps(uid, reason=None):
    q = EntitySnapshot.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(snapshot_reason=reason) if reason else q

# Retired schedule APIs are covered by current retirement/immutable-history checks.
try:
    exec(__import__('pathlib').Path('/app/qa/suites/finance_retired_contract.py').read_text())
except Exception:
    raise
