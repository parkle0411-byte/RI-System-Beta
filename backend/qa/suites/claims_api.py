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
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-CLM-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case
def ledger(c, case):
    return [x for x in call(c, "get", "/api/accounting").json().get("rows", []) if x["caseUid"] == str(case.case_uid)]
def claims(c, case):
    return call(c, "get", f"/api/claims?caseUid={case.case_uid}")
def act(c, action, case, root=None, **extra):
    body = {"action": action, "caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=(root or case).pk).row_version, **extra}
    return call(c, "post", "/api/claims", body)
def endorse(c, root, status, reinsurers=None, effective=None):
    e = make_case(c, "draft", **({"reinsurers": reinsurers} if reinsurers else {}))
    _ref[0] += 1
    # 2026-10-16「92 項會計規則重新確認」第 62 項：賠款採出險日適用且已生效的保單／批單比例，
    # 批單以 endoEffectiveDate 判斷是否生效，故 fixture 需明確給批單生效日。
    payload = {**e.payload, **({"endoEffectiveDate": effective} if effective else {})}
    Case.objects.filter(pk=e.pk).update(parent_case=root, case_kind="endorsement", status=status, payload=payload,
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
        for label, c in (("viewer", viewer),):
            check(f"{label}: no cases.read.all -> GET 403, POST 403", claims(c, root).status_code == 403 and act(c, "create_claim", root).status_code == 403)
        check("finance staff: claims GET allowed, POST denied", claims(fin, root).status_code == 200 and act(fin, "create_claim", root).status_code == 403)
        r = claims(gm, root)
        check("general manager: GET 200 (cases.read.all), no-store", r.status_code == 200 and r["Cache-Control"] == "no-store, max-age=0")
        check("general manager can write claims like Reinsurance Staff (2026-09-27): unsupported action 400, not 403", act(gm, "zz_unknown", root).status_code == 400)

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
        # 2026-10-16「92 項會計規則重新確認」第 62 項：分攤來源改為「出險日當天適用且已生效」的保單／批單，
        # 不再是「最新一張已 Announce／Confirmed 批單」。下方以出險日 2026-05-01 的理賠付款驗證：
        # 生效日 ≤ 出險日中最晚的已公告批單（e1）勝出；Draft 與封存批單即使生效日更晚也不採用。
        e_draft = endorse(sales, root, "draft", three, effective="2026-04-25")
        st = claims(sales, root).json()["claimsState"]
        check("a Draft endorsement is not the split source", st["splitSource"]["caseUid"] == str(root.case_uid))
        e_old = endorse(sales, root, "closed", effective="2026-04-01")   # 較早生效的已確認批單：出險日適用的是較晚生效的 e1
        e1 = endorse(sales, root, "posted", three, effective="2026-04-15")
        e_arch = endorse(sales, root, "closed", effective="2026-04-20"); Case.objects.filter(pk=e_arch.pk).update(is_archived=True, archived_at=timezone.now(), archived_by="t")
        st = claims(sales, root).json()["claimsState"]
        # 2026-10-16 第 62 項：GET 沒有出險日，畫面上的預設 splitSource 為根案件；實際分攤於付款時依出險日決定（見理賠付款段）。
        check("GET without a Date of Loss shows the root as the default split source", st["splitSource"]["caseUid"] == str(root.case_uid) and st["splitSource"]["twRef"] == root.tw_ref
              and len(st["splitSource"]["reinsurers"]) == 2, st["splitSource"]["caseUid"])
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
        for label, reserve in (("reserve text (Alpha stored 0)", "abc"), ("reserve negative", -1), ("reserve -0.5 text", "-0.5"), ("reserve Infinity", "Infinity"), ("reserve blank", ""), ("reserve zero", 0)):
            r = act(sales, "create_claim", root, claim={"dateOfLoss": "2026-05-01", "outstandingReserve": reserve})
            check(f"create: {label} -> 400 invalid_claim_reserve", r.status_code == 400 and code(r) == "invalid_claim_reserve", (r.status_code, code(r)))
        check("create: failed attempts changed nothing", Case.objects.get(pk=root.pk).row_version == v0 and Case.objects.get(pk=root.pk).payload == before)
        # 2026-11-14 owner decision (problem 11): Claim amounts beyond the currency precision are rejected, not rounded.
        r = act(sales, "create_claim", root, claim={"dateOfLoss": "2026-05-01", "outstandingReserve": "1,234.567"})
        check("create: USD reserve with three decimals -> 400 invalid_claim_precision", r.status_code == 400 and code(r) == "invalid_claim_precision", (r.status_code, code(r)))
        r = act(sales, "create_claim", root, claim={"lossNo": "  L" + "x" * 200, "dateOfLoss": "2026-05-01", "causeOfLoss": "c" * 2500, "outstandingReserve": "1,234.57"})
        j = r.json(); root.refresh_from_db(); c1 = root.payload["claims"][0]
        check("create -> 200 {ok, action, claimId 1, claimsState}", r.status_code == 200 and j["ok"] is True and j["action"] == "create_claim" and j["claimId"] == 1
              and j["claimsState"]["rootRowVersion"] == v0 + 1 and j["claimsState"]["claims"] == root.payload["claims"], j)
        check("claim fields: trimmed/capped text, reserve parsed with comma and rounded to cents (VM), no payments", c1["id"] == 1 and len(c1["lossNo"]) == 160 and c1["lossNo"].startswith("Lx")
              and len(c1["causeOfLoss"]) == 2000 and c1["outstandingReserve"] == 1234.57 and c1["payments"] == [] and c1["dateOfLoss"] == "2026-05-01", c1)
        Case.objects.filter(pk__in=[root.pk, e1.pk]).update(owner_personnel_id=view_p.pk)
        root_detail = call(viewer, 'get', '/api/cases?caseUid=' + str(root.case_uid))
        endo_detail = call(viewer, 'get', '/api/cases?caseUid=' + str(e1.case_uid))
        check('case viewers see the same policy-period Claim loss on original and endorsement', root_detail.status_code == 200 and endo_detail.status_code == 200
              and root_detail.json()['case']['claimLossRecord'] == endo_detail.json()['case']['claimLossRecord']
              and root_detail.json()['case']['claimLossRecord'][0]['lossPaid'] == 1234.57, (root_detail.content[:200], endo_detail.content[:200]))
        Case.objects.filter(pk__in=[root.pk, e1.pk]).update(owner_personnel_id=sales_p.pk)
        a = audit(root.case_uid, "create_claim").first()
        check("audit create_claim: before/after payload, metadata", a and a.metadata == {"claimId": 1, "action": "create_claim"} and a.before_data["rowVersion"] == v0
              and a.before_data["payload"].get("claims", []) == [] and a.after_data["payload"]["claims"][0]["id"] == 1)
        check("snapshot claim_created at the new version (VM addition)", snaps(root.case_uid, "claim_created").filter(entity_version=v0 + 1).exists())
        r = act(sales, "create_claim", e1, root=root, claim={"dateOfLoss": "2026-06-30", "outstandingReserve": 100}); root.refresh_from_db()
        check("create from an endorsement view: stored on the root as claim #2 with positive reserve", r.status_code == 200 and [c["id"] for c in root.payload["claims"]] == [1, 2]
              and root.payload["claims"][1]["outstandingReserve"] == 100 and (Case.objects.get(pk=e1.pk).payload or {}).get("claims") in (None, []), root.payload["claims"])

        # ================= 準備金 =================
        v1 = root.row_version
        r = act(sales, "update_reserve", root, claimId=99, outstandingReserve=1); check("reserve: unknown claim -> 404 claim_not_found", r.status_code == 404 and code(r) == "claim_not_found")
        r = act(sales, "update_reserve", root, outstandingReserve=1); check("reserve: claimId missing -> 404", code(r) == "claim_not_found")
        for bad in ("abc", -0.01, "1e999"):
            r = act(sales, "update_reserve", root, claimId=1, outstandingReserve=bad); check(f"reserve {bad!r} -> 400 invalid_claim_reserve", code(r) == "invalid_claim_reserve", code(r))
        r = act(sales, "update_reserve", root, claimId="1", outstandingReserve=5000.555)
        check("reserve with three decimals -> 400 invalid_claim_precision (2026-11-14)", r.status_code == 400 and code(r) == "invalid_claim_precision", code(r))
        r = act(sales, "update_reserve", root, claimId="1", outstandingReserve=5000.56); root.refresh_from_db()
        check("reserve updated (claimId as text works like Number())", r.status_code == 200 and root.payload["claims"][0]["outstandingReserve"] == 5000.56 and root.row_version == v1 + 1, r.content[:200])
        check("audit update_claim_reserve + snapshot claim_reserve_updated", audit(root.case_uid, "update_claim_reserve").first().metadata == {"claimId": 1, "action": "update_reserve"}
              and snaps(root.case_uid, "claim_reserve_updated").exists())
        r = act(sales, "update_reserve", root, claimId=1, outstandingReserve=""); root.refresh_from_db()
        check("reserve blank -> 0 (same as Alpha)", r.status_code == 200 and root.payload["claims"][0]["outstandingReserve"] == 0)

        # ================= 理賠付款 =================
        v2 = root.row_version
        for label, pay in (("amount 0", {"amount": 0, "date": "2026-07-01"}), ("amount text", {"amount": "abc", "date": "2026-07-01"}), ("amount missing", {"date": "2026-07-01"})):
            r = act(sales, "record_payment", root, claimId=1, payment=pay); check(f"payment: {label} -> 400 payment_amount_required", r.status_code == 400 and code(r) == "payment_amount_required", (r.status_code, code(r)))
        r = act(sales, "record_payment", root, claimId=1, payment={"amount": 0.004, "date": "2026-07-01"})
        check("payment: USD 0.004 exceeds two decimals -> 400 invalid_claim_precision (2026-11-14)", r.status_code == 400 and code(r) == "invalid_claim_precision", (r.status_code, code(r)))
        for label, pay in (("date missing (VM: required)", {"amount": 10}), ("date 2026-13-01", {"amount": 10, "date": "2026-13-01"}), ("date text", {"amount": 10, "date": "soon"})):
            r = act(sales, "record_payment", root, claimId=1, payment=pay); check(f"payment: {label} -> 400 invalid_payment_date", r.status_code == 400 and code(r) == "invalid_payment_date", (r.status_code, code(r)))
        r = act(sales, "record_payment", root, claimId=5, payment={"amount": 10, "date": "2026-07-01"}); check("payment: unknown claim -> 404", code(r) == "claim_not_found")
        check("payment: failed attempts changed nothing", Case.objects.get(pk=root.pk).row_version == v2)
        r = act(sales, "record_payment", e1, root=root, claimId=1, payment={"amount": "1,000.01", "date": "2026-07-01", "note": " first "}); root.refresh_from_db()
        p1 = root.payload["claims"][0]["payments"][0]; tx = [t for t in root.payload.get("transactions", []) if t.get("source") == "claim"]
        # 2026-10-16「92 項會計規則重新確認」：付款紀錄另存伺服器建立時間 createdAt（到期日起算）及出險日適用的 splitSource；
        # 原本的 id／日期／金額／備註斷言不變，splitSource 必須是出險日（2026-05-01）適用的 e1（Archived／Draft 不採用）。
        check("payment recorded: id 1, amount parsed and rounded, note trimmed", r.status_code == 200 and {k: p1.get(k) for k in ("id", "date", "amount", "note")} == {"id": 1, "date": "2026-07-01", "amount": 1000.01, "note": "first"}
              and bool(p1.get("createdAt")), (r.status_code, p1))
        check("Date of Loss split source: the latest Announced/Confirmed endorsement effective on the Date of Loss (archived/draft ignored)",
              p1.get("splitSource", {}).get("caseUid") == str(e1.case_uid) and p1["splitSource"]["twRef"] == e1.tw_ref and len(p1["splitSource"]["reinsurers"]) == 3, p1.get("splitSource"))
        # 2026-10-16 第 71／72 項：賠款從建立帳款當天台灣日期起算 15 日到期。
        from cases.calc.payment_terms import taipei_date, add_calendar_days
        check("claim obligations due on creation Taiwan date + 15 days", tx and all(t.get("dueDate") == add_calendar_days(taipei_date(p1["createdAt"]), 15) for t in tx), [t.get("dueDate") for t in tx[:2]])
        check("transactions: Claim Leg 1 + Leg 2 per reinsurer of the split source (3 -> 6)", len(tx) == 6 and [t["legType"] for t in tx[:2]] == ["Claim Leg 1", "Claim Leg 2"], len(tx))
        check("VM fix: transaction numbers start with the root TW Ref (Alpha: 'undefined')", all(t["txNo"].startswith(root.tw_ref + "-C1-P1-R") for t in tx) and not any("undefined" in t["txNo"] for t in tx), [t["txNo"] for t in tx[:2]])
        check("shares follow the endorsement split: 50% / 30% / 20%", [t["amount"] for t in tx[::2]] == [money(1000.01 * 0.5), money(1000.01 * 30 / 100), money(1000.01 * 20 / 100)], [t["amount"] for t in tx[::2]])
        check("reinsurerIdx maps to the root lines by name (Re C is not on the root -> null); broker used as settlement party",
              [t["reinsurerIdx"] for t in tx[::2]] == [0, None, 1] and tx[4]["reinsurer"] == "ZZ Broker" and tx[4]["viaForeignBroker"] is True, [(t["reinsurerIdx"], t["reinsurer"]) for t in tx[::2]])
        check("audit record_claim_payment + snapshot claim_payment_recorded", audit(root.case_uid, "record_claim_payment").first().metadata == {"claimId": 1, "action": "record_payment"}
              and snaps(root.case_uid, "claim_payment_recorded").filter(entity_version=v2 + 1).exists())
        r = act(sales, "record_payment", root, claimId=1, payment={"amount": -200, "date": "2026-07-02"}); root.refresh_from_db()
        tx2 = [t for t in root.payload["transactions"] if "-C1-P2-" in t["txNo"]]
        check("negative payment allowed (recovery / correction), payment id 2, negative transactions", r.status_code == 200 and root.payload["claims"][0]["payments"][1]["amount"] == -200
              and len(tx2) == 6 and all(t["amount"] < 0 for t in tx2), r.content[:200])
        loss_rows = claims(sales, root).json()['claimsState']['claimLossRecord']
        check('claim loss record includes reserve and signed obligations in original currency', loss_rows[0]['claimId'] == 1 and loss_rows[0]['currency'] == 'USD' and loss_rows[0]['lossPaid'] == 800.01, loss_rows)
        rows = [x for x in ledger(fin, root) if x["source"] == "claim"]
        check("claim transactions appear in the Accounting ledger", len(rows) == 12 and all(x["settlement"] == "open" for x in rows), len(rows))
        # 2026-10-16「92 項會計規則重新確認」第 65／71 項：GET 對每筆付款另加顯示用 canCorrect（可否更正）與 dueDate（建帳台灣日＋15）；
        # 去掉這兩個顯示欄位後須與儲存內容完全一致，並確認顯示值正確。
        shown = claims(sales, e1).json()["claimsState"]["claims"]
        stripped = [{**cl, "payments": [{k: v for k, v in pay.items() if k not in ("canCorrect", "dueDate")} for pay in cl["payments"]]} for cl in shown]
        check("GET shows the claims with payments", stripped == root.payload["claims"]
              and [pay["dueDate"] for pay in shown[0]["payments"]] == [add_calendar_days(taipei_date(pay["createdAt"]), 15) for pay in root.payload["claims"][0]["payments"]]
              and all(pay["canCorrect"] is True for pay in shown[0]["payments"]), shown[0]["payments"])
        # 2026-10-16 第 62 項：出險日不在任何保單／批單期間 -> claim_split_pending_review，不寫入付款或交易。
        r = act(sales, "create_claim", root, claim={"dateOfLoss": "2028-01-01", "outstandingReserve": 100}); root.refresh_from_db(); v3 = root.row_version; before = root.payload
        r = act(sales, "record_payment", root, claimId=3, payment={"amount": 10, "date": "2028-01-02"}); root.refresh_from_db()
        check("Date of Loss outside every policy/endorsement period -> claim_split_pending_review, nothing written", code(r) == "claim_split_pending_review" and root.row_version == v3 and root.payload == before, (r.status_code, code(r)))
        # Changing the loss date must preserve already-created obligations and ledger entries.
        before_tx = copy.deepcopy(root.payload.get('transactions', []))
        before_payments = copy.deepcopy(root.payload['claims'][0]['payments'])
        r = act(sales, 'update_loss_date', root, claimId=1, dateOfLoss='2026-06-01', reason='')
        check('loss date change requires a reason', r.status_code == 400 and code(r) == 'correction_reason_required')
        r = act(sales, 'update_loss_date', root, claimId=1, dateOfLoss='2026-02-30', reason='Correct date')
        check('loss date change rejects invalid calendar dates', r.status_code == 400 and code(r) == 'invalid_date_of_loss')
        r = act(sales, 'update_loss_date', root, claimId=1, dateOfLoss='2026-06-01', reason='Correct date'); root.refresh_from_db()
        history = root.payload['claims'][0].get('lossDateHistory', [])
        check('loss date change preserves existing obligations and transactions', r.status_code == 200 and root.payload.get('transactions', []) == before_tx and root.payload['claims'][0]['payments'] == before_payments, r.content[:200])
        check('loss date change records old date, new date, reason and actor', bool(history) and history[-1].get('before') == '2026-05-01' and history[-1].get('after') == '2026-06-01' and history[-1].get('reason') == 'Correct date' and bool(history[-1].get('changedAt')) and bool(history[-1].get('changedBy')), history)
        old_cause = root.payload['claims'][0].get('causeOfLoss') or ''
        r = act(sales, 'update_cause', root, claimId=1, causeOfLoss='Updated cause'); root.refresh_from_db()
        from cases.claim_loss_record import claim_loss_rows
        cause_history = root.payload['claims'][0].get('causeHistory', [])
        check('claim cause change updates derived loss record and preserves accounting', r.status_code == 200 and claim_loss_rows(root.payload)[0]['cause'] == 'Updated cause' and root.payload.get('transactions', []) == before_tx and root.payload['claims'][0]['payments'] == before_payments, r.content[:200])
        check('claim cause change records before, after and actor', bool(cause_history) and cause_history[-1].get('before') == old_cause and cause_history[-1].get('after') == 'Updated cause' and bool(cause_history[-1].get('changedBy')), cause_history)
        r = act(sales, 'update_cause', root, claimId=1, causeOfLoss=None)
        check('claim cause change rejects non-text input', r.status_code == 400 and code(r) == 'invalid_cause')
        multi = make_case(sales, 'posted', classOfBusiness='Commercial General Liability', classCode='GL', typePrefix='Commercial General Liability',
                          reinsurers=[dict(name='ZZ Re A', sharePct=60, premium=600, riCommPct=5, taxPct=0, paymentTermsDays=90),
                                      dict(name='ZZ Re B', sharePct=40, premium=400, riCommPct=5, taxPct=0, paymentTermsDays=90)])
        r = act(sales, 'create_claim', multi, claim={'dateOfLoss':'2026-05-01', 'outstandingReserve':100, 'currency':'TWD'}); multi.refresh_from_db()
        check('multi-currency claim uses selected currency', r.status_code == 200 and multi.payload['claims'][0].get('currency') == 'TWD', r.content[:300])
        r = act(sales, 'record_payment', multi, claimId=1, payment={'date':'2026-06-01', 'amount':101}); multi.refresh_from_db()
        multi_tx = [t for t in multi.payload.get('transactions', []) if t.get('source') == 'claim']
        check('claim obligations use claim currency and integer TWD shares', r.status_code == 200 and len(multi_tx) == 4 and all(t.get('currency') == 'TWD' and t['amount'] == int(t['amount']) for t in multi_tx), multi_tx)
        accounting = call(fin, 'get', '/api/accounting').json()
        original_rows = [row for row in accounting.get('transactionRows', []) if row.get('caseUid') == str(multi.case_uid) and row.get('source') == 'claim']
        check('multi-currency Claim Accounting rows do not display FX conversions', len(original_rows) == 4 and all(row.get('currency') == 'TWD' and row.get('amountNtd') is None and row.get('outstandingNtd') is None and row.get('fxNotApplicable') is True for row in original_rows), original_rows)
        from dashboard.calc import build_dashboard
        from production.views import case_source
        metrics = build_dashboard([case_source(multi)], [], [], timezone.now(), production_rules=True)['metrics']
        claim_totals = metrics.get('claimOutstandingByCurrency') or []
        # 2026-11-15 owner decision (conflict 2): the Dashboard converts every Claim into the TWD
        # receivable / payable totals; Accounting keeps the original-currency display above.
        check('Dashboard converts Claim receivables and payables into the TWD totals', claim_totals == []
              and metrics['outstandingLeg1Ntd'] == 101 and metrics['outstandingLeg2Ntd'] == 101, metrics)
        before_numbers = [t['txNo'] for t in multi_tx]
        r = act(sales, 'update_currency', multi, claimId=1, currency='USD', reason='Correct currency'); multi.refresh_from_db()
        changed = [t for t in multi.payload.get('transactions', []) if t.get('source') == 'claim']
        check('currency correction changes every transaction, not identifiers', r.status_code == 200 and [t['txNo'] for t in changed] == before_numbers and all(t.get('currency') == 'USD' for t in changed), r.content[:300])
        check('currency correction preserves before and after history', len(multi.payload['claims'][0].get('currencyHistory', [])) == 1, multi.payload['claims'][0])
        r = act(sales, 'create_claim', multi, claim={'dateOfLoss':'2026-05-01', 'outstandingReserve':10, 'currency':'EUR'}); multi.refresh_from_db()
        r2 = act(sales, 'record_payment', multi, claimId=2, payment={'date':'2026-06-01', 'amount':25}); multi.refresh_from_db()
        metrics = build_dashboard([case_source(multi)], [], [], timezone.now(), production_rules=True)['metrics']
        missing = {row['currency'] for row in metrics['missingPostingRates']}
        check('Claims in other currencies convert at their own currency; without FX they are reported as Awaiting FX', r.status_code == 200 and r2.status_code == 200
              and not metrics.get('claimOutstandingByCurrency') and {'USD','EUR'} <= missing and metrics['outstandingLeg1Ntd'] == 0, metrics['missingPostingRates'])
        fx_rows = [{'year_month': timezone.localtime().strftime('%Y-%m'), 'currency': cur, 'rate': rate} for cur, rate in (('USD', 30.0), ('EUR', 35.0))]
        metrics = build_dashboard([case_source(multi)], [], fx_rows, timezone.now(), production_rules=True)['metrics']
        check('with FX, Claim receivables convert at each Claim currency (USD 101 x 30 + EUR 25 x 35)', round(metrics['outstandingLeg1Ntd'], 2) == 101 * 30 + 25 * 35, metrics['outstandingLeg1Ntd'])
        compact = call(fin, 'get', '/api/accounting?view=list').json()
        check('Accounting currency filter includes each Claim transaction currency', {'USD','EUR'} <= set(compact.get('currencies') or []), compact.get('currencies'))
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Clm Insured").count())
