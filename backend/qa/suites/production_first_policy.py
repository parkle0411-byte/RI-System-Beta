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
from cases.models import Case
from fxrates.models import FxRate
from production.models import ProductionExclusion, ProductionReport
from django.db import IntegrityError, DatabaseError
from datetime import datetime, timezone as tz
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=kw.pop("name", f"ZZ FPN {role} {_seq[0]}"), department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.fpn.{tag}", password="Fpn-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Fpn-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Prd Cedant", originalInsured="ZZ Prd Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0)],
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
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-FPN-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case
URL = "/api/production-report"
M1, M2, M3, M4 = "2031-05", "2031-06", "2031-07", "2031-08"   # 遠在未來的月份：真實案件不會落在這裡
def get(c, month): return call(c, "get", f"{URL}?month={month}")

def post(c, action, month, **extra): return call(c, "post", URL, {"action": action, "month": month, **extra})
from production import calc as prod
MONTH = "2031-09"
EARLY = datetime(2026, 9, 1, 4, 0, tzinfo=tz.utc)

def chain_case(sales, tw_ref, name, **payload):
    case = make_case(sales, "posted", originalInsured=name, policyFrom="2031-09-01", policyTo="2032-09-01", currency="TWD")
    p = copy.deepcopy(case.payload); p.update(payload)
    Case.objects.filter(pk=case.pk).update(tw_ref=tw_ref, payload=p, announced_at=EARLY)
    case.refresh_from_db(); return case

try:
    with transaction.atomic():
        # ===== 純函式：連結表與追溯 =====
        links = prod.reference_links([
            ("A", {}), ("A-E1", {"parentTwRef": "A"}), ("B", {"renewedFromTwRef": "A"}), ("B-E1", {"parentTwRef": "B"}),
            ("C", {"renewedFromTwRef": "B-E1"}), ("X", {"renewedFromTwRef": "Y"}), ("Y", {"renewedFromTwRef": "X"}),
            ("S", {"parentTwRef": "S"}), ("P2", {"previousTwRefs": ["P1"]}), ("Q", {"renewedFromTwRef": "P1"}),
            ("L", {"renewedFromTwRef": "GONE"}), ("N", None), (None, {"renewedFromTwRef": "A"}), ("  ", {}), ("W", {"parentTwRef": 5, "renewedFromTwRef": ["A"]}),
        ])
        f = lambda ref: prod.first_policy_no(ref, links)
        check("unit: original policy -> itself", f("A") == "A")
        check("unit: endorsement -> original policy", f("A-E1") == "A")
        check("unit: renewal -> source", f("B") == "A")
        check("unit: endorsement of a renewal -> first policy", f("B-E1") == "A")
        check("unit: renewal made from an endorsement -> first policy", f("C") == "A")
        check("unit: source missing -> last known number", f("L") == "GONE")
        check("unit: unknown number -> itself", f("NOPE") == "NOPE")
        check("unit: empty / None / blank -> ''", f("") == "" and f(None) == "" and f("   ") == "")
        check("unit: renewal loop terminates", f("X") in ("X", "Y") and f("Y") in ("X", "Y"))
        check("unit: case that points to itself terminates", f("S") == "S")
        check("unit: old TW Ref (previousTwRefs) resolves to the current number", f("Q") == "P2" and f("P1") == "P2")
        check("unit: bad payload shapes ignored (payload None, non-text refs)", f("N") == "N" and f("W") == "W")
        check("unit: case without TW Ref contributes no link", None not in links and "" not in links)

        sales_p, finm_p = person("sales", "reinsurance"), person("accounting_manager", "finance")
        sales, finm = account(sales_p, "sales"), account(finm_p, "finm")

        # ===== 實際案件：改名的批單與續保仍歸在同一個首次承保號碼 =====
        a = chain_case(sales, "ZZ-FPN-A", "ZZ Old Name Ltd")
        e1 = chain_case(sales, "ZZ-FPN-A-E1", "ZZ Changed Name Ltd", parentTwRef="ZZ-FPN-A", endorsementSeq=1)
        b = chain_case(sales, "ZZ-FPN-B", "ZZ New Name Ltd", renewedFromTwRef="ZZ-FPN-A", newOrRenew="Renew")
        e2 = chain_case(sales, "ZZ-FPN-B-E1", "ZZ Newer Name Ltd", parentTwRef="ZZ-FPN-B", endorsementSeq=1)
        c = chain_case(sales, "ZZ-FPN-C", "ZZ Third Name Ltd", renewedFromTwRef="ZZ-FPN-B-E1", newOrRenew="Renew")
        d = chain_case(sales, "ZZ-FPN-D", "ZZ Old Name Ltd")                      # 同名但不同案子：不可被併進 A
        m = chain_case(sales, "ZZ-FPN-M", "ZZ Orphan Ltd", renewedFromTwRef="ZZ-FPN-MISSING", newOrRenew="Renew")
        g = chain_case(sales, "ZZ-FPN-G", "ZZ Middle Ltd", renewedFromTwRef="ZZ-FPN-A", newOrRenew="Renew")
        h = chain_case(sales, "ZZ-FPN-H", "ZZ Last Ltd", renewedFromTwRef="ZZ-FPN-G", newOrRenew="Renew")
        Case.objects.filter(pk=g.pk).update(is_archived=True, archived_by="ZZ FPN", archived_at=timezone.now())                   # 中間那張被封存：不在報表裡，但鏈不能斷

        j = call(finm, "get", f"{URL}?month={MONTH}").json()
        rows = {r["caseUid"]: r for r in j["rows"]}
        want = {a: "ZZ-FPN-A", e1: "ZZ-FPN-A", b: "ZZ-FPN-A", e2: "ZZ-FPN-A", c: "ZZ-FPN-A", d: "ZZ-FPN-D", m: "ZZ-FPN-MISSING", h: "ZZ-FPN-A"}
        got = {k.tw_ref: rows[str(k.case_uid)]["firstPolicyNo"] for k in want if str(k.case_uid) in rows}
        check("preview contains every non-archived chain case", len(got) == len(want), f"{len(got)}/{len(want)}")
        check("every row carries First Policy No as expected", all(got.get(k.tw_ref) == v for k, v in want.items()), got)
        check("archived middle case is not in the report", str(g.case_uid) not in rows)
        check("Policy No is unchanged (endorsement = original policy, renewal = its own number)",
              rows[str(e1.case_uid)]["policyNo"] == "ZZ-FPN-A" and rows[str(b.case_uid)]["policyNo"] == "ZZ-FPN-B"
              and rows[str(e2.case_uid)]["policyNo"] == "ZZ-FPN-B" and rows[str(c.case_uid)]["policyNo"] == "ZZ-FPN-C")
        names = {rows[str(k.case_uid)]["originalInsured"] for k in (a, e1, b, e2, c)}
        check("the five chain rows have five different insured names but ONE First Policy No", len(names) == 5
              and {rows[str(k.case_uid)]["firstPolicyNo"] for k in (a, e1, b, e2, c)} == {"ZZ-FPN-A"})
        check("same insured name, different case -> different First Policy No (names alone are not used)",
              rows[str(a.case_uid)]["originalInsured"] == rows[str(d.case_uid)]["originalInsured"]
              and rows[str(a.case_uid)]["firstPolicyNo"] != rows[str(d.case_uid)]["firstPolicyNo"])
        check("headers: First Policy No is the last (18th) column", j["headers"][-1] == "First Policy No" and len(j["headers"]) == 18 and j["headers"][13] == "Policy No")

        # ===== 簽章與報表 =====
        before = j["sourceSignature"]
        Case.objects.filter(pk=b.pk).update(payload={**Case.objects.get(pk=b.pk).payload, "renewedFromTwRef": "ZZ-FPN-D"})
        after = call(finm, "get", f"{URL}?month={MONTH}").json()
        check("source signature ignores First Policy No (existing reports are not marked outdated)", after["sourceSignature"] == before)
        check("...but the preview does follow the changed link", {r["caseUid"]: r["firstPolicyNo"] for r in after["rows"]}[str(b.case_uid)] == "ZZ-FPN-D")
        Case.objects.filter(pk=b.pk).update(payload={**Case.objects.get(pk=b.pk).payload, "renewedFromTwRef": "ZZ-FPN-A"})
        sig = call(finm, "get", f"{URL}?month={MONTH}").json()["sourceSignature"]
        r = post(finm, "generate", MONTH, sourceSignature=sig)
        check("generate succeeds", r.status_code in (200, 201), r.content[:200])
        stored = ProductionReport.objects.filter(year_month=MONTH).order_by("-version").first()
        check("generated report stores First Policy No in every row", stored is not None and len(stored.rows) >= 8
              and all(row.get("firstPolicyNo") for row in stored.rows))
        listed = call(finm, "get", f"{URL}?month={MONTH}").json()["versions"][0]["rows"]
        check("API returns the stored rows with First Policy No", all("firstPolicyNo" in row for row in listed))
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| 2031 reports =", ProductionReport.objects.filter(year_month__startswith="2031").count())
