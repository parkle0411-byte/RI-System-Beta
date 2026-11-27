"""案件 History（2026-11-27）：Announce 之後的事件與欄位修改前／後。唯讀 API，走真實的建立 → Announce → 修改流程。"""
import copy
import json
import uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from audit.services import record_snapshot
from cases.history import MAX_CHANGES, compare
from cases.models import Case, CaseDocument
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    kw.setdefault('email', f'zz.hist.{_seq[0]}@example.test')
    return Personnel.objects.create(name=kw.pop("name", f"ZZ HIST {role} {_seq[0]}"), department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value) if "csrftoken" in c.cookies else {}
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.hist.{tag}", password="Hist-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Hist-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

BEFORE_TEXT = "Loc 1: Chemical Factory\n Loc 2: Outdoor Tank"
AFTER_TEXT = "Loc 1: Chemical Factory\nLoc 2: Outdoor Tank"
def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Cedant", originalInsured="ZZ Hist Insured", originalInsuredCn='合成測試被保險人', policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0, paymentTermsDays=30), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0, paymentTermsDays=30)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation=BEFORE_TEXT, construction='Concrete', constructionSelections=['A2 Class'],
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
def create(c, **over):
    r = call(c, "post", "/api/cases", {"case": ready(**over)}); assert r.status_code == 201, r.content
    return Case.objects.get(case_uid=r.json()["case"]["caseUid"])
def announce(c, case):
    docs = [CaseDocument.objects.create(case=case, kind=kind, reinsurers=names, filename=f"{kind}.pdf", content_type="application/pdf", byte_size=5,
                                        sha256="0" * 64, storage_key=f"zz-{uuid.uuid4()}", is_selected=True, uploaded_by="t")
            for kind, names in (("offer", []), ("signed", ["ZZ Re A"]), ("confirmation", ["ZZ Re B"]))]
    r = call(c, "post", "/api/case-announce", {"caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version,
                                               "confirmed": True, "documentIds": [str(d.pk) for d in docs]})
    assert r.status_code == 200, r.content
    case.refresh_from_db(); return case
def load(c, case): return call(c, "get", f"/api/cases?caseUid={case.case_uid}").json()["case"]
def save(c, case, change=None, **extra):
    """與畫面相同：讀出案件、改欄位、整份送回。"""
    current = load(c, case); payload = copy.deepcopy(current["payload"])
    if change: change(payload)
    return call(c, "put", "/api/cases", {"caseUid": str(case.case_uid), "rowVersion": current["rowVersion"], "case": payload, **extra})
def history(c, case): return call(c, "get", f"/api/case-history?caseUid={case.case_uid}")
def events(c, case): return history(c, case).json()["events"]
def fields(event): return sorted(x["field"] for x in event["changes"])
def counts(): return Case.objects.count(), EntitySnapshot.objects.count(), AuditLog.objects.count(), sum(Case.objects.values_list("row_version", flat=True))

try:
    with transaction.atomic():
        sales_p, adm_p = person("sales", "reinsurance", name="ZZ Hist Sandy"), person("admin", "admin")
        view_p, acct_p = person("viewer", "business_1"), person("accounting", "finance")
        sales, admin, viewer, acct = account(sales_p, "sales"), account(adm_p, "admin"), account(view_p, "view"), account(acct_p, "acct")

        # ---------------- 草稿 ----------------
        c1 = create(sales)
        assert save(sales, c1, lambda p: p.update(interest="Buildings and contents")).status_code == 200
        r = history(sales, c1); j = r.json()
        check("draft: 200, not announced, no events", r.status_code == 200 and j["announced"] is False and j["events"] == [], j)
        check("response is no-store", r["Cache-Control"] == "no-store, max-age=0", r.get("Cache-Control"))

        # ---------------- Announce 之後 ----------------
        c1 = announce(sales, c1)
        e = events(sales, c1)
        check("right after Announce: exactly the Announce event, drafts before it are not listed",
              [(x["reason"], x["action"], x["changes"], x["compared"]) for x in e] == [("announced", "Announced", [], False)], e)

        r = save(sales, c1, lambda p: p.update(occupation=AFTER_TEXT)); assert r.status_code == 200, r.content
        e = events(sales, c1); top = e[0]
        check("newest first: edit then Announce", [x["reason"] for x in e] == ["case_updated", "announced"], e)
        check("one removed space is the only reported change, with the exact before and after text",
              top["changes"] == [{"field": "Occupation", "before": BEFORE_TEXT, "after": AFTER_TEXT, "kind": "changed"}], top["changes"])
        check("event carries who, when, action, version and the compared version",
              top["actorName"] == "ZZ Hist Sandy" and top["action"] == "Case edited" and top["at"] and top["compared"] is True
              and top["version"] == c1.row_version + 1 and top["comparedWithVersion"] == c1.row_version, top)

        r = save(sales, c1); assert r.status_code == 200, r.content
        top = events(sales, c1)[0]
        check("saving without editing reports no field change (no server-added noise)", top["compared"] is True and top["changes"] == [], top["changes"])

        def several(p):
            p["deductibles"] = "15%"; p["originalConditions"] = "As original policy"
            p["situations"] = p["situations"] + [dict(address="2 ZZ Road", postcode="200")]
            p["sumInsured"][0]["amount"] = 2000000
        r = save(sales, c1, several); assert r.status_code == 200, r.content
        top = events(sales, c1)[0]
        check("several edits are each listed with their screen names",
              fields(top) == sorted(["Deductibles", "Original Conditions", "Situation › #2", "Sum Insured › Building › Amount"]), top["changes"])
        by = {x["field"]: x for x in top["changes"]}
        check("added row is marked added with its content", by["Situation › #2"]["kind"] == "added" and by["Situation › #2"]["before"] is None
              and "2 ZZ Road" in by["Situation › #2"]["after"] and "200" in by["Situation › #2"]["after"], by.get("Situation › #2"))
        check("amount before and after", (by["Sum Insured › Building › Amount"]["before"], by["Sum Insured › Building › Amount"]["after"]) == ("1000000", "2000000"), by.get("Sum Insured › Building › Amount"))
        r = save(sales, c1, lambda p: p.update(situations=p["situations"][:1])); assert r.status_code == 200, r.content
        top = events(sales, c1)[0]
        check("removed row is marked removed", [(x["field"], x["kind"], x["after"]) for x in top["changes"]] == [("Situation › #2", "removed", None)], top["changes"])

        # ---------------- 參考號碼編輯 ----------------
        r = call(sales, "post", "/api/case-reconciliation-references", {"caseUid": str(c1.case_uid), "rowVersion": Case.objects.get(pk=c1.pk).row_version,
                                                                      "statementNo": "SOA-77", "reinsurers": [{"index": 0, "settlementRef": "REF-A"}]})
        top = events(sales, c1)[0]
        check("reference editor: lists statement and reinsurer reference only", r.status_code == 200 and top["reason"] == "reconciliation_references_updated"
              and fields(top) == sorted(["Statement No.", "Reinsurer › ZZ Re A › Settlement Reference"]), (r.status_code, r.content[:200], top))

        # ---------------- 系統事件只列一行 ----------------
        current = Case.objects.get(pk=c1.pk)
        paid = copy.deepcopy(current.payload); paid["paymentEntries"] = [{"id": "p", "amount": 5}]; paid["statementNo"] = "SOA-AFTER-FINANCE"
        for step, reason in enumerate(("finance_accounts_reviewed", "payment_recorded"), 1):
            Case.objects.filter(pk=c1.pk).update(row_version=current.row_version + step, payload=paid)
            record_snapshot(entity_type="case", entity_id=c1.case_uid, version=current.row_version + step, reason=reason,
                            data={"payload": paid}, created_by=f"personnel:{acct_p.pk}")
        record_snapshot(entity_type="case", entity_id=c1.case_uid, version=current.row_version + 3, reason="claim_loss_snapshot_updated",
                        data={"snapshot": {}}, created_by="cli")
        Case.objects.filter(pk=c1.pk).update(row_version=current.row_version + 3)
        e = events(sales, c1)
        check("finance and payment events are one line each without field details",
              [(x["action"], x["compared"], x["changes"]) for x in e[:3]] == [("Renewal claim record updated", False, []), ("Payment recorded", False, []), ("Finance review", False, [])]
              and e[1]["actorName"] == acct_p.name and e[0]["actorName"] == "System (maintenance)", e[:3])
        r = save(sales, c1, lambda p: p.update(deductibles="20%")); assert r.status_code == 200, r.content
        top = events(sales, c1)[0]
        check("an edit after system events compares with the latest full version (skipping versions without content)",
              fields(top) == ["Deductibles"] and top["comparedWithVersion"] == current.row_version + 2, top)

        # ---------------- 理賠（真實 API） ----------------
        r = call(sales, "post", "/api/claims", {"action": "create_claim", "caseUid": str(c1.case_uid), "rowVersion": Case.objects.get(pk=c1.pk).row_version,
                                              "claim": {"dateOfLoss": "2026-05-01", "outstandingReserve": 500}})
        top = events(sales, c1)[0]
        check("claim created: listed with the claim content only, no internal ids or stamps",
              r.status_code in (200, 201) and top["reason"] == "claim_created" and top["changes"] and all(x["field"].startswith("Claim") for x in top["changes"])
              and "createdAt" not in json.dumps(top["changes"]) and "Created At" not in json.dumps(top["changes"]) and "2026-05-01" in json.dumps(top["changes"]), (r.status_code, r.content[:200], top))

        # ---------------- Reverse 之後的草稿修改 ----------------
        c2 = announce(sales, create(sales, originalInsured="ZZ Hist Insured 2"))
        r = call(sales, "post", "/api/case-workflow", {"action": "reverse_case", "caseUid": str(c2.case_uid), "rowVersion": c2.row_version}); assert r.status_code == 200, r.content
        c2.refresh_from_db()
        r = save(sales, c2, lambda p: p.update(deductibles="30%"), reverseCorrectionConfirmed=True, reason="ZZ correction"); assert r.status_code == 200, r.content
        e = events(sales, c2)
        check("after Reverse: the reversal and the correction are listed with the corrected field",
              [x["reason"] for x in e][1:] == ["case_reversed", "announced"] and e[0]["reason"] in ("draft_updated", "case_updated") and fields(e[0]) == ["Deductibles"], e)

        # ---------------- 批單 ----------------
        c3 = announce(sales, create(sales, originalInsured="ZZ Hist Insured 3"))
        r = call(sales, "post", "/api/case-workflow", {"action": "create_endorsement", "caseUid": str(c3.case_uid), "rowVersion": c3.row_version}); assert r.status_code == 201, r.content
        child = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
        check("endorsement draft: no history yet; the original case is unchanged",
              events(sales, child) == [] and [x["reason"] for x in events(sales, c3)] == ["announced"])

        # ---------------- 唯讀 ----------------
        before = counts()
        for who in (sales, admin, acct): history(who, c1)
        check("reading history writes nothing", counts() == before, (before, counts()))

        # ---------------- 權限 ----------------
        check("anonymous -> 401", history(new_client(), c1).status_code == 401)
        check("finance and admin can read", history(acct, c1).status_code == 200 and history(admin, c1).status_code == 200)
        r = history(viewer, c1); check("viewer, not their case -> 404", r.status_code == 404 and code(r) == "case_not_found", r.status_code)
        Case.objects.filter(pk=c1.pk).update(owner_personnel=view_p)
        check("viewer, own case -> 200 with the same events", history(viewer, c1).status_code == 200 and events(viewer, c1) == events(admin, c1))
        Case.objects.filter(pk=c1.pk).update(owner_personnel=sales_p)
        for label_, url in (("no caseUid", "/api/case-history"), ("bad uuid", "/api/case-history?caseUid=abc"), ("unknown case", f"/api/case-history?caseUid={uuid.uuid4()}")):
            r = call(admin, "get", url); check(f"{label_} -> 404", r.status_code == 404 and code(r) == "case_not_found", r.status_code)
        check("writing methods are refused", all(call(admin, m, f"/api/case-history?caseUid={c1.case_uid}", {}).status_code in (403, 405) for m in ("post", "put", "delete")))
        Case.objects.filter(pk=c2.pk).update(recycled_at="2026-01-01T00:00:00Z", recycled_by="t")
        check("recycled case -> 404", history(admin, c2).status_code == 404)
        Case.objects.filter(pk=c3.pk).update(reinsurance_structure="FACILITY")
        check("Facility cases are not offered -> 404", history(admin, c3).status_code == 404)

        # ---------------- 筆數上限 ----------------
        import cases.history_views as views
        original, views.MAX_EVENTS = views.MAX_EVENTS, 3
        try:
            j = history(admin, c1).json()
        finally:
            views.MAX_EVENTS = original
        check("only the latest events are returned and flagged as truncated", len(j["events"]) == 3 and j["truncated"] is True and j["events"][0]["reason"] == "claim_created", j)
        raise Rollback()
except Rollback:
    pass

# ---------------- 比對規則 ----------------
def changes(a, b, reason="case_updated"): return compare(reason, a, b)[0]
check("empty values and missing keys are the same", changes({"a": "", "b": None, "c": [], "d": {}, "e": False}, {"f": "", "g": [{}] and []}) == [])
check("a number stored as text equals the number", changes({"originalPremium": "1000"}, {"originalPremium": 1000.0}) == [])
check("zero is a value, not empty", changes({}, {"taxPct": 0}) == [{"field": "Tax (%)", "before": None, "after": "0", "kind": "changed"}])
check("switching a tick off is reported", changes({"installmentEnabled": True}, {"installmentEnabled": False}) == [{"field": "Premium Installments", "before": "Yes", "after": "No", "kind": "changed"}])
check("system-maintained keys and internal ids are not reported",
      changes({"status": "draft", "transactions": [], "ownerPersonnelId": 1, "twRef": "A", "draftInput": {}},
              {"status": "posted", "transactions": [{"x": 1}], "ownerPersonnelId": 2, "twRef": "B", "draftInput": {"a": 1}}) == [])
check("reference corrections show the TW Ref", [x["field"] for x in changes({"twRef": "A"}, {"twRef": "B"}, "oversea_reference_corrected")] == ["Tw Ref"])
rows_a = [{"name": "Re A", "sharePct": 60, "riCommPct": 5}, {"name": "Re B", "sharePct": 40, "riCommPct": 5}]
rows_b = [{"name": "Re B", "sharePct": 40, "riCommPct": 7}, {"name": "Re C", "sharePct": 60, "riCommPct": 5}]
got = {(x["field"], x["kind"]) for x in changes({"reinsurers": rows_a}, {"reinsurers": rows_b})}
check("reinsurers are matched by name: change, addition, removal",
      got == {("Reinsurer › Re B › Deductions (%)", "changed"), ("Reinsurer › Re C", "added"), ("Reinsurer › Re A", "removed")}, got)
check("nested and plain lists", changes({"cglInformation": {"policyForm": "Occurrence"}, "clauses": ["A", "B"]}, {"cglInformation": {"policyForm": "Claims Made"}, "clauses": ["A"]})
      == [{"field": "CGL Information › Policy Form", "before": "Occurrence", "after": "Claims Made", "kind": "changed"}, {"field": "Clauses", "before": "A, B", "after": "A", "kind": "changed"}])
out, comment = compare("historical_personnel_link", {}, {"personnelIdentityHistory": [{"field": "ae", "historicalName": "Old", "personnelName": "New", "reason": "Renamed"}]})
check("personnel link shows names and reason", out == [{"field": "Account Executive link", "before": "Old", "after": "New", "kind": "changed"}] and comment == "Renamed", (out, comment))
check("property edit reason is shown", compare("case_updated", {"propertyEditHistory": [{"reason": "old"}]}, {"propertyEditHistory": [{"reason": "old"}, {"reason": "Fix share"}]})[1] == "Fix share")
claim = {"id": "c", "createdAt": "x", "updatedBy": "y", "reserve": 5, "payments": []}
check("claim events compare claims only", changes({"claims": [claim], "deductibles": "1"}, {"claims": [{**claim, "reserve": 9, "createdAt": "z"}], "deductibles": "2"}, "claim_reserve_updated")
      == [{"field": "Claim › #1 › Reserve", "before": "5", "after": "9", "kind": "changed"}])
check("very many changes are capped at one over the limit", len(changes({}, {f"k{i}": i + 1 for i in range(MAX_CHANGES + 50)})) >= MAX_CHANGES + 1)

fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ cases =", Case.objects.filter(payload__originalInsured__startswith="ZZ Hist").count(), "| ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count())
