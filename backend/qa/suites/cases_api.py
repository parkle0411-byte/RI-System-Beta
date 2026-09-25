import copy
import json
import uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case
from cases.calc.totals import list_financials
from masterdata.models import MasterRecord
from personnel.models import Personnel

User = get_user_model()

# 測試自己建立臨時人員與帳號（在會回滾的交易內），不依賴真實資料
_DEPT = {"admin": "admin", "sales": "reinsurance", "accounting": "finance", "general_manager": "reinsurance",
         "viewer": "business_1"}
_seq = [0]
def person(role, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=kw.pop("name", f"ZZ C {role} {_seq[0]}"), department=kw.pop("department", _DEPT[role]),
                                    role_code=role, created_by="t", updated_by="t", **kw)
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass

def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf")
    kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.c.{tag}", password="Case-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Case-Test-Pass-1"}),
               content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

def body(**over):
    base = dict(originalInsured="ZZ Insured", reinsured="ZZ Cedant", classOfBusiness="ZZ Class", currency="USD",
                policyFrom="2026-01-01", policyTo="2026-12-31", originalPremium=1000, riCommPct=10, taxPct=0,
                paymentTermsDays=30,
                reinsurers=[dict(name="ZZ Re", sharePct=100, premium=1000, riCommPct=5, taxPct=0)])
    base.update(over); return base
def create(c, **over):
    r = call(c, "post", "/api/cases", {"case": body(**over)}); return r
def load(c, uid): return call(c, "get", f"/api/cases?caseUid={uid}").json()["case"]
def put(c, uid, version, case_body, **extra): return call(c, "put", "/api/cases", {"caseUid": uid, "rowVersion": version, "case": case_body, **extra})
def audit(uid, action=None):
    q = AuditLog.objects.filter(entity_type="case", entity_id=str(uid))
    return q.filter(action=action) if action else q

try:
    with transaction.atomic():
        sales_p, admin_p, acct_p, view_p, other_p = person("sales"), person("admin"), person("accounting"), person("viewer"), person("sales")
        sales, admin, acct, viewer = account(sales_p, "sales"), account(admin_p, "admin"), account(acct_p, "acct"), account(view_p, "view")

        # --- 權限 ---
        anon = new_client()
        check("anonymous GET -> 401", call(anon, "get", "/api/cases").status_code == 401)
        r = call(acct, "get", "/api/cases"); check("accounting (no dashboard/cases read) GET -> 403 PERMISSION_DENIED", r.status_code == 403 and code(r) == "PERMISSION_DENIED", (r.status_code, code(r)))
        r = call(acct, "post", "/api/cases", {"case": body()}); check("accounting POST -> 403", r.status_code == 403)
        r = call(viewer, "post", "/api/cases", {"case": body()}); check("viewer (read only) POST -> 403", r.status_code == 403)
        r = call(viewer, "put", "/api/cases", {"caseUid": str(uuid.uuid4()), "rowVersion": 1, "case": body()}); check("viewer PUT -> 403", r.status_code == 403)
        check("responses are no-store", call(sales, "get", "/api/cases")["Cache-Control"] == "no-store, max-age=0")

        # --- 新增 Draft ---
        base_audits = AuditLog.objects.count()
        r = create(sales); j = r.json()
        check("create -> 201 with uid/status/rowVersion", r.status_code == 201 and j["case"]["status"] == "draft" and j["case"]["rowVersion"] == 1, (r.status_code, j))
        uid = j["case"]["caseUid"]; row = Case.objects.get(case_uid=uid)
        check("default owner = the logged-in person", row.owner_personnel_id == sales_p.pk and row.payload["ownerPersonnelName"] == sales_p.name)
        check("columns/snapshots filled (currency, dates, structure, names)", row.currency == "USD" and str(row.effective_date) == "2026-01-01"
              and str(row.expiration_date) == "2026-12-31" and row.reinsured_name_snapshot == "ZZ Cedant" and row.class_name_snapshot == "ZZ Class"
              and row.case_kind == "original" and row.tw_ref is None and row.created_by == f"personnel:{sales_p.pk}")
        snaps = EntitySnapshot.objects.filter(entity_type="case", entity_id=uid)
        check("one snapshot draft_created v1", snaps.count() == 1 and snaps[0].snapshot_reason == "draft_created" and snaps[0].entity_version == 1)
        a = audit(uid)
        check("one audit event create_draft with actor + payload", a.count() == 1 and a[0].action == "create_draft" and a[0].before_data is None
              and a[0].actor_id == f"personnel:{sales_p.pk}" and a[0].actor_role == "sales" and a[0].after_data["payload"]["currency"] == "USD")
        n = Case.objects.count()
        r = create(sales, currency="US"); check("validation error -> 400 validation_failed with errors[]", r.status_code == 400 and code(r) == "validation_failed" and r.json()["errors"], r.content[:120])
        check("failed create wrote nothing", Case.objects.count() == n and AuditLog.objects.count() == base_audits + 1)
        r = call(sales, "post", "/api/cases", {"nope": 1}); check("missing case object -> 400", r.status_code == 400)

        # --- 負責人 ---
        r = create(sales, ownerPersonnelId=other_p.pk); o = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
        check("explicit active owner accepted (name taken from Personnel)", r.status_code == 201 and o.owner_personnel_id == other_p.pk and o.payload["ownerPersonnelName"] == other_p.name)
        gone = person("sales", is_active=False, deactivated_by="t", deactivated_at="2026-01-01T00:00:00Z")
        r = create(sales, ownerPersonnelId=gone.pk); check("inactive owner refused for new selection", r.status_code == 400 and code(r) == "invalid_case_owner")
        r = create(sales, ownerPersonnelId=99999999); check("unknown owner -> 400 invalid_case_owner", r.status_code == 400 and code(r) == "invalid_case_owner")

        # --- Performance Split ---
        p1, p2 = person("sales"), person("viewer")
        ns = person("sales", is_split_eligible=False)
        def split(*ids, **kw): return dict(splitEnabled=True, splitParties=[dict(personnelId=i, name="x", pct=50) for i in ids], **kw)
        r = create(sales, **split(p1.pk, p2.pk)); s = Case.objects.get(case_uid=r.json()["case"]["caseUid"]) if r.status_code == 201 else None
        check("split with two eligible people -> 201; names replaced from Personnel", r.status_code == 201 and [x["name"] for x in s.payload["splitParties"]] == [p1.name, p2.name], r.content[:150])
        r = create(sales, **split(p1.pk, ns.pk)); check("non-split-eligible person refused", r.status_code == 400 and code(r) == "invalid_personnel_split")
        r = create(sales, **split(p1.pk, gone.pk)); check("inactive person refused", r.status_code == 400 and code(r) == "invalid_personnel_split")
        r = create(sales, **split(p1.pk, p1.pk)); check("same person twice refused", r.status_code == 400 and code(r) == "invalid_personnel_split")
        r = create(sales, **split(p1.pk, 99999999)); check("unknown person refused", r.status_code == 400 and code(r) == "invalid_personnel_split")
        r = create(sales, splitEnabled=True, splitParties=[dict(name=p1.name.upper(), pct=50), dict(name=p2.name, pct=50)])
        check("name-only reference resolved case-insensitively", r.status_code == 201, r.content[:150])
        dup_a, dup_b = person("sales", name="ZZ Twin", department="reinsurance"), person("viewer", name="ZZ Twin", department="business_2")
        r = create(sales, splitEnabled=True, splitParties=[dict(name="ZZ Twin", pct=50), dict(personnelId=p1.pk, pct=50)])
        check("name-only reference matching two people is refused (ambiguous)", r.status_code == 400 and code(r) == "invalid_personnel_split" and "more than one" in r.json()["message"], r.content[:200])
        r = create(sales, splitEnabled=False, splitParties=[dict(personnelId=ns.pk, pct=50)])
        check("splitEnabled=false skips split validation", r.status_code == 201, r.content[:120])

        # --- 主檔參照 ---
        ae = MasterRecord.objects.create(entity_type="ae", name="ZZ AE One", display_order=5, created_by="t", updated_by="t")
        cafe = MasterRecord.objects.create(entity_type="class", name="ZZ Café Class", display_order=1, created_by="t", updated_by="t")
        off = MasterRecord.objects.create(entity_type="reinsured", name="ZZ Off Cedant", is_active=False, deactivated_by="t", deactivated_at="2026-01-01T00:00:00Z", created_by="t", updated_by="t")
        r = create(sales, ae="zz ae one", classOfBusiness="ZZ Café Class", reinsured="ZZ Off Cedant"); m = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
        check("master refs: AE matched case-insensitively", m.ae_master_id == ae.pk and m.ae_name_snapshot == "zz ae one")
        check("master refs: inactive master not linked", m.reinsured_master_id is None)
        check("master refs: exact class name linked", m.class_master_id == cafe.pk)
        r = create(sales, classOfBusiness="ZZ Cafe Class"); m = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
        check("master refs: accent-different name NOT linked (Alpha compares lower(name) exactly)", m.class_master_id is None)

        # --- 列表 / 範圍 ---
        mine = Case.objects.get(case_uid=create(sales, ownerPersonnelId=view_p.pk).json()["case"]["caseUid"])
        others = Case.objects.get(case_uid=create(sales, ownerPersonnelId=other_p.pk).json()["case"]["caseUid"])
        with_split = Case.objects.get(case_uid=create(sales, ownerPersonnelId=other_p.pk, splitEnabled=True,
            splitParties=[dict(personnelId=view_p.pk, name="x", pct=50), dict(personnelId=p1.pk, name="y", pct=50)]).json()["case"]["caseUid"])
        recycled = Case.objects.get(case_uid=create(sales, ownerPersonnelId=view_p.pk).json()["case"]["caseUid"]); Case.objects.filter(pk=recycled.pk).update(recycled_at="2026-01-01T00:00:00Z", recycled_by="t")
        archived = Case.objects.get(case_uid=create(sales, ownerPersonnelId=view_p.pk).json()["case"]["caseUid"]); Case.objects.filter(pk=archived.pk).update(status="posted", is_archived=True, archived_by="t", archived_at="2026-01-01T00:00:00Z")
        child = Case.objects.get(case_uid=create(sales, ownerPersonnelId=view_p.pk).json()["case"]["caseUid"]); Case.objects.filter(pk=child.pk).update(parent_case=mine)
        Case.objects.filter(pk=mine.pk).update(status="posted", tw_ref="ZZ-TEST-1")
        j = call(viewer, "get", "/api/cases").json(); uids = [c["caseUid"] for c in j["cases"]]
        check("viewer sees own-owned + split-member cases only", set(uids) >= {str(mine.case_uid), str(with_split.case_uid)} and str(others.case_uid) not in uids, uids)
        check("viewer list excludes recycled / archived / child cases", not ({str(recycled.case_uid), str(archived.case_uid), str(child.case_uid)} & set(uids)))
        real_viewer_cases = [c for c in j["cases"] if not c["caseUid"] in {str(mine.case_uid), str(with_split.case_uid)}]
        check("viewer list contains nothing else", not real_viewer_cases, real_viewer_cases[:1])
        check("summary counts match (2 in scope: 1 posted + 1 draft)", j["summary"] == {"total": 2, "draft": 1, "posted": 1, "closed": 0, "reversed": 0}, j["summary"])
        big = call(sales, "get", "/api/cases").json()
        check("sales sees every non-recycled top-level case (incl. others')", {str(others.case_uid), str(mine.case_uid)} <= {c["caseUid"] for c in big["cases"]}
              and str(recycled.case_uid) not in {c["caseUid"] for c in big["cases"]})
        ups = [c["updatedAt"] for c in big["cases"]]
        check("list sorted by updated_at desc", ups == sorted(ups, reverse=True))
        it = next(c for c in j["cases"] if c["caseUid"] == str(mine.case_uid))
        fin = list_financials(mine.payload)
        check("list row: financials from unified ledger algorithm", it["ourSharePremium"] == fin["ourSharePremium"] and it["brokerage"] == fin["brokerage"] and it["ourSharePremium"] == 1000, it)
        check("list row: fields", it["twRef"] == "ZZ-TEST-1" and it["reinsurers"] == ["ZZ Re"] and it["currency"] == "USD" and it["reinsured"] == "ZZ Cedant"
              and it["className"] == "ZZ Class" and it["effectiveDate"] == "2026-01-01" and it["effectiveTime"] == "12:00"
              and it["ownerPersonnelId"] == view_p.pk and it["originalInsured"] == "ZZ Insured" and isinstance(it["id"], int) and isinstance(it["rowVersion"], int), it)
        MasterRecord.objects.create(entity_type="reinsurer", name="ZZ Re", payload={"abbreviation": "ZR"}, created_by="t", updated_by="t")
        it = next(c for c in call(viewer, "get", "/api/cases").json()["cases"] if c["caseUid"] == str(mine.case_uid))
        check("list row: reinsurer abbreviation used for display name", it["reinsurerDisplayNames"] == ["ZR"] and it["reinsuredDisplayName"] == "ZZ Cedant", it)

        # --- 單筆 ---
        r = call(viewer, "get", f"/api/cases?caseUid={mine.case_uid}"); c = r.json()["case"]
        check("get one -> payload + rowVersion + status", r.status_code == 200 and c["caseUid"] == str(mine.case_uid) and c["rowVersion"] == 1 and c["status"] == "posted" and c["payload"]["currency"] == "USD")
        check("viewer cannot get someone else's case -> 404", call(viewer, "get", f"/api/cases?caseUid={others.case_uid}").status_code == 404)
        check("sales can get anyone's", call(sales, "get", f"/api/cases?caseUid={others.case_uid}").status_code == 200)
        check("unknown / malformed uid -> 404 case_not_found", code(call(sales, "get", f"/api/cases?caseUid={uuid.uuid4()}")) == "case_not_found" and call(sales, "get", "/api/cases?caseUid=not-a-uuid").status_code == 404)
        check("recycled case not gettable", call(sales, "get", f"/api/cases?caseUid={recycled.case_uid}").status_code == 404)
        Case.objects.filter(pk=mine.pk).update(payload={**mine.payload, "transactions": [
            {"legType": "Leg 1 (Cedant)", "amount": 5}, {"source": "claim", "settlement": "settled"}, {"legType": "Commission"}]})
        tx = load(viewer, mine.case_uid)["payload"]["transactions"]
        check("get one: derived paymentScheduleSettlement attached, stored payload untouched",
              all("paymentScheduleSettlement" in t for t in tx) and tx[1]["paymentScheduleSettlement"] == "settled" and tx[2]["paymentScheduleSettlement"] == "not_tracked"
              and "paymentScheduleSettlement" not in Case.objects.get(pk=mine.pk).payload["transactions"][0], tx)

        # --- 編輯 ---
        r = create(sales); uid = r.json()["case"]["caseUid"]; base_payload = load(sales, uid)["payload"]
        r = call(sales, "put", "/api/cases", {"rowVersion": 1, "case": base_payload}); check("PUT without caseUid -> 400 case_uid_required", code(r) == "case_uid_required")
        for bad in (None, 0, "x", -1, 1.5, ""):
            r = call(sales, "put", "/api/cases", {"caseUid": uid, "rowVersion": bad, "case": base_payload}); check(f"PUT rowVersion={bad!r} -> 400 row_version_required", code(r) == "row_version_required", (r.status_code, code(r)))
        check("PUT unknown case -> 404", put(sales, str(uuid.uuid4()), 1, base_payload).status_code == 404)
        tmp = create(sales).json()["case"]["caseUid"]
        r = put(sales, tmp, "1.0", load(sales, tmp)["payload"]); check("rowVersion \"1.0\" -> saved as version 2", r.status_code == 200 and r.json()["case"]["rowVersion"] == 2, (r.status_code, r.content[:100]))
        r = put(sales, tmp, True, load(sales, tmp)["payload"]); check("rowVersion true == 1 -> stale now (409), not a 400", r.status_code == 409 and code(r) == "version_conflict")
        e = copy.deepcopy(base_payload); e["remark"] = "edited"; e["originalPremium"] = 2000
        r = put(sales, uid, 1, e); j = r.json()
        check("edit draft -> 200, rowVersion 2, status draft", r.status_code == 200 and j["case"]["rowVersion"] == 2 and j["case"]["status"] == "draft", (r.status_code, j))
        row = Case.objects.get(case_uid=uid)
        check("payload saved + updated_by", row.payload["remark"] == "edited" and row.updated_by == f"personnel:{sales_p.pk}" and row.row_version == 2)
        check("snapshot draft_updated v2 + audit update_draft with before/after",
              EntitySnapshot.objects.filter(entity_type="case", entity_id=uid, entity_version=2, snapshot_reason="draft_updated").count() == 1
              and audit(uid, "update_draft").count() == 1 and audit(uid, "update_draft")[0].before_data["payload"]["remark"] == ""
              and audit(uid, "update_draft")[0].after_data["payload"]["remark"] == "edited" and audit(uid, "update_draft")[0].after_data["rowVersion"] == 2)
        r = put(sales, uid, 1, e); check("stale rowVersion -> 409 version_conflict with currentRowVersion", r.status_code == 409 and code(r) == "version_conflict" and r.json()["currentRowVersion"] == 2)
        check("conflict wrote nothing", Case.objects.get(case_uid=uid).row_version == 2 and audit(uid).count() == 2)
        e2 = copy.deepcopy(e); e2["currency"] = "XX9"; r = put(sales, uid, 2, e2); check("PUT invalid content -> 400 validation_failed, nothing changed", code(r) == "validation_failed" and Case.objects.get(case_uid=uid).row_version == 2)

        # #8 claims / transactions / paymentEntries 不能被一般編輯覆蓋
        Case.objects.filter(case_uid=uid).update(payload={**Case.objects.get(case_uid=uid).payload, "claims": [{"id": "C1", "amount": 10}],
            "transactions": [{"legType": "Leg 1", "amount": 1}], "paymentEntries": [{"scheduleKey": "cedant", "amount": 3}]})
        cur = load(sales, uid); e3 = copy.deepcopy(cur["payload"]); e3["claims"] = []; e3["transactions"] = [{"forged": True}]; e3["paymentEntries"] = [{"forged": True}]
        r = put(sales, uid, cur["rowVersion"], e3); st = Case.objects.get(case_uid=uid).payload
        check("#8 claims / transactions / paymentEntries pinned to stored values", r.status_code == 200 and st["claims"] == [{"id": "C1", "amount": 10}]
              and st["transactions"] == [{"legType": "Leg 1", "amount": 1}] and st["paymentEntries"] == [{"scheduleKey": "cedant", "amount": 3}], st["claims"])
        cur = load(sales, uid); e4 = copy.deepcopy(cur["payload"]); e4.pop("claims"); e4.pop("transactions"); e4.pop("paymentEntries")
        r = put(sales, uid, cur["rowVersion"], e4); st = Case.objects.get(case_uid=uid).payload
        check("#8 omitting them does not erase them either", r.status_code == 200 and len(st["claims"]) == 1 and len(st["transactions"]) == 1 and len(st["paymentEntries"]) == 1)

        # 已 Announce（posted）：付款條件鎖定
        Case.objects.filter(case_uid=uid).update(status="posted", tw_ref="ZZ-TEST-2")
        cur = load(sales, uid); pt = copy.deepcopy(cur["payload"]); pt["paymentTermsDays"] = 45
        r = put(sales, uid, cur["rowVersion"], pt); check("posted: changing payment terms -> 409 payment_terms_locked", r.status_code == 409 and code(r) == "payment_terms_locked")
        pt = copy.deepcopy(cur["payload"]); pt["reinsurers"][0]["paymentTermsDays"] = 60
        check("posted: changing a reinsurer's payment terms -> locked", code(put(sales, uid, cur["rowVersion"], pt)) == "payment_terms_locked")
        pt = copy.deepcopy(cur["payload"]); pt["installmentEnabled"] = True
        check("posted: turning installments on -> locked", code(put(sales, uid, cur["rowVersion"], pt)) == "payment_terms_locked")
        pt = copy.deepcopy(cur["payload"]); pt["remark"] = "posted edit"
        r = put(sales, uid, cur["rowVersion"], pt)
        check("posted: other edits allowed, status stays posted, reason case_updated / action update_case",
              r.status_code == 200 and r.json()["case"]["status"] == "posted" and audit(uid, "update_case").count() == 1
              and EntitySnapshot.objects.filter(entity_type="case", entity_id=uid, snapshot_reason="case_updated").count() == 1)
        # 鍵順序不同不算變動（資料庫會重排 JSON 鍵）
        Case.objects.filter(case_uid=uid).update(payload={**Case.objects.get(case_uid=uid).payload,
            "performanceInstallments": [{"id": "I1", "paymentBaseDate": "2026-02-01", "paymentTermsDays": 30, "reinsurerPaymentTerms": {"r10": 30, "r2": 45}}]})
        cur = load(sales, uid); pt = copy.deepcopy(cur["payload"])
        pt["performanceInstallments"][0]["reinsurerPaymentTerms"] = {"r2": 45, "r10": 30}
        check("posted: same payment terms in a different key order are NOT a change", put(sales, uid, cur["rowVersion"], pt).status_code == 200)

        # #7 Reversed 存檔要明確確認
        Case.objects.filter(case_uid=uid).update(status="reversed")
        cur = load(sales, uid); rv = copy.deepcopy(cur["payload"]); rv["remark"] = "fix"
        r = put(sales, uid, cur["rowVersion"], rv); check("#7 reversed: save without confirmation -> 409 reverse_correction_confirmation_required", r.status_code == 409 and code(r) == "reverse_correction_confirmation_required")
        r = put(sales, uid, cur["rowVersion"], rv, reverseCorrectionConfirmed="true"); check("#7 reversed: only boolean true confirms", code(r) == "reverse_correction_confirmation_required")
        check("#7 nothing changed while unconfirmed", Case.objects.get(case_uid=uid).status == "reversed")
        r = put(sales, uid, cur["rowVersion"], rv, reverseCorrectionConfirmed=True)
        st = Case.objects.get(case_uid=uid)
        check("#7 reversed + confirmed -> back to posted, payload.status posted", r.status_code == 200 and r.json()["case"]["status"] == "posted" and st.status == "posted" and st.payload["status"] == "posted")
        Case.objects.filter(case_uid=uid).update(status="closed"); cur = load(sales, uid)
        r = put(sales, uid, cur["rowVersion"], cur["payload"]); check("closed case not editable -> 409 case_not_editable", r.status_code == 409 and code(r) == "case_not_editable")
        Case.objects.filter(case_uid=uid).update(status="posted")

        # 負責人移轉
        cur = load(sales, uid); tr = copy.deepcopy(cur["payload"]); tr["ownerPersonnelId"] = other_p.pk
        r = put(admin, uid, cur["rowVersion"], tr); check("admin may transfer the owner", r.status_code == 200 and Case.objects.get(case_uid=uid).owner_personnel_id == other_p.pk, r.content[:150])
        cur = load(sales, uid); tr = copy.deepcopy(cur["payload"]); tr["ownerPersonnelId"] = sales_p.pk
        r = put(sales, uid, cur["rowVersion"], tr); check("non-owner, non-admin cannot transfer -> 403 owner_transfer_denied", r.status_code == 403 and code(r) == "owner_transfer_denied")
        r = put(sales, uid, cur["rowVersion"], cur["payload"]); check("non-owner may still edit without changing the owner", r.status_code == 200)
        other = account(other_p, "other"); cur = load(other, uid); tr = copy.deepcopy(cur["payload"]); tr["ownerPersonnelId"] = sales_p.pk
        r = put(other, uid, cur["rowVersion"], tr); check("current owner may hand the case over", r.status_code == 200 and Case.objects.get(case_uid=uid).owner_personnel_id == sales_p.pk)
        # 歷史人員可以保留：離職的負責人／拆分人員不會擋住編輯，但不能新選
        Personnel.objects.filter(pk=sales_p.pk).update(is_active=True)
        Case.objects.filter(case_uid=uid).update(owner_personnel=gone, payload={**Case.objects.get(case_uid=uid).payload, "ownerPersonnelId": gone.pk, "ownerPersonnelName": gone.name})
        cur = load(admin, uid); ok = copy.deepcopy(cur["payload"]); ok["remark"] = "keep inactive owner"
        check("inactive historical owner kept on edit", put(admin, uid, cur["rowVersion"], ok).status_code == 200)
        cur = load(admin, uid); nw = copy.deepcopy(cur["payload"]); nw["ownerPersonnelId"] = ns.pk; other_gone = person("sales", is_active=False, deactivated_by="t", deactivated_at="2026-01-01T00:00:00Z"); nw["ownerPersonnelId"] = other_gone.pk
        check("selecting a different inactive owner is refused", code(put(admin, uid, cur["rowVersion"], nw)) == "invalid_case_owner")
        Case.objects.filter(case_uid=uid).update(payload={**Case.objects.get(case_uid=uid).payload, "splitEnabled": True,
            "splitParties": [{"personnelId": ns.pk, "name": ns.name, "pct": 50}, {"personnelId": p1.pk, "name": p1.name, "pct": 50}]})
        cur = load(admin, uid); ok = copy.deepcopy(cur["payload"]); ok["remark"] = "keep non-eligible split"
        check("non-eligible historical split person kept on edit", put(admin, uid, cur["rowVersion"], ok).status_code == 200)
        cur = load(admin, uid); nw = copy.deepcopy(cur["payload"]); nw["splitParties"][1] = {"personnelId": ns.pk + 0, "name": "", "pct": 50}; nw["splitParties"][0] = {"personnelId": p2.pk, "name": "", "pct": 50}
        nw["splitParties"][1] = {"personnelId": other_gone.pk, "name": "", "pct": 50}
        check("adding a NEW inactive split person is refused", code(put(admin, uid, cur["rowVersion"], nw)) == "invalid_personnel_split")

        # 版本一路遞增、每次都有稽核
        final = Case.objects.get(case_uid=uid)
        check("every successful save bumped rowVersion once and left one snapshot + one audit each",
              EntitySnapshot.objects.filter(entity_type="case", entity_id=uid).count() == final.row_version
              and audit(uid).count() == final.row_version, (final.row_version, audit(uid).count()))
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Insured").count(), "| ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count())
