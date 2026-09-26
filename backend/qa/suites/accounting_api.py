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
             reinsured="ZZ Acc Cedant", originalInsured="ZZ Acc Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
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
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-ACC-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case
def ledger(c, case=None):
    r = call(c, "get", "/api/accounting"); j = r.json()
    rows = [x for x in j.get("rows", []) if case is None or x["caseUid"] == str(case.case_uid)]
    return r, j, rows
def post(c, action, case, **extra):
    body = {"action": action, "caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version, **extra}
    return call(c, "post", "/api/accounting", body)
def pay(c, case, key, amount, date="2026-09-20", **extra): return post(c, "record_payment", case, scheduleKey=key, amount=amount, paymentDate=date, **extra)
def audit(uid, action=None):
    q = AuditLog.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(action=action) if action else q
def snaps(uid, reason=None):
    q = EntitySnapshot.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(snapshot_reason=reason) if reason else q

try:
    with transaction.atomic():
        adm_p, sales_p, gm_p, view_p = person("admin", "admin"), person("sales", "reinsurance"), person("general_manager", "reinsurance"), person("viewer", "business_1")
        fin_p, finm_p = person("accounting", "finance"), person("accounting_manager", "finance")
        admin, sales, gm, viewer = account(adm_p, "admin"), account(sales_p, "sales"), account(gm_p, "gm"), account(view_p, "view")
        fin, finm = account(fin_p, "fin"), account(finm_p, "finm")

        # ================= 權限 =================
        for label, c in (("sales", sales), ("general manager", gm), ("viewer", viewer)):
            check(f"{label}: no accounting.read -> GET and POST 403", call(c, "get", "/api/accounting").status_code == 403 and call(c, "post", "/api/accounting", {"action": "record_payment"}).status_code == 403)
        check("anonymous -> 401", call(new_client(), "get", "/api/accounting").status_code == 401)
        for label, c in (("admin", admin), ("finance staff", fin), ("finance manager", finm)):
            r = call(c, "get", "/api/accounting")
            check(f"{label}: GET 200, canEdit true, no-store", r.status_code == 200 and r.json()["scope"] == {"canEdit": True} and r.json()["ok"] is True
                  and r["Cache-Control"] == "no-store, max-age=0", (r.status_code, r.content[:200]))
        r = call(fin, "post", "/api/accounting", {"action": "settle"}); check("unknown action (settle is not in the API) -> 400 unsupported_action", r.status_code == 400 and code(r) == "unsupported_action")
        r = call(fin, "post", "/api/accounting", {}); check("no action -> 400 unsupported_action", code(r) == "unsupported_action")

        # ================= 帳本 =================
        posted = make_case(sales, "posted")
        closed = make_case(sales, "closed", currency="EUR")
        draft = make_case(sales, "draft")
        rev = make_case(sales, "reversed")
        recycled = make_case(sales, "draft"); Case.objects.filter(pk=recycled.pk).update(recycled_at="2026-01-01T00:00:00Z", recycled_by="t")
        archived = make_case(sales, "closed"); Case.objects.filter(pk=archived.pk).update(is_archived=True, archived_at=timezone.now(), archived_by="t")
        r, j, _ = ledger(fin)
        uids = {x["caseUid"] for x in j["rows"]}
        check("ledger lists Announced and Confirmed cases", str(posted.case_uid) in uids and str(closed.case_uid) in uids)
        check("ledger excludes Draft, Reversed, recycled and archived cases", not ({str(c.case_uid) for c in (draft, rev, recycled, archived)} & uids))
        check("currencies: distinct, sorted", "USD" in j["currencies"] and "EUR" in j["currencies"] and j["currencies"] == sorted(set(j["currencies"])))
        _, _, rows = ledger(fin, posted)
        sched = build_payment_schedule(posted.payload)
        check("one premium row per schedule item (Cedant + 2 Reinsurers)", len(rows) == 3 and [x["scheduleKey"] for x in rows] == [i["scheduleKey"] for i in sched["items"]], [x.get("scheduleKey") for x in rows])
        ced = next(x for x in rows if x["partyType"] == "cedant"); r2 = next(x for x in rows if x["scheduleKey"].endswith(":r2"))
        check("cedant row: label, legType, amount, key", ced["label"] == "Receivable from " + ced["partyName"] and ced["legType"] == "Cedant" and ced["reinsurer"] == ""
              and ced["key"] == f"{posted.case_uid}:case-effective-date:cedant" and ced["amount"] == sched["items"][0]["amount"] and ced["caseRowVersion"] == posted.row_version, ced)
        check("reinsurer row: Facility tag stripped, Payable to, legType Reinsurer", r2["partyName"] == "ZZ Re B" and r2["label"] == "Payable to ZZ Re B" and r2["reinsurer"] == "ZZ Re B" and r2["legType"] == "Reinsurer", r2)
        check("row fields: twRef, status, reinsured, currency, dueTime, settlement open, no entries", ced["twRef"] == posted.tw_ref and ced["caseStatus"] == "posted" and ced["reinsured"] == "ZZ Acc Cedant"
              and ced["currency"] == "USD" and ced["dueTime"] == "12:00" and ced["settlement"] == "open" and ced["entries"] == [] and ced["source"] == "premium", ced)

        # 理賠交易也列在帳本
        p = copy.deepcopy(posted.payload)
        p["transactions"] = [{"source": "claim", "txNo": "CL-1", "legType": "Claim Leg 1", "reinsurer": "ZZ Re A", "reinsurerIdx": 0, "label": "Claim paid", "amount": 250.5, "settlement": "settled", "settledAt": "2026-09-01T00:00:00.000Z", "settledBy": "P.L"},
                             {"source": "claim", "txNo": "CL-2", "legType": "Claim Leg 2", "amount": "80", "settlement": "open"},
                             {"source": "premium", "txNo": "P-1", "amount": 1}, None]
        Case.objects.filter(pk=posted.pk).update(payload=p); posted.refresh_from_db()
        _, _, rows = ledger(fin, posted)
        cl = [x for x in rows if x["source"] == "claim"]
        check("claim transactions appear (premium transactions and nulls do not)", len(cl) == 2 and len(rows) == 5, len(rows))
        check("open claim: paid 0, outstanding = amount, status upcoming", len(cl) == 2 and cl[1]["paid"] == 0 and cl[1]["outstanding"] == 80 and cl[1]["paymentStatus"] == "upcoming" and cl[1]["settledAt"] is None, cl[1:])
        check("claim row fields", cl and cl[0]["key"] == f"{posted.case_uid}:CL-1" and cl[0]["amount"] == 250.5 and cl[0]["paid"] == 250.5 and cl[0]["outstanding"] == 0
              and cl[0]["settlement"] == "settled" and cl[0]["paymentStatus"] == "settled" and cl[0]["settledBy"] == "P.L" and cl[0]["reversed"] is False, cl)
        # 帳本：paymentEntries 裡有 null（Alpha 會整個拋錯），VM 略過
        p2 = copy.deepcopy(posted.payload); p2["paymentEntries"] = [None]
        Case.objects.filter(pk=posted.pk).update(payload=p2)
        check("a null inside paymentEntries does not break the ledger (VM)", call(fin, "get", "/api/accounting").status_code == 200)
        Case.objects.filter(pk=posted.pk).update(payload=posted.payload); posted.refresh_from_db()

        # ================= 記付款：驗證 =================
        key = "case-effective-date:cedant"
        v0 = posted.row_version
        check("sales cannot record payments (403)", pay(sales, posted, key, 10).status_code == 403)
        bad_inputs = [
            ("missing caseUid", dict(caseUid="")), ("missing scheduleKey", dict(scheduleKey="  ")), ("amount 0", dict(amount=0)), ("negative amount", dict(amount=-5)),
            ("amount text", dict(amount="abc")), ("amount missing", dict(amount=None)), ("amount Infinity text", dict(amount="Infinity")),
            ("date missing", dict(paymentDate="")), ("date 2026-13-45 (VM: real dates only)", dict(paymentDate="2026-13-45")),
            ("date 2026-02-30", dict(paymentDate="2026-02-30")), ("date 2026-2-3", dict(paymentDate="2026-2-3")), ("date with time", dict(paymentDate="2026-09-20T00:00")),
            ("date 0000-01-01", dict(paymentDate="0000-01-01")),
        ]
        for label, override in bad_inputs:
            body = {"action": "record_payment", "caseUid": str(posted.case_uid), "rowVersion": v0, "scheduleKey": key, "amount": 10, "paymentDate": "2026-09-20", **override}
            r = call(fin, "post", "/api/accounting", body)
            check(f"record: {label} -> 400 invalid_payment", r.status_code == 400 and code(r) == "invalid_payment", (r.status_code, code(r)))
        r = pay(fin, posted, key, 10, "2024-02-29"); check("record: leap day 2024-02-29 is accepted", r.status_code == 200, r.content[:200]); posted.refresh_from_db()
        r = post(fin, "reverse_payment", posted, entryId=posted.payload["paymentEntries"][-1]["id"]); posted.refresh_from_db()   # 讓後面從乾淨的餘額開始
        v0 = posted.row_version
        r = call(fin, "post", "/api/accounting", {"action": "record_payment", "caseUid": str(uuid.uuid4()), "rowVersion": 1, "scheduleKey": key, "amount": 1, "paymentDate": "2026-09-20"})
        check("record: unknown case -> 404", r.status_code == 404 and code(r) == "case_not_found")
        for label, uid in (("upper-case UUID", str(posted.case_uid).upper()), ("UUID without dashes", posted.case_uid.hex), ("not a UUID", "abc")):
            r = call(fin, "post", "/api/accounting", {"action": "record_payment", "caseUid": uid, "rowVersion": v0, "scheduleKey": key, "amount": 1, "paymentDate": "2026-09-20"})
            check(f"record: {label} -> 404 (same as Alpha's case_uid::text match)", r.status_code == 404, r.status_code)
        for label, c in (("Draft", draft), ("Reversed", rev)):
            r = pay(fin, c, key, 1); check(f"record on a {label} case -> 409 accounting_status_locked (VM)", r.status_code == 409 and code(r) == "accounting_status_locked", (r.status_code, code(r)))
        r = pay(fin, recycled, key, 1); check("record on a recycled Draft -> 404 (not found before the status check)", r.status_code == 404)
        r = pay(fin, posted, "case-effective-date:reinsurer:r9", 1); check("record: unknown schedule key -> 400 schedule_not_found", code(r) == "schedule_not_found")
        r = pay(fin, posted, key, ced["outstanding"] + 0.01); check("record: more than outstanding -> 400 overpayment", code(r) == "overpayment", code(r))
        r = pay(fin, posted, key, 10, rowVersion=v0 - 1 if v0 > 1 else 99); check("record: stale rowVersion -> 409 version_conflict", r.status_code == 409 and code(r) == "version_conflict")
        r = call(fin, "post", "/api/accounting", {"action": "record_payment", "caseUid": str(posted.case_uid), "scheduleKey": key, "amount": 10, "paymentDate": "2026-09-20"})
        check("record: rowVersion missing -> 409 version_conflict", r.status_code == 409 and code(r) == "version_conflict")
        check("record: no failed attempt changed the case", Case.objects.get(pk=posted.pk).row_version == v0 and len(Case.objects.get(pk=posted.pk).payload["paymentEntries"]) == 2)
        nobase = make_case(sales, "posted")
        pb = copy.deepcopy(nobase.payload); pb["policyFrom"] = ""; Case.objects.filter(pk=nobase.pk).update(payload=pb); nobase.refresh_from_db()
        _, jnb, nbrows = ledger(fin, nobase)
        check("no payment base date: rows are pending review and the case is in warnings", nbrows and all(x["reviewRequired"] and x["paymentStatus"] == "pending_review" for x in nbrows)
              and any(w["caseUid"] == str(nobase.case_uid) for w in jnb["warnings"]), nbrows[:1])
        r = pay(fin, nobase, key, 1); check("record against a pending-review item -> 400 schedule_pending_review", code(r) == "schedule_pending_review", code(r))

        # ================= 記付款：成功 =================
        before_entries = len(posted.payload["paymentEntries"])
        r = pay(fin, posted, key, 12.345, "2026-09-21", note="  first part  "); posted.refresh_from_db()
        j = r.json(); e = posted.payload["paymentEntries"][-1]
        check("record -> 200 {ok, rowVersion+1}", r.status_code == 200 and j == {"ok": True, "rowVersion": v0 + 1} and posted.row_version == v0 + 1, (r.status_code, j))
        check("entry appended with Alpha's fields", len(posted.payload["paymentEntries"]) == before_entries + 1 and e["entryType"] == "payment" and e["scheduleKey"] == key
              and e["installmentId"] == "case-effective-date" and e["partyType"] == "cedant" and e["partyName"] == ced["partyName"] and e["paymentDate"] == "2026-09-21"
              and e["note"] == "first part" and e["createdBy"] and e["createdByName"] == fin_p.name and uuid.UUID(e["id"]) and len(e["createdAt"]) == 24 and e["createdAt"].endswith("Z"), e)
        check("amount rounded like Math.round((x+EPSILON)*100)/100", e["amount"] == money(12.345), e["amount"])
        a = audit(posted.case_uid, "record_payment").order_by("-id").first()
        check("audit record_payment: before/after entries and metadata", a and a.before_data["rowVersion"] == v0 and len(a.before_data["paymentEntries"]) == before_entries
              and a.after_data == {"rowVersion": v0 + 1, "paymentEntries": posted.payload["paymentEntries"]}
              and a.metadata == {"paymentEntryId": e["id"], "scheduleKey": key, "amount": e["amount"], "paymentDate": "2026-09-21"}, a and (a.before_data, a.metadata))
        s = snaps(posted.case_uid, "payment_recorded").order_by("-id").first()
        check("snapshot payment_recorded at the new version (VM addition)", s and s.entity_version == v0 + 1 and s.snapshot_data["payload"]["paymentEntries"][-1]["id"] == e["id"])
        _, _, rows = ledger(fin, posted); ced2 = next(x for x in rows if x.get("scheduleKey") == key)
        check("ledger: paid, outstanding, partial, entry listed on the row", ced2["paid"] == e["amount"] and ced2["outstanding"] == money(ced["amount"] - e["amount"]) and ced2["partial"] is True
              and [x["id"] for x in ced2["entries"]][-1] == e["id"] and ced2["caseRowVersion"] == v0 + 1, ced2)
        check("ledger: the payment is listed only on its own row", all(x.get("entries", []) == [] for x in rows if x.get("scheduleKey") != key))
        r = pay(fin, posted, key, 1, note="n" * 1500); posted.refresh_from_db()
        check("note capped at 1000 characters", r.status_code == 200 and len(posted.payload["paymentEntries"][-1]["note"]) == 1000)
        _, _, rows = ledger(fin, posted); rest = next(x for x in rows if x.get("scheduleKey") == key)["outstanding"]
        r = pay(finm, posted, key, rest); posted.refresh_from_db()
        _, _, rows = ledger(fin, posted); ced3 = next(x for x in rows if x.get("scheduleKey") == key)
        check("paying the balance settles the row (finance manager)", r.status_code == 200 and ced3["outstanding"] == 0 and ced3["paymentStatus"] == "settled" and ced3["settlement"] == "settled" and ced3["partial"] is False, ced3)
        r = pay(fin, posted, key, 0.01); check("a settled row cannot take more money -> overpayment", code(r) == "overpayment")
        rclosed = pay(admin, closed, "case-effective-date:reinsurer:r1", 5); check("admin can record on a Confirmed case", rclosed.status_code == 200, rclosed.content[:200])

        # ================= 沖銷 =================
        posted.refresh_from_db(); v1 = posted.row_version; first = posted.payload["paymentEntries"][2]
        check("reverse: sales -> 403", post(sales, "reverse_payment", posted, entryId=first["id"]).status_code == 403)
        r = post(fin, "reverse_payment", posted, entryId=str(uuid.uuid4())); check("reverse: unknown entry -> 400 payment_not_found", code(r) == "payment_not_found")
        for label, date in (("text", "yesterday"), ("2026-13-01", "2026-13-01"), ("2026-02-30", "2026-02-30")):
            r = post(fin, "reverse_payment", posted, entryId=first["id"], paymentDate=date)
            check(f"reverse: date {label} -> 400 invalid_payment_date (VM)", r.status_code == 400 and code(r) == "invalid_payment_date", (r.status_code, code(r)))
        r = post(fin, "reverse_payment", posted, entryId=first["id"], rowVersion=v1 + 5); check("reverse: stale rowVersion -> 409 version_conflict", code(r) == "version_conflict")
        r = post(fin, "reverse_payment", draft, entryId=first["id"]); check("reverse on a Draft -> 409 accounting_status_locked (VM)", code(r) == "accounting_status_locked")
        check("reverse: failed attempts changed nothing", Case.objects.get(pk=posted.pk).row_version == v1)
        r = post(fin, "reverse_payment", posted, entryId="  " + first["id"] + " ", note=" wrong amount "); posted.refresh_from_db()
        rv = posted.payload["paymentEntries"][-1]
        check("reverse -> 200, reversal entry appended", r.status_code == 200 and r.json() == {"ok": True, "rowVersion": v1 + 1} and rv["entryType"] == "reversal" and rv["reversalOf"] == first["id"]
              and rv["amount"] == first["amount"] and rv["scheduleKey"] == key and rv["partyName"] == first["partyName"] and rv["note"] == "wrong amount", rv)
        check("reverse: default date is today in Taipei (VM)", rv["paymentDate"] == taipei_date(), (rv["paymentDate"], taipei_date()))
        check("reverse: original payment kept unchanged", posted.payload["paymentEntries"][2] == first)
        a = audit(posted.case_uid, "reverse_payment").order_by("-id").first()
        check("audit reverse_payment metadata", a and a.metadata == {"paymentEntryId": rv["id"], "reversalOf": first["id"], "scheduleKey": key, "amount": first["amount"]}, a and a.metadata)
        check("snapshot payment_reversed (VM addition)", snaps(posted.case_uid, "payment_reversed").filter(entity_version=v1 + 1).exists())
        _, _, rows = ledger(fin, posted); ced4 = next(x for x in rows if x.get("scheduleKey") == key)
        check("ledger: reversal puts the amount back as outstanding", ced4["outstanding"] == money(first["amount"]) and ced4["paymentStatus"] != "settled", ced4)
        r = post(fin, "reverse_payment", posted, entryId=first["id"]); check("reverse the same payment twice -> 409 already_reversed", r.status_code == 409 and code(r) == "already_reversed")
        r = post(fin, "reverse_payment", posted, entryId=rv["id"]); check("a reversal entry cannot itself be reversed -> payment_not_found", code(r) == "payment_not_found")
        r = post(fin, "reverse_payment", posted, entryId=posted.payload["paymentEntries"][3]["id"], paymentDate="2026-09-01"); posted.refresh_from_db()
        check("reverse with an explicit date keeps that date", r.status_code == 200 and posted.payload["paymentEntries"][-1]["paymentDate"] == "2026-09-01")
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Acc Insured").count())
