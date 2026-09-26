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
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=kw.pop("name", f"ZZ CLM {role} {_seq[0]}"), department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.clm.{tag}", password="Clm-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Clm-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Clm Cedant", originalInsured="ZZ Clm Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make_case(c, status="posted", **over):
    r = call(c, "post", "/api/cases", {"case": ready(**over)}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
    if status != "draft":
        _ref[0] += 1
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-CLM-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case
def ledger(c, case):
    return [x for x in call(c, "get", "/api/accounting").json().get("rows", []) if x["caseUid"] == str(case.case_uid)]
def claims(c, case):
    return call(c, "get", f"/api/claims?caseUid={case.case_uid}")
def act(c, action, case, root=None, **extra):
    body = {"action": action, "caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=(root or case).pk).row_version, **extra}
    return call(c, "post", "/api/claims", body)
def endorse(c, root, status, reinsurers=None):
    e = make_case(c, "draft", **({"reinsurers": reinsurers} if reinsurers else {}))
    _ref[0] += 1
    Case.objects.filter(pk=e.pk).update(parent_case=root, case_kind="endorsement", status=status,
                                        tw_ref=None if status == "draft" else f"ZZ-CLM-{_ref[0]:04d}-E")
    e.refresh_from_db(); return e
def audit(uid, action=None):
    q = AuditLog.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(action=action) if action else q
def snaps(uid, reason=None):
    q = EntitySnapshot.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(snapshot_reason=reason) if reason else q


try:
    with transaction.atomic():
        sales_p, gm_p, view_p, fin_p = person("sales", "reinsurance"), person("general_manager", "reinsurance"), person("viewer", "business_1"), person("accounting", "finance")
        sales, gm, viewer, fin = account(sales_p, "sales"), account(gm_p, "gm"), account(view_p, "view"), account(fin_p, "fin")

        root = make_case(sales, "posted")
        draft = make_case(sales, "draft")

        # ================= 權限 =================
        check("anonymous -> 401", call(new_client(), "get", f"/api/claims?caseUid={root.case_uid}").status_code == 401)
        for label, c in (("viewer", viewer), ("finance staff", fin)):
            check(f"{label}: no cases.read.all -> GET 403, POST 403", claims(c, root).status_code == 403 and act(c, "create_claim", root).status_code == 403)
        r = claims(gm, root)
        check("general manager: GET 200 (cases.read.all), no-store", r.status_code == 200 and r["Cache-Control"] == "no-store, max-age=0")
        check("general manager: POST 403 (no cases.write)", act(gm, "create_claim", root, claim={"dateOfLoss": "2026-05-01"}).status_code == 403)

        # ================= 讀取 =================
        r = call(sales, "get", "/api/claims"); check("GET without caseUid -> 400 case_uid_required", r.status_code == 400 and code(r) == "case_uid_required")
        r = call(sales, "get", f"/api/claims?caseUid={uuid.uuid4()}"); check("GET unknown case -> 404 case_not_found", r.status_code == 404 and code(r) == "case_not_found")
        r = call(sales, "get", f"/api/claims?caseUid={str(root.case_uid).upper()}"); check("GET upper-case UUID -> 404 (Alpha matches case_uid::text)", r.status_code == 404)
        st = claims(sales, root).json()["claimsState"]
        check("root state: TW Ref, status, version, currency, no claims, can write", st["rootCaseUid"] == str(root.case_uid) and st["rootTwRef"] == root.tw_ref and st["rootStatus"] == "posted"
              and st["rootRowVersion"] == root.row_version and st["currency"] == "USD" and st["claims"] == [] and st["actions"] == {"canWrite": True}, st)
        check("split source is the root when there is no Announced endorsement", st["splitSource"]["caseUid"] == str(root.case_uid) and len(st["splitSource"]["reinsurers"]) == 2, st["splitSource"])
        sd = claims(sales, draft).json()["claimsState"]
        check("Draft root: no TW Ref, cannot write", sd["rootTwRef"] == "" and sd["actions"] == {"canWrite": False}, sd)

        three = [dict(name="ZZ Re A", sharePct=50, premium=500, riCommPct=5, taxPct=0), dict(name="ZZ Re C", sharePct=30, premium=300, riCommPct=5, taxPct=0),
                 dict(name="ZZ Re B (Facility)", sharePct=20, premium=200, riCommPct=5, taxPct=0, foreignBroker="ZZ Broker")]
        e_draft = endorse(sales, root, "draft", three)
        st = claims(sales, root).json()["claimsState"]
        check("a Draft endorsement is not the split source", st["splitSource"]["caseUid"] == str(root.case_uid))
        e_old = endorse(sales, root, "closed")   # 較早的已確認批單：分攤要用「最新」那一張
        e1 = endorse(sales, root, "posted", three)
        e_arch = endorse(sales, root, "closed"); Case.objects.filter(pk=e_arch.pk).update(is_archived=True, archived_at=timezone.now(), archived_by="t")
        st = claims(sales, root).json()["claimsState"]
        check("the latest Announced/Confirmed endorsement is the split source (archived ones ignored)", st["splitSource"]["caseUid"] == str(e1.case_uid) and st["splitSource"]["twRef"] == e1.tw_ref
              and len(st["splitSource"]["reinsurers"]) == 3, st["splitSource"]["caseUid"])
        se = claims(sales, e1).json()["claimsState"]
        check("reading from an endorsement returns the same root state", se == st)

        # ================= 寫入：共同檢查 =================
        base = {"action": "create_claim", "caseUid": str(root.case_uid), "rowVersion": root.row_version, "claim": {"dateOfLoss": "2026-05-01"}}
        r = call(sales, "post", "/api/claims", {**base, "caseUid": ""}); check("POST without caseUid -> 400 case_uid_required", code(r) == "case_uid_required")
        for bad in (None, 0, 1.5, "x", -1):
            r = call(sales, "post", "/api/claims", {**base, "rowVersion": bad}); check(f"rowVersion {bad!r} -> 400 row_version_required", r.status_code == 400 and code(r) == "row_version_required")
        r = call(sales, "post", "/api/claims", {k: v for k, v in base.items() if k != "rowVersion"}); check("rowVersion missing -> 400 row_version_required", code(r) == "row_version_required")
        r = call(sales, "post", "/api/claims", {**base, "action": "delete_claim"}); check("unknown action -> 400 invalid_action", r.status_code == 400 and code(r) == "invalid_action")
        r = call(sales, "post", "/api/claims", {**base, "caseUid": str(uuid.uuid4())}); check("unknown case -> 404", r.status_code == 404 and code(r) == "case_not_found")
        r = act(sales, "create_claim", draft, claim={"dateOfLoss": "2026-05-01"}); check("Draft root (no TW Ref) -> 409 claim_reference_required", r.status_code == 409 and code(r) == "claim_reference_required")
        r = call(sales, "post", "/api/claims", {**base, "rowVersion": root.row_version + 1})
        check("stale root version -> 409 version_conflict with currentRowVersion", r.status_code == 409 and code(r) == "version_conflict" and r.json()["currentRowVersion"] == root.row_version)
        Case.objects.filter(pk=e1.pk).update(row_version=root.row_version + 7)
        r = act(sales, "create_claim", e1, root=e1, claim={"dateOfLoss": "2026-05-01"})
        check("posting from an endorsement with the endorsement's own version -> 409 (the ROOT version is required)", r.status_code == 409 and code(r) == "version_conflict", r.status_code)

        # ================= 新增理賠 =================
        v0 = root.row_version; before = Case.objects.get(pk=root.pk).payload
        for label, claim in (("Date of Loss missing (VM: required)", {}), ("Date of Loss blank", {"dateOfLoss": "  "}), ("Date of Loss 2026-02-30", {"dateOfLoss": "2026-02-30"}),
                             ("Date of Loss text", {"dateOfLoss": "last May"}), ("Date of Loss 2026/05/01", {"dateOfLoss": "2026/05/01"})):
            r = act(sales, "create_claim", root, claim=claim); check(f"create: {label} -> 400 invalid_date_of_loss", r.status_code == 400 and code(r) == "invalid_date_of_loss", (r.status_code, code(r)))
        for label, reserve in (("reserve text (Alpha stored 0)", "abc"), ("reserve negative", -1), ("reserve -0.5 text", "-0.5"), ("reserve Infinity", "Infinity")):
            r = act(sales, "create_claim", root, claim={"dateOfLoss": "2026-05-01", "outstandingReserve": reserve})
            check(f"create: {label} -> 400 invalid_claim_reserve", r.status_code == 400 and code(r) == "invalid_claim_reserve", (r.status_code, code(r)))
        check("create: failed attempts changed nothing", Case.objects.get(pk=root.pk).row_version == v0 and Case.objects.get(pk=root.pk).payload == before)
        r = act(sales, "create_claim", root, claim={"lossNo": "  L" + "x" * 200, "dateOfLoss": "2026-05-01", "causeOfLoss": "c" * 2500, "outstandingReserve": "1,234.567"})
        j = r.json(); root.refresh_from_db(); c1 = root.payload["claims"][0]
        check("create -> 200 {ok, action, claimId 1, claimsState}", r.status_code == 200 and j["ok"] is True and j["action"] == "create_claim" and j["claimId"] == 1
              and j["claimsState"]["rootRowVersion"] == v0 + 1 and j["claimsState"]["claims"] == root.payload["claims"], j)
        check("claim fields: trimmed/capped text, reserve parsed with comma and rounded to cents (VM), no payments", c1["id"] == 1 and len(c1["lossNo"]) == 160 and c1["lossNo"].startswith("Lx")
              and len(c1["causeOfLoss"]) == 2000 and c1["outstandingReserve"] == 1234.57 and c1["payments"] == [] and c1["dateOfLoss"] == "2026-05-01", c1)
        a = audit(root.case_uid, "create_claim").first()
        check("audit create_claim: before/after payload, metadata", a and a.metadata == {"claimId": 1, "action": "create_claim"} and a.before_data["rowVersion"] == v0
              and a.before_data["payload"].get("claims", []) == [] and a.after_data["payload"]["claims"][0]["id"] == 1)
        check("snapshot claim_created at the new version (VM addition)", snaps(root.case_uid, "claim_created").filter(entity_version=v0 + 1).exists())
        r = act(sales, "create_claim", e1, root=root, claim={"dateOfLoss": "2026-06-30"}); root.refresh_from_db()
        check("create from an endorsement view: stored on the root as claim #2, blank reserve is 0", r.status_code == 200 and [c["id"] for c in root.payload["claims"]] == [1, 2]
              and root.payload["claims"][1]["outstandingReserve"] == 0 and (Case.objects.get(pk=e1.pk).payload or {}).get("claims") in (None, []), root.payload["claims"])

        # ================= 準備金 =================
        v1 = root.row_version
        r = act(sales, "update_reserve", root, claimId=99, outstandingReserve=1); check("reserve: unknown claim -> 404 claim_not_found", r.status_code == 404 and code(r) == "claim_not_found")
        r = act(sales, "update_reserve", root, outstandingReserve=1); check("reserve: claimId missing -> 404", code(r) == "claim_not_found")
        for bad in ("abc", -0.01, "1e999"):
            r = act(sales, "update_reserve", root, claimId=1, outstandingReserve=bad); check(f"reserve {bad!r} -> 400 invalid_claim_reserve", code(r) == "invalid_claim_reserve", code(r))
        r = act(sales, "update_reserve", root, claimId="1", outstandingReserve=5000.555); root.refresh_from_db()
        check("reserve updated (claimId as text works like Number()), rounded to cents", r.status_code == 200 and root.payload["claims"][0]["outstandingReserve"] == 5000.56 and root.row_version == v1 + 1, r.content[:200])
        check("audit update_claim_reserve + snapshot claim_reserve_updated", audit(root.case_uid, "update_claim_reserve").first().metadata == {"claimId": 1, "action": "update_reserve"}
              and snaps(root.case_uid, "claim_reserve_updated").exists())
        r = act(sales, "update_reserve", root, claimId=1, outstandingReserve=""); root.refresh_from_db()
        check("reserve blank -> 0 (same as Alpha)", r.status_code == 200 and root.payload["claims"][0]["outstandingReserve"] == 0)

        # ================= 理賠付款 =================
        v2 = root.row_version
        for label, pay in (("amount 0", {"amount": 0, "date": "2026-07-01"}), ("amount text", {"amount": "abc", "date": "2026-07-01"}), ("amount missing", {"date": "2026-07-01"}),
                           ("amount 0.004 rounds to 0 (VM)", {"amount": 0.004, "date": "2026-07-01"})):
            r = act(sales, "record_payment", root, claimId=1, payment=pay); check(f"payment: {label} -> 400 payment_amount_required", r.status_code == 400 and code(r) == "payment_amount_required", (r.status_code, code(r)))
        for label, pay in (("date missing (VM: required)", {"amount": 10}), ("date 2026-13-01", {"amount": 10, "date": "2026-13-01"}), ("date text", {"amount": 10, "date": "soon"})):
            r = act(sales, "record_payment", root, claimId=1, payment=pay); check(f"payment: {label} -> 400 invalid_payment_date", r.status_code == 400 and code(r) == "invalid_payment_date", (r.status_code, code(r)))
        r = act(sales, "record_payment", root, claimId=5, payment={"amount": 10, "date": "2026-07-01"}); check("payment: unknown claim -> 404", code(r) == "claim_not_found")
        check("payment: failed attempts changed nothing", Case.objects.get(pk=root.pk).row_version == v2)
        r = act(sales, "record_payment", e1, root=root, claimId=1, payment={"amount": "1,000.005", "date": "2026-07-01", "note": " first "}); root.refresh_from_db()
        p1 = root.payload["claims"][0]["payments"][0]; tx = [t for t in root.payload.get("transactions", []) if t.get("source") == "claim"]
        check("payment recorded: id 1, amount parsed and rounded, note trimmed", r.status_code == 200 and p1 == {"id": 1, "date": "2026-07-01", "amount": 1000.01, "note": "first"}, (r.status_code, p1))
        check("transactions: Claim Leg 1 + Leg 2 per reinsurer of the split source (3 -> 6)", len(tx) == 6 and [t["legType"] for t in tx[:2]] == ["Claim Leg 1", "Claim Leg 2"], len(tx))
        check("VM fix: transaction numbers start with the root TW Ref (Alpha: 'undefined')", all(t["txNo"].startswith(root.tw_ref + "-CLM1-P1-R") for t in tx) and not any("undefined" in t["txNo"] for t in tx), [t["txNo"] for t in tx[:2]])
        check("shares follow the endorsement split: 50% / 30% / 20%", [t["amount"] for t in tx[::2]] == [money(1000.01 * 0.5), money(1000.01 * 30 / 100), money(1000.01 * 20 / 100)], [t["amount"] for t in tx[::2]])
        check("reinsurerIdx maps to the root lines by name (Re C is not on the root -> null); broker used as settlement party",
              [t["reinsurerIdx"] for t in tx[::2]] == [0, None, 1] and tx[4]["reinsurer"] == "ZZ Broker" and tx[4]["viaForeignBroker"] is True, [(t["reinsurerIdx"], t["reinsurer"]) for t in tx[::2]])
        check("audit record_claim_payment + snapshot claim_payment_recorded", audit(root.case_uid, "record_claim_payment").first().metadata == {"claimId": 1, "action": "record_payment"}
              and snaps(root.case_uid, "claim_payment_recorded").filter(entity_version=v2 + 1).exists())
        r = act(sales, "record_payment", root, claimId=1, payment={"amount": -200, "date": "2026-07-02"}); root.refresh_from_db()
        tx2 = [t for t in root.payload["transactions"] if "-CLM1-P2-" in t["txNo"]]
        check("negative payment allowed (recovery / correction), payment id 2, negative transactions", r.status_code == 200 and root.payload["claims"][0]["payments"][1]["amount"] == -200
              and len(tx2) == 6 and all(t["amount"] < 0 for t in tx2), r.content[:200])
        rows = [x for x in ledger(fin, root) if x["source"] == "claim"]
        check("claim transactions appear in the Accounting ledger", len(rows) == 12 and all(x["settlement"] == "open" for x in rows), len(rows))
        check("GET shows the claims with payments", claims(sales, e1).json()["claimsState"]["claims"] == root.payload["claims"])
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Clm Insured").count())
