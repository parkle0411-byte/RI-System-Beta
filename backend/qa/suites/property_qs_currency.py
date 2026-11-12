"""Property Quota Share currency is limited to TWD or USD (2026-11-11), through the real Case API."""
import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from cases.models import Case
from cases.draft import validate_announce_ready
from cases.property_qs_currency import MESSAGE
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass

def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf")
    kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(tag):
    p = Personnel.objects.create(name=f"ZZ PQC {tag}", department="reinsurance", role_code="sales", created_by="t", updated_by="t")
    u = User.objects.create_user(username=f"zz.pqc.{tag}", password="Case-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Case-Test-Pass-1"}),
               content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def body(**over):
    base = dict(originalInsured="ZZ PQC Insured", reinsured="ZZ Cedant", classOfBusiness="Property", reinsuranceStructure="QS",
                currency="USD", policyFrom="2026-01-01", policyTo="2026-12-31", originalPremium=1000, riCommPct=10, taxPct=0,
                paymentTermsDays=30, lossAdvisedDate="2026-01-01", lossRecordYears=5,
                reinsurers=[dict(name="ZZ Re", sharePct=100, premium=1000, riCommPct=5, taxPct=0)])
    base.update(over); return base
def post(c, incomplete=True, **over):
    return call(c, "post", "/api/cases", {"case": body(**over), **({"incompleteDraft": True} if incomplete else {})})
def put(c, uid, version, case_body, incomplete=True):
    return call(c, "put", "/api/cases", {"caseUid": uid, "rowVersion": version, "case": case_body, **({"incompleteDraft": True} if incomplete else {})})
def has_msg(r): return MESSAGE in r.content.decode("utf-8", "replace")

try:
    with transaction.atomic():
        sales = account("sales")

        for cur in ("EUR", "JPY", "GBP", "HKD", "MYR"):
            r = post(sales, currency=cur)
            check(f"incomplete Property QS Draft in {cur} is refused", r.status_code == 400 and has_msg(r), (r.status_code, r.content[:300]))
            r = post(sales, incomplete=False, currency=cur)
            check(f"full Property QS save in {cur} is refused", r.status_code == 400 and has_msg(r), (r.status_code, r.content[:300]))
        r = post(sales, currency="eur")
        check("lower-case eur is refused too", r.status_code == 400 and has_msg(r), (r.status_code, r.content[:300]))
        r = post(sales, incomplete=False, reinsuranceStructure="FACULTATIVE", currency="EUR")
        check("old FACULTATIVE alias is covered", r.status_code == 400 and has_msg(r), (r.status_code, r.content[:300]))

        uids = {}
        for cur in ("TWD", "USD", ""):
            r = post(sales, currency=cur)
            check(f"incomplete Property QS Draft with currency {cur or 'blank'} is saved", r.status_code == 201, (r.status_code, r.content[:300]))
            if r.status_code == 201: uids[cur] = r.json()["case"]["caseUid"]
        r = post(sales, incomplete=False, currency="USD")
        check("full Property QS save in USD is not blocked by the currency rule", not has_msg(r), (r.status_code, r.content[:300]))

        r = call(sales, "post", "/api/cases", {"case": body(classOfBusiness="ZZ Class", currency="EUR")})
        check("other classes keep their other currencies", not has_msg(r), (r.status_code, r.content[:300]))

        # Existing Draft that already holds an unsupported currency (before the rule): must be replaced, not kept or blanked.
        uid = uids.get("USD")
        if uid:
            row = Case.objects.get(case_uid=uid)
            row.payload = {**row.payload, "currency": "EUR"}; row.currency = "EUR"; row.save()
            row.refresh_from_db()
            r = put(sales, uid, row.row_version, body(currency="EUR"))
            check("existing EUR Draft cannot be saved again in EUR", r.status_code == 400 and has_msg(r), (r.status_code, r.content[:300]))
            r = put(sales, uid, row.row_version, body(currency=""))
            check("existing EUR Draft cannot be saved by blanking the currency", r.status_code == 400 and has_msg(r), (r.status_code, r.content[:300]))
            r = put(sales, uid, row.row_version, body(currency="TWD"))
            check("existing EUR Draft saves once changed to TWD", r.status_code == 200, (r.status_code, r.content[:300]))
            row.refresh_from_db()
            check("changed currency is stored", row.payload.get("currency") == "TWD" and row.currency == "TWD", (row.payload.get("currency"), row.currency))
        else:
            check("USD Draft available for the existing-case checks", False)

        blank = uids.get("")
        if blank:
            row = Case.objects.get(case_uid=blank)
            r = put(sales, blank, row.row_version, body(currency=""))
            check("blank new Draft can be saved again while blank", r.status_code == 200, (r.status_code, r.content[:300]))

        ready = lambda **over: [i["label"] for i in validate_announce_ready(body(**over))]
        check("Announce readiness requires a currency", MESSAGE in ready(currency=""))
        check("Announce readiness refuses EUR", MESSAGE in ready(currency="EUR"))
        check("Announce readiness refuses EUR on an endorsement", MESSAGE in ready(currency="EUR", parentTwRef="TW-1"))
        check("Announce readiness accepts TWD and USD", MESSAGE not in ready(currency="TWD") and MESSAGE not in ready(currency="USD"))
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed Property QS currency checks; database changes rolled back")
