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
             reinsured="ZZ Acc Cedant", originalInsured="ZZ Acc Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0, paymentTermsDays=30), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0, paymentTermsDays=30)],   # 2026-10-16：每家再保人天數獨立填寫、不繼承
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
        for label, c in (("sales", sales), ("general manager", gm)):   # 2026-09-27：帳本唯讀
            r = call(c, "get", "/api/accounting")
            check(f"{label}: ledger read-only (200, canEdit false), record/reverse 403", r.status_code == 200 and r.json()["scope"]["canEdit"] is False
                  and code(call(c, "post", "/api/accounting", {"action": "record_payment"})) == "permission_denied"
                  and code(call(c, "post", "/api/accounting", {"action": "reverse_payment"})) == "permission_denied")
        check("viewer: no accounting.read -> GET and POST 403", call(viewer, "get", "/api/accounting").status_code == 403 and call(viewer, "post", "/api/accounting", {"action": "record_payment"}).status_code == 403)
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
        # 2026-10-16「92 項會計規則」：逾期以實際約定到期日（日期）判斷，不再附 12:00 時點 → dueTime 為空
        check("row fields: twRef, status, reinsured, currency, dueTime, settlement open, no entries", ced["twRef"] == posted.tw_ref and ced["caseStatus"] == "posted" and ced["reinsured"] == "ZZ Acc Cedant"
              and ced["currency"] == "USD" and ced["dueTime"] == "" and ced["settlement"] == "open" and ced["entries"] == [] and ced["source"] == "premium", ced)

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
        # 2026-10-16「92 項會計規則」：保費在 Production 關帳後才建立帳款；收付須逐筆對應已建立的交易。
        # 夾具：替 posted／closed／nobase 案件建立保費交易（模擬關帳），舊的「排程層級部分收款」改為逐筆整筆餘額登錄。
        def close_production(case):
            pp = copy.deepcopy(Case.objects.get(pk=case.pk).payload); pp["twRef"] = case.tw_ref; pp["transactions"] = build_premium_transactions(pp)
            Case.objects.filter(pk=case.pk).update(payload=pp); case.refresh_from_db(); return case
        def txs(case, leg): return [t["txNo"] for t in Case.objects.get(pk=case.pk).payload["transactions"] if t.get("legType") == leg]
        def detail(case, no): return transaction_details(Case.objects.get(pk=case.pk).payload)[no]
        def due(case, no): return abs(detail(case, no)["outstanding"])
        def txpay(c, case, amounts, date="2026-09-20", **extra):
            v = Case.objects.get(pk=case.pk).row_version
            return call(c, "post", "/api/accounting", {"action": "record_transaction_payments", "paymentDate": date, "amount": round(sum(amounts.values()), 2),
                        "allocations": [{"caseUid": str(case.case_uid), "rowVersion": v, "txNo": no, "amount": a} for no, a in amounts.items()], **extra})
        def reverse_batch(c, case, batch, **extra):
            return call(c, "post", "/api/accounting", {"action": "reverse_batch_payment", "batchId": batch, "cases": [{"caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version}], **extra})
        close_production(posted); close_production(closed)
        key = "case-effective-date:cedant"; rkey = "case-effective-date:reinsurer:r1"; r2key = "case-effective-date:reinsurer:r2"
        t1a, t1b = txs(posted, "Leg 1"); t2a, t2b = txs(posted, "Leg 2")
        v0 = posted.row_version
        check("sales cannot record payments (403)", pay(sales, posted, rkey, 10).status_code == 403 and txpay(sales, posted, {t2a: due(posted, t2a)}).status_code == 403)
        bad_inputs = [
            ("missing caseUid", dict(caseUid="")), ("missing scheduleKey", dict(scheduleKey="  ")), ("amount 0", dict(amount=0)), ("negative amount", dict(amount=-5)),
            ("amount text", dict(amount="abc")), ("amount missing", dict(amount=None)), ("amount Infinity text", dict(amount="Infinity")),
            ("date missing", dict(paymentDate="")), ("date 2026-13-45 (VM: real dates only)", dict(paymentDate="2026-13-45")),
            ("date 2026-02-30", dict(paymentDate="2026-02-30")), ("date 2026-2-3", dict(paymentDate="2026-2-3")), ("date with time", dict(paymentDate="2026-09-20T00:00")),
            ("date 0000-01-01", dict(paymentDate="0000-01-01")),
        ]
        for label, override in bad_inputs:
            body = {"action": "record_payment", "caseUid": str(posted.case_uid), "rowVersion": v0, "scheduleKey": rkey, "amount": 10, "paymentDate": "2026-09-20", **override}
            r = call(fin, "post", "/api/accounting", body)
            check(f"record: {label} -> 400 invalid_payment", r.status_code == 400 and code(r) == "invalid_payment", (r.status_code, code(r)))
        full_a = due(posted, t2a)
        r = pay(fin, posted, rkey, full_a, "2024-02-29"); check("record: leap day 2024-02-29 is accepted", r.status_code == 200, r.content[:200]); posted.refresh_from_db()
        # 讓後面從乾淨的餘額開始；2026-10-16：沖回整筆匯款須填原因
        r = reverse_batch(fin, posted, posted.payload["paymentEntries"][-1]["batchId"], note="QA reset"); posted.refresh_from_db()
        check("record: leap-day remittance reversed to restore a clean balance", r.status_code == 200 and due(posted, t2a) == full_a, r.content[:200])
        v0 = posted.row_version
        r = call(fin, "post", "/api/accounting", {"action": "record_payment", "caseUid": str(uuid.uuid4()), "rowVersion": 1, "scheduleKey": rkey, "amount": 1, "paymentDate": "2026-09-20"})
        check("record: unknown case -> 404", r.status_code == 404 and code(r) == "case_not_found")
        for label, uid in (("upper-case UUID", str(posted.case_uid).upper()), ("UUID without dashes", posted.case_uid.hex), ("not a UUID", "abc")):
            r = call(fin, "post", "/api/accounting", {"action": "record_payment", "caseUid": uid, "rowVersion": v0, "scheduleKey": rkey, "amount": 1, "paymentDate": "2026-09-20"})
            check(f"record: {label} -> 404 (same as Alpha's case_uid::text match)", r.status_code == 404, r.status_code)
        for label, c in (("Draft", draft), ("Reversed", rev)):
            r = pay(fin, c, key, 1); check(f"record on a {label} case -> 409 accounting_status_locked (VM)", r.status_code == 409 and code(r) == "accounting_status_locked", (r.status_code, code(r)))
        r = pay(fin, recycled, key, 1); check("record on a recycled Draft -> 404 (not found before the status check)", r.status_code == 404)
        r = pay(fin, posted, "case-effective-date:reinsurer:r9", 1); check("record: unknown schedule key -> 400 schedule_not_found", code(r) == "schedule_not_found")
        # 2026-10-16：排程層級登錄不得自動分配；Cedant 排程對應兩筆 T1（每家再保人各一）時須逐筆選擇交易
        r = pay(fin, posted, key, 10); check("record: schedule key mapping to several transactions -> 400 individual_transaction_required", r.status_code == 400 and code(r) == "individual_transaction_required", code(r))
        # 2026-10-16：保費每次須登錄整筆餘額，超過或不足都由整筆規則擋下（超額 overpayment 改於賠款測試）
        r = pay(fin, posted, rkey, full_a + 0.01); check("record: more than the premium balance -> 400 (whole balance required)", r.status_code == 400 and code(r) == "swiss_payment_blocked", code(r))
        r = pay(fin, posted, rkey, 10); check("record: partial premium -> 400 (whole balance required)", r.status_code == 400 and code(r) == "swiss_payment_blocked", code(r))
        r = pay(fin, posted, rkey, full_a, rowVersion=v0 - 1 if v0 > 1 else 99); check("record: stale rowVersion -> 409 version_conflict", r.status_code == 409 and code(r) == "version_conflict")
        r = call(fin, "post", "/api/accounting", {"action": "record_payment", "caseUid": str(posted.case_uid), "scheduleKey": rkey, "amount": full_a, "paymentDate": "2026-09-20"})
        # 2026-10-16：排程登錄改走逐筆交易登錄，缺 rowVersion 屬「缺少案件版本」的輸入錯誤（400 invalid_payment），同樣不寫入
        check("record: rowVersion missing -> rejected (400 invalid_payment)", r.status_code == 400 and code(r) == "invalid_payment", (r.status_code, code(r)))
        check("record: no failed attempt changed the case", Case.objects.get(pk=posted.pk).row_version == v0 and len(Case.objects.get(pk=posted.pk).payload["paymentEntries"]) == 2)
        nobase = make_case(sales, "posted")
        pb = copy.deepcopy(nobase.payload); pb["policyFrom"] = ""; Case.objects.filter(pk=nobase.pk).update(payload=pb); nobase.refresh_from_db()
        _, jnb, nbrows = ledger(fin, nobase)
        check("no payment base date: rows are pending review and the case is in warnings", nbrows and all(x["reviewRequired"] and x["paymentStatus"] == "pending_review" for x in nbrows)
              and any(w["caseUid"] == str(nobase.case_uid) for w in jnb["warnings"]), nbrows[:1])
        close_production(nobase)
        # 2026-10-16：缺漏日期／天數列待確認，不得收付（舊 schedule_pending_review 改由逐筆交易的 transaction_not_payable 擋下）
        r = pay(fin, nobase, rkey, due(nobase, txs(nobase, "Leg 2")[0])); check("record against a pending-review item -> 400 transaction_not_payable", r.status_code == 400 and code(r) == "transaction_not_payable", code(r))

        # ================= 記付款：成功 =================
        before_entries = len(posted.payload["paymentEntries"])
        # 金額先依 Math.round((x+EPSILON)*100)/100 取位，再比對整筆餘額
        r = pay(fin, posted, rkey, full_a + 0.004, "2026-09-21", note="  full balance  "); posted.refresh_from_db()
        j = r.json(); e = posted.payload["paymentEntries"][-1]
        check("record -> 200 {ok, batch, rowVersion+1}", r.status_code == 200 and j["ok"] is True and j["cases"] == [{"caseUid": str(posted.case_uid), "rowVersion": v0 + 1}] and j["batchId"] and posted.row_version == v0 + 1, (r.status_code, j))
        # 2026-10-16：收付逐筆對應交易，installmentId 取自該筆交易（單期交易無 installmentId）
        tx_a = next(t for t in posted.payload["transactions"] if t["txNo"] == t2a)
        check("entry appended with Alpha's fields plus its transaction", len(posted.payload["paymentEntries"]) == before_entries + 1 and e["entryType"] == "payment" and e["scheduleKey"] == rkey and e["transactionNo"] == t2a
              and e["installmentId"] == tx_a.get("installmentId") and t2a.startswith(posted.tw_ref + "-") and e["partyType"] == "reinsurer" and e["partyName"] == "ZZ Re A" and e["paymentDate"] == "2026-09-21"
              and e["note"] == "full balance" and e["createdBy"] and e["createdByName"] == fin_p.name and uuid.UUID(e["id"]) and len(e["createdAt"]) == 24 and e["createdAt"].endswith("Z"), e)
        check("amount rounded like Math.round((x+EPSILON)*100)/100 before the whole-balance check", e["amount"] == money(full_a + 0.004) == full_a, e["amount"])
        a = audit(posted.case_uid, "record_payment").order_by("-id").first()
        check("audit record_payment: before/after entries and metadata", a and a.before_data["rowVersion"] == v0 and len(a.before_data["paymentEntries"]) == before_entries
              and a.after_data == {"rowVersion": v0 + 1, "paymentEntries": posted.payload["paymentEntries"]}
              and a.metadata == {"operation": "record_transaction_payments", "batchId": e["batchId"], "batchAmount": e["amount"]}, a and (a.before_data, a.metadata))
        s = snaps(posted.case_uid, "payment_recorded").order_by("-id").first()
        check("snapshot payment_recorded at the new version (VM addition)", s and s.entity_version == v0 + 1 and s.snapshot_data["payload"]["paymentEntries"][-1]["id"] == e["id"])
        _, _, rows = ledger(fin, posted); r1row = next(x for x in rows if x.get("scheduleKey") == rkey)
        check("ledger: paid, outstanding 0, not partial, entry listed on the row, awaiting manual settlement", r1row["paid"] == e["amount"] and r1row["outstanding"] == 0 and r1row["partial"] is False
              and [x["id"] for x in r1row["entries"]][-1] == e["id"] and r1row["caseRowVersion"] == v0 + 1 and r1row["settlement"] == "pending_confirmation", r1row)
        check("ledger: the payment is listed only on its own row", all(x.get("entries", []) == [] for x in rows if x.get("scheduleKey") not in (rkey, None) and x.get("source") != "claim"))
        # Cedant：兩筆 T1 逐筆選擇、整筆餘額，一次登錄（財務主管）
        r = txpay(finm, posted, {t1a: due(posted, t1a), t1b: due(posted, t1b)}); posted.refresh_from_db()
        _, _, rows = ledger(fin, posted); ced3 = next(x for x in rows if x.get("scheduleKey") == key)
        check("paying every Cedant transaction in full awaits manual settlement (finance manager)", r.status_code == 200 and ced3["outstanding"] == 0 and ced3["paymentStatus"] == "pending_confirmation" and ced3["settlement"] == "pending_confirmation" and ced3["partial"] is False, ced3)
        cedant_batch = posted.payload["paymentEntries"][-1]["batchId"]
        # 2026-10-16：銷帳逐筆交易進行，排程層級銷帳回 individual_transaction_required
        r = post(finm, "confirm_facility_settlement", posted, scheduleKey=key, note="Bank and statement reconciled")
        check("schedule-level settlement -> 400 individual_transaction_required", r.status_code == 400 and code(r) == "individual_transaction_required", code(r))
        ok = all(post(finm, "confirm_facility_settlement", posted, txNo=no, note="Bank and statement reconciled").status_code == 200 for no in (t1a, t1b)); posted.refresh_from_db()
        _, _, rows = ledger(fin, posted); reconciled = next(x for x in rows if x.get("scheduleKey") == key)
        check("finance manager manually settles each cleared Cedant transaction", ok and reconciled["settlement"] == "settled", reconciled)
        r = txpay(fin, posted, {t1a: 0.01}); check("a settled transaction cannot take more money -> transaction_not_payable", code(r) == "transaction_not_payable", code(r))
        rclosed = pay(admin, closed, rkey, due(closed, txs(closed, "Leg 2")[0])); check("admin can record on a Confirmed case", rclosed.status_code == 200, rclosed.content[:200])

        # ================= 賠款：可部分收付 =================
        # 2026-10-16：賠款建立即建帳，建帳台灣日期＋15 日到期；只有賠款可部分收付，付出不得超過已收
        pc = copy.deepcopy(Case.objects.get(pk=posted.pk).payload)
        pc["transactions"] += [{"source": "claim", "txNo": "ZZ-CL-T1", "legType": "Claim Leg 1", "reinsurer": "ZZ Re A", "reinsurerIdx": 0, "amount": 100, "createdAt": "2026-09-01T02:00:00Z"},
                               {"source": "claim", "txNo": "ZZ-CL-T2", "legType": "Claim Leg 2", "reinsurer": "ZZ Re A", "reinsurerIdx": 0, "amount": 100, "createdAt": "2026-09-01T02:00:00Z"}]
        Case.objects.filter(pk=posted.pk).update(payload=pc); posted.refresh_from_db()
        check("claim due date is creation Taiwan date + 15", detail(posted, "ZZ-CL-T1")["contractDueDate"] == "2026-09-16", detail(posted, "ZZ-CL-T1").get("contractDueDate"))
        r = txpay(fin, posted, {"ZZ-CL-T1": 100.01}); check("claim: more than outstanding -> 400 overpayment", code(r) == "overpayment", code(r))
        r = txpay(fin, posted, {"ZZ-CL-T1": 12.35}, note="n" * 1500); posted.refresh_from_db()
        check("claim partial receipt keeps cents", r.status_code == 200 and detail(posted, "ZZ-CL-T1")["paid"] == 12.35 and detail(posted, "ZZ-CL-T1")["outstanding"] == 87.65, r.content[:200])
        check("note capped at 1000 characters", len(posted.payload["paymentEntries"][-1]["note"]) == 1000)
        r = txpay(fin, posted, {"ZZ-CL-T2": 20}); check("claim payment cannot exceed the amount received", r.status_code == 400, (r.status_code, code(r)))
        r = txpay(fin, posted, {"ZZ-CL-T2": 12.35}); check("claim payment up to the amount received", r.status_code == 200, r.content[:200])

        # ================= 沖銷 =================
        # 2026-10-16：API 登錄的收付皆屬整筆匯款（batchId），只能整筆沖回且須填原因；曾銷帳的金額永久鎖定。
        # 單筆 reverse_payment 保留給沒有 batchId 的舊收款紀錄：夾具注入兩筆舊式收款（ZZ Re B 排程）。
        posted.refresh_from_db(); pl = copy.deepcopy(posted.payload)
        legacy = [{"id": str(uuid.uuid4()), "entryType": "payment", "scheduleKey": r2key, "installmentId": "case-effective-date", "partyType": "reinsurer", "partyName": "ZZ Re B",
                   "amount": amt, "paymentDate": "2026-08-01", "createdAt": "2026-08-01T00:00:00.000Z", "createdBy": "legacy", "createdByName": "Legacy"} for amt in (50, 30)]
        pl["paymentEntries"] += legacy; Case.objects.filter(pk=posted.pk).update(payload=pl); posted.refresh_from_db()
        full_b = abs(next(t for t in posted.payload["transactions"] if t["txNo"] == t2b)["amount"])
        check("legacy schedule cash is counted on its single transaction", detail(posted, t2b)["paid"] == 80 and due(posted, t2b) == money(full_b - 80), detail(posted, t2b)["paid"])
        v1 = posted.row_version; first = legacy[0]
        check("reverse: sales -> 403", post(sales, "reverse_payment", posted, entryId=first["id"]).status_code == 403)
        r = post(fin, "reverse_payment", posted, entryId=str(uuid.uuid4())); check("reverse: unknown entry -> 400 payment_not_found", code(r) == "payment_not_found")
        for label, date in (("text", "yesterday"), ("2026-13-01", "2026-13-01"), ("2026-02-30", "2026-02-30")):
            r = post(fin, "reverse_payment", posted, entryId=first["id"], paymentDate=date)
            check(f"reverse: date {label} -> 400 invalid_payment_date (VM)", r.status_code == 400 and code(r) == "invalid_payment_date", (r.status_code, code(r)))
        r = post(fin, "reverse_payment", posted, entryId=first["id"], rowVersion=v1 + 5, note="stale"); check("reverse: stale rowVersion -> 409 version_conflict", code(r) == "version_conflict")
        r = post(fin, "reverse_payment", draft, entryId=first["id"]); check("reverse on a Draft -> 409 accounting_status_locked (VM)", code(r) == "accounting_status_locked")
        # 2026-10-16：更正須填原因
        r = post(fin, "reverse_payment", posted, entryId=first["id"]); check("reverse: missing reason -> 400 correction_reason_required", code(r) == "correction_reason_required", code(r))
        r = post(fin, "reverse_payment", posted, entryId=e["id"], note="batch entry"); check("reverse: a remittance entry must be reversed as a whole batch -> batch_reverse_required", code(r) == "batch_reverse_required", code(r))
        check("reverse: failed attempts changed nothing", Case.objects.get(pk=posted.pk).row_version == v1)
        r = post(fin, "reverse_payment", posted, entryId="  " + first["id"] + " ", note=" wrong amount "); posted.refresh_from_db()
        rv = posted.payload["paymentEntries"][-1]
        check("reverse -> 200, reversal entry appended", r.status_code == 200 and r.json() == {"ok": True, "rowVersion": v1 + 1} and rv["entryType"] == "reversal" and rv["reversalOf"] == first["id"]
              and rv["amount"] == first["amount"] and rv["scheduleKey"] == r2key and rv["partyName"] == first["partyName"] and rv["note"] == "wrong amount", rv)
        check("reverse: default date is today in Taipei (VM)", rv["paymentDate"] == taipei_date(), (rv["paymentDate"], taipei_date()))
        check("reverse: original payment kept unchanged", first in posted.payload["paymentEntries"])
        a = audit(posted.case_uid, "reverse_payment").order_by("-id").first()
        check("audit reverse_payment metadata", a and a.metadata == {"paymentEntryId": rv["id"], "reversalOf": first["id"], "scheduleKey": r2key, "amount": first["amount"]}, a and a.metadata)
        check("snapshot payment_reversed (VM addition)", snaps(posted.case_uid, "payment_reversed").filter(entity_version=v1 + 1).exists())
        check("ledger: reversal puts the amount back as outstanding", due(posted, t2b) == money(full_b - 30) and detail(posted, t2b)["settlement"] != "settled", detail(posted, t2b)["outstanding"])
        r = post(fin, "reverse_payment", posted, entryId=first["id"], note="again"); check("reverse the same payment twice -> 409 already_reversed", r.status_code == 409 and code(r) == "already_reversed")
        r = post(fin, "reverse_payment", posted, entryId=rv["id"], note="again"); check("a reversal entry cannot itself be reversed -> payment_not_found", code(r) == "payment_not_found")
        r = post(fin, "reverse_payment", posted, entryId=legacy[1]["id"], paymentDate="2026-09-01", note="explicit date"); posted.refresh_from_db()
        check("reverse with an explicit date keeps that date", r.status_code == 200 and posted.payload["paymentEntries"][-1]["paymentDate"] == "2026-09-01")
        # 整筆匯款沖回：未銷帳者可沖回；已銷帳者永久鎖定（取消銷帳亦不解鎖）
        r = reverse_batch(fin, posted, e["batchId"]); check("batch reverse: missing reason -> 400 correction_reason_required", code(r) == "correction_reason_required", code(r))
        r = reverse_batch(fin, posted, e["batchId"], note="Bank return", paymentDate="2026-09-22"); posted.refresh_from_db()
        check("batch reverse of an unsettled remittance restores the balance", r.status_code == 200 and due(posted, t2a) == full_a and posted.payload["paymentEntries"][-1]["reversalOf"] == e["id"], r.content[:200])
        r = reverse_batch(fin, posted, cedant_batch, note="Bank return"); check("batch reverse of settled cash -> 409 settled_amount_locked", r.status_code == 409 and code(r) == "settled_amount_locked", code(r))
        r = post(finm, "unconfirm_facility_settlement", posted, txNo=t1a, note="Reopen reconciliation")
        r2 = reverse_batch(fin, posted, cedant_batch, note="Bank return")
        check("cancelling settlement does not unlock the settled amount", r.status_code == 200 and r2.status_code == 409 and code(r2) == "settled_amount_locked", (r.status_code, code(r2)))
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Acc Insured").count())
