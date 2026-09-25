import copy
import json
import uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case, CaseDocument, ReferenceSequence
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=kw.pop("name", f"ZZ WF {role} {_seq[0]}"), department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.wf.{tag}", password="Flow-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Flow-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Cedant", originalInsured="ZZ Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
def create(c, **over):
    r = call(c, "post", "/api/cases", {"case": ready(**over)}); assert r.status_code == 201, r.content
    return Case.objects.get(case_uid=r.json()["case"]["caseUid"])
def doc(case, kind, reinsurers=(), selected=True):
    return CaseDocument.objects.create(case=case, kind=kind, reinsurers=list(reinsurers), filename=f"{kind}.pdf", content_type="application/pdf", byte_size=5,
                                       sha256="0" * 64, storage_key=f"zz-{uuid.uuid4()}", is_selected=selected, uploaded_by="t")
def full_docs(case):
    return [doc(case, "offer"), doc(case, "signed", ["ZZ Re A"]), doc(case, "confirmation", ["zz  re b"])]
def announce(c, case, docs=None, **over):
    body = {"caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version, "confirmed": True,
            "documentIds": [str(d.pk) for d in (docs if docs is not None else CaseDocument.objects.filter(case=case, is_selected=True))]}
    body.update(over); return call(c, "post", "/api/case-announce", body)
def wf(c, action, case, **extra):
    body = {"action": action, "caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version, **extra}
    return call(c, "post", "/api/case-workflow", body)
def audit(uid, action=None):
    q = AuditLog.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(action=action) if action else q
def snaps(uid, reason=None):
    q = EntitySnapshot.objects.filter(entity_type="case", entity_id=str(uid)); return q.filter(snapshot_reason=reason) if reason else q

try:
    with transaction.atomic():
        sales_p, gm_p, view_p = person("sales", "reinsurance"), person("general_manager", "reinsurance"), person("viewer", "business_1")
        fin_p = person("accounting", "finance", name="ZZ WF Fin B"); fin2 = person("accounting_manager", "finance", name="ZZ WF Fin A")
        fin_off = person("accounting", "finance", is_active=False, deactivated_by="t", deactivated_at="2026-01-01T00:00:00Z"); biz = person("sales", "business_1")
        sales, gm, viewer = account(sales_p, "sales"), account(gm_p, "gm"), account(view_p, "view")
        adm_p = person("admin", "admin"); admin = account(adm_p, "admin")

        # ================= Announce =================
        c1 = create(sales)
        check("announce: GM / viewer have no cases.announce -> 403", call(gm, "post", "/api/case-announce", {}).status_code == 403 and call(viewer, "post", "/api/case-announce", {}).status_code == 403)
        check("announce: anonymous -> 401, GET is not allowed (403/405)", call(new_client(), "post", "/api/case-announce", {}).status_code == 401 and call(sales, "get", "/api/case-announce").status_code in (403, 405))
        r = call(sales, "post", "/api/case-announce", {"rowVersion": 1, "confirmed": True}); check("no caseUid -> 400 case_uid_required", code(r) == "case_uid_required")
        for bad in (None, 0, "x", 1.5): check(f"rowVersion {bad!r} -> 400 row_version_required", code(call(sales, "post", "/api/case-announce", {"caseUid": str(c1.case_uid), "rowVersion": bad, "confirmed": True})) == "row_version_required")
        r = call(sales, "post", "/api/case-announce", {"caseUid": str(c1.case_uid), "rowVersion": 1}); check("confirmed missing -> 400 confirmation_required", code(r) == "confirmation_required")
        r = call(sales, "post", "/api/case-announce", {"caseUid": str(c1.case_uid), "rowVersion": 1, "confirmed": "true"}); check("confirmed must be boolean true", code(r) == "confirmation_required")
        r = call(sales, "post", "/api/case-announce", {"caseUid": str(uuid.uuid4()), "rowVersion": 1, "confirmed": True}); check("unknown case -> 404", r.status_code == 404 and code(r) == "case_not_found")
        r = announce(sales, c1, docs=[], rowVersion=7); check("stale version -> 409 version_conflict + currentRowVersion", r.status_code == 409 and code(r) == "version_conflict" and r.json()["currentRowVersion"] == 1)
        Case.objects.filter(pk=c1.pk).update(owner_personnel=None)
        check("no owner -> 400 case_owner_required", code(announce(sales, c1, docs=[])) == "case_owner_required")
        Case.objects.filter(pk=c1.pk).update(owner_personnel=sales_p)
        inc = create(sales, ae="", interest="", deductibles=""); r = announce(sales, inc, docs=[])
        check("incomplete case -> 400 case_not_ready with issues (plural message)", r.status_code == 400 and code(r) == "case_not_ready" and len(r.json()["issues"]) == 3 and r.json()["message"] == "Complete 3 required fields before Announce." and {i["field"] for i in r.json()["issues"]} == {"ae", "interest", "deductibles"}, r.content[:200])
        one = create(sales, ae=""); check("one missing field -> singular message", announce(sales, one, docs=[]).json()["message"] == "Complete 1 required field before Announce.")

        r = announce(sales, c1, docs=[]); check("no documents -> 400 documents_not_ready, coverage lists everything missing", r.status_code == 400 and code(r) == "documents_not_ready" and r.json()["coverage"]["offer"] is False and r.json()["coverage"]["missing"] == ["zz re a", "zz re b"], r.content[:250])
        dup = create(sales, reinsurers=[dict(name="ZZ Re A", sharePct=50, premium=1, riCommPct=0, taxPct=0), dict(name="zz re a (Facility)", sharePct=50, premium=1, riCommPct=0, taxPct=0)])
        check("the same reinsurer listed twice (case / Facility tag differ) counts once", announce(sales, dup, docs=[]).json()["coverage"]["required"] == ["zz re a"])
        d_offer = doc(c1, "offer"); d_sa = doc(c1, "signed", ["ZZ Re A"])
        r = announce(sales, c1); check("offer + signed for A only -> not ready, missing B", code(r) == "documents_not_ready" and r.json()["coverage"]["missing"] == ["zz re b"] and r.json()["coverage"]["offer"] is True)
        d_unsel = doc(c1, "confirmation", ["ZZ Re B"], selected=False)
        check("an unselected document does not count", code(announce(sales, c1)) == "documents_not_ready")
        CaseDocument.objects.filter(pk=d_unsel.pk).update(is_selected=True); d_unsel.refresh_from_db()
        check("...selected, matches 'ZZ Re B (Facility)' (Facility tag, case and spacing ignored)", announce(sales, c1, docs=[d_offer, d_sa, d_unsel], documentIds=["x"]).status_code == 409)
        r = announce(sales, c1, documentIds=[str(d_offer.pk), str(d_sa.pk)]); check("document list differs from the reviewed one -> 409 document_review_outdated (+coverage)", r.status_code == 409 and code(r) == "document_review_outdated" and "coverage" in r.json())
        r = announce(sales, c1, documentIds="nope"); check("documentIds not an array -> outdated", code(r) == "document_review_outdated")
        Case.objects.filter(pk=c1.pk).update(payload={**Case.objects.get(pk=c1.pk).payload, "policyFrom": "2026-3-1"})
        check("effective date in a bad format -> 400 effective_date_required", code(announce(sales, c1)) == "effective_date_required")
        Case.objects.filter(pk=c1.pk).update(payload={**Case.objects.get(pk=c1.pk).payload, "policyFrom": "2026-03-01"})
        seq_before = ReferenceSequence.objects.filter(prefix="TWPAR2603").count()
        r = announce(sales, c1); j = r.json(); c1.refresh_from_db()
        check("announce -> 200, TW reference TW<class><yy><mm>001, status posted, version 2", r.status_code == 200 and j["case"]["twRef"] == "TWPAR2603001" and c1.tw_ref == "TWPAR2603001" and c1.status == "posted" and c1.row_version == 2 and j["case"]["rowVersion"] == 2, (r.status_code, j))
        check("announced_by / announced_at recorded", c1.announced_by == f"personnel:{sales_p.pk}" and c1.announced_at is not None and j["case"]["announcedAt"])
        s = snaps(c1.case_uid, "announced").first(); a = audit(c1.case_uid, "announce").first()
        check("snapshot 'announced' v2 with the document review", s and s.entity_version == 2 and s.snapshot_data["documentReview"] == {"confirmed": True, "documentIds": sorted(str(d.pk) for d in (d_offer, d_sa, d_unsel)), "confirmedBy": f"personnel:{sales_p.pk}"} and s.snapshot_data["twRef"] == "TWPAR2603001")
        check("audit 'announce': before draft / after posted, metadata documentIds", a and a.before_data["status"] == "draft" and a.before_data["twRef"] is None and a.after_data["status"] == "posted" and a.metadata["milestone"] == "review-announce" and len(a.metadata["documentIds"]) == 3 and a.actor_role == "sales")
        r = announce(sales, c1); check("announce a second time -> 409 only_draft_can_announce", code(r) == "only_draft_can_announce")
        c2 = create(sales); full_docs(c2); r = announce(sales, c2)
        check("next case, same class and month -> ...002", r.json()["case"]["twRef"] == "TWPAR2603002", r.content[:100])
        c3 = create(sales, policyFrom="2026-04-01", policyTo="2027-04-01", classCode="p-a.r"); full_docs(c3)
        check("other month starts at 001; class code is upper-cased and stripped of symbols", announce(sales, c3).json()["case"]["twRef"] == "TWPAR2604001")
        c4 = create(sales, classCode="  ", policyFrom="2026-04-02"); full_docs(c4)
        check("no class code -> XX", announce(admin, c4).json()["case"]["twRef"] == "TWXX2604001")
        c5 = create(sales, classCode="abcdefghijklmnop", policyFrom="2027-11-01", policyTo="2028-11-01"); full_docs(c5)
        check("class code limited to 12 characters", announce(sales, c5).json()["case"]["twRef"] == "TWABCDEFGHIJKL2711001")
        check("sequence rows hold the last number", ReferenceSequence.objects.get(prefix="TWPAR2603").last_value == 2 and ReferenceSequence.objects.get(prefix="TWPAR2604").last_value == 1)
        ReferenceSequence.objects.filter(prefix="TWPAR2604").update(last_value=999)
        c6 = create(sales, policyFrom="2026-04-09"); full_docs(c6)
        check("after 999 the number just gets longer (no truncation, no duplicate)", announce(sales, c6).json()["case"]["twRef"] == "TWPAR26041000")
        c7 = create(sales, policyFrom="2026-04-10"); full_docs(c7)
        check("...and 1001 follows", announce(sales, c7).json()["case"]["twRef"] == "TWPAR26041001")
        failed = create(sales, policyFrom="2026-05-01", ae=""); full_docs(failed); announce(sales, failed)
        check("a failed announce does not consume a number", not ReferenceSequence.objects.filter(prefix="TWPAR2605").exists())

        # ================= Workflow: 狀態 =================
        r = call(sales, "get", "/api/case-workflow"); check("GET without caseUid -> 400", code(r) == "case_uid_required")
        check("GET unknown case -> 404; viewer 403; GM allowed", code(call(sales, "get", f"/api/case-workflow?caseUid={uuid.uuid4()}")) == "case_not_found" and call(viewer, "get", f"/api/case-workflow?caseUid={c1.case_uid}").status_code == 403 and call(gm, "get", f"/api/case-workflow?caseUid={c1.case_uid}").status_code == 200)
        w = call(sales, "get", f"/api/case-workflow?caseUid={c1.case_uid}").json()["workflow"]
        check("state of an announced root: chain=[root], latest=root, actions", [x["caseUid"] for x in w["chain"]] == [str(c1.case_uid)] and w["latestCaseUid"] == str(c1.case_uid) and w["root"]["twRef"] == "TWPAR2603001"
              and w["actions"] == {"canCreateEndorsement": True, "canRenew": False, "canEditAnnounced": True, "canReverse": False, "canNotifyAccounting": True}, w["actions"])
        check("state: chain fields", w["chain"][0]["originalInsured"] == "ZZ Insured" and w["chain"][0]["policyFromTime"] == "12:00" and w["chain"][0]["endoTypes"] == [] and w["chain"][0]["parentCaseId"] is None)
        names = [p["name"] for p in w["accountingStaff"]]
        check("state: active Finance people only, sorted by name", "ZZ WF Fin A" in names and "ZZ WF Fin B" in names and names.index("ZZ WF Fin A") < names.index("ZZ WF Fin B") and fin_off.name not in names and biz.name not in names and sales_p.name not in names, names)
        d = call(sales, "get", f"/api/case-workflow?caseUid={inc.case_uid}").json()["workflow"]["actions"]; check("draft: no workflow actions", not any(d.values()))
        Case.objects.filter(pk=c2.pk).update(status="closed"); d = call(sales, "get", f"/api/case-workflow?caseUid={c2.case_uid}").json()["workflow"]["actions"]
        check("closed: endorse, renew, reverse; not notify / edit", d == {"canCreateEndorsement": True, "canRenew": True, "canEditAnnounced": False, "canReverse": True, "canNotifyAccounting": False}, d)
        Case.objects.filter(pk=c2.pk).update(status="posted")
        r = call(sales, "post", "/api/case-workflow", {"action": "reverse_case"}); check("POST without caseUid -> 400", code(r) == "case_uid_required")
        r = call(sales, "post", "/api/case-workflow", {"action": "reverse_case", "caseUid": str(uuid.uuid4())}); check("POST unknown case -> 404", r.status_code == 404)
        r = call(sales, "post", "/api/case-workflow", {"action": "fly", "caseUid": str(c1.case_uid)}); check("unknown action -> 400 unsupported_action", code(r) == "unsupported_action")
        check("GM cannot run workflow actions (no cases.write) -> 403", call(gm, "post", "/api/case-workflow", {"action": "reverse_case", "caseUid": str(c1.case_uid)}).status_code == 403)

        # ================= Endorsement =================
        root = c1
        Case.objects.filter(pk=root.pk).update(payload={**Case.objects.get(pk=root.pk).payload, "claims": [{"id": "C1"}], "transactions": [{"legType": "Leg 1"}], "paymentEntries": [{"scheduleKey": "cedant"}],
                                                       "statementNo": "S-1", "endorsements": [1], "accountingNotifications": [{"id": "old"}], "reversalCycle": 3})
        root.refresh_from_db()
        r = wf(sales, "create_endorsement", root, rowVersion="abc"); check("endorse: invalid rowVersion -> 409 version_conflict (Alpha: not 400)", r.status_code == 409 and code(r) == "version_conflict")
        r = wf(sales, "create_endorsement", root, rowVersion=99); check("endorse: stale rowVersion -> 409 + currentRowVersion", r.status_code == 409 and r.json()["currentRowVersion"] == root.row_version)
        r = wf(sales, "create_endorsement", inc); check("endorse from a draft -> 409 endorsement_source_status", code(r) == "endorsement_source_status")
        r = wf(sales, "create_endorsement", root); j = r.json(); e1 = Case.objects.get(case_uid=j["case"]["caseUid"]) if r.status_code == 201 else None
        check("endorse -> 201, new Draft endorsement under the root", r.status_code == 201 and e1.case_kind == "endorsement" and e1.parent_case_id == root.pk and e1.status == "draft" and e1.tw_ref is None and e1.row_version == 1 and e1.owner_personnel_id == root.owner_personnel_id, (r.status_code, r.content[:200]))
        p = e1.payload
        check("endorsement payload: ledger/claims/notifications reset, financial fields cleared, sequence 1, parent ref",
              p["claims"] == [] and p["transactions"] == [] and p["paymentEntries"] == [] and p["statementNo"] == "" and p["endorsements"] == [] and p["accountingNotifications"] == [] and p["reversalCycle"] == 0
              and p["status"] == "draft" and p["parentTwRef"] == "TWPAR2603001" and p["endorsementSeq"] == 1 and p["originalPremium"] is None and p["exchRate"] is None and p["endoEffectiveDate"] == "" and p["endoTypes"] == [] and p["pendingReversalOffset"] is None,
              {k: p.get(k) for k in ("claims", "status", "parentTwRef", "originalPremium")})
        check("endorsement reinsurers: premium cleared, other fields kept", [(x["name"], x["premium"], x["sharePct"], x["settlementRef"]) for x in p["reinsurers"]] == [("ZZ Re A", None, 60, ""), ("ZZ Re B (Facility)", None, 40, "")])
        check("the source case is untouched", Case.objects.get(pk=root.pk).row_version == root.row_version and Case.objects.get(pk=root.pk).payload["claims"] == [{"id": "C1"}])
        check("endorsement: snapshot v1 endorsement_created + audit create_endorsement",
              snaps(e1.case_uid, "endorsement_created").count() == 1 and snaps(e1.case_uid).first().entity_version == 1 and audit(e1.case_uid, "create_endorsement").first().before_data == {"sourceCaseUid": str(root.case_uid), "sourceRowVersion": root.row_version}
              and audit(e1.case_uid, "create_endorsement").first().metadata == {"endorsementSequence": 1})
        check("response has the case view + payload", j["case"]["caseKind"] == "endorsement" and j["case"]["parentCaseId"] == root.pk and j["case"]["payload"]["endorsementSeq"] == 1 and j["case"]["rowVersion"] == 1)
        r = wf(sales, "create_endorsement", root); check("a second endorsement from the root -> 409 latest_endorsement_required + latestCaseUid", r.status_code == 409 and code(r) == "latest_endorsement_required" and r.json()["latestCaseUid"] == str(e1.case_uid), r.content[:200])
        r = wf(sales, "create_endorsement", e1); check("endorse from the Draft endorsement itself -> endorsement_source_status", code(r) == "endorsement_source_status")
        w = call(sales, "get", f"/api/case-workflow?caseUid={e1.case_uid}").json()["workflow"]
        check("state seen from the child: same chain [root, child], latest = child, root reported", [x["caseUid"] for x in w["chain"]] == [str(root.case_uid), str(e1.case_uid)] and w["latestCaseUid"] == str(e1.case_uid) and w["root"]["caseUid"] == str(root.case_uid))
        check("state from the root now says it cannot create an endorsement", call(sales, "get", f"/api/case-workflow?caseUid={root.case_uid}").json()["workflow"]["actions"]["canCreateEndorsement"] is False)
        Case.objects.filter(pk=e1.pk).update(status="posted", tw_ref="TWPAR2603001-E00"); e1.refresh_from_db()
        r = wf(sales, "create_endorsement", e1); e2 = Case.objects.get(case_uid=r.json()["case"]["caseUid"]) if r.status_code == 201 else None
        check("an announced endorsement can be endorsed again: sequence 2, parent is still the root", r.status_code == 201 and e2.parent_case_id == root.pk and e2.payload["endorsementSeq"] == 2 and e2.payload["parentTwRef"] == "TWPAR2603001", r.content[:150])
        Case.objects.filter(pk=e2.pk).update(recycled_at="2026-01-01T00:00:00Z", recycled_by="t")
        check("a recycled endorsement leaves the chain: the previous one is latest again", call(sales, "get", f"/api/case-workflow?caseUid={e1.case_uid}").json()["workflow"]["actions"]["canCreateEndorsement"] is True)
        noref = create(sales); Case.objects.filter(pk=noref.pk).update(status="posted"); r = wf(sales, "create_endorsement", noref)
        check("root without TW Reference -> 409 root_reference_required", code(r) == "root_reference_required")

        # 批單的 Announce（TW Reference = 根案件編號 + -E + 2 位流水號）
        e3 = Case.objects.get(case_uid=wf(sales, "create_endorsement", e1).json()["case"]["caseUid"])
        e3.status = "draft"; Case.objects.filter(pk=e1.pk).update(status="posted")
        pl = e3.payload; pl.update(reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=10, riCommPct=5, taxPct=0), dict(name="ZZ Re B (Facility)", sharePct=40, premium=10, riCommPct=5, taxPct=0)], originalPremium=20, endoEffectiveDate="2026-06-01", endoTypes=["Premium"], endoText="Amend.")
        Case.objects.filter(pk=e3.pk).update(payload=pl); e3.refresh_from_db(); full_docs(e3)
        r = announce(sales, e3); e3.refresh_from_db()
        check("announce an endorsement -> <root ref>-E<nn>, audit action announce_endorsement", r.status_code == 200 and e3.tw_ref == "TWPAR2603001-E01" and audit(e3.case_uid, "announce_endorsement").count() == 1, (r.status_code, r.content[:200], e3.tw_ref))
        Case.objects.filter(pk=root.pk).update(tw_ref=None)
        e5 = create(sales); Case.objects.filter(pk=e5.pk).update(case_kind="endorsement", parent_case=root); full_docs(e5)
        e5.refresh_from_db(); pl = e5.payload; pl.update(parentTwRef="X", endoEffectiveDate="2026-06-01", endoTypes=["Premium"], endoText="A"); Case.objects.filter(pk=e5.pk).update(payload=pl)
        check("announce an endorsement whose root has no TW Reference -> 409 root_reference_required", code(announce(sales, e5)) == "root_reference_required")
        Case.objects.filter(pk=root.pk).update(tw_ref="TWPAR2603001")

        # ================= Renewal =================
        src = c2; Case.objects.filter(pk=src.pk).update(status="closed", payload={**Case.objects.get(pk=src.pk).payload, "policyFrom": "2028-02-29", "policyTo": "2029-02-28", "claims": [{"id": "C"}], "paymentEntries": [{"x": 1}], "statementNo": "S"}, effective_date="2028-02-29", expiration_date="2029-02-28")
        src.refresh_from_db()
        r = wf(sales, "create_renewal", src, rowVersion=1); check("renew: stale version -> 409", code(r) == "version_conflict" and r.json()["currentRowVersion"] == src.row_version)
        r = wf(sales, "create_renewal", c3); check("renew from a non-closed case -> 409 renewal_source_status", code(r) == "renewal_source_status")
        r = wf(sales, "create_renewal", src); j = r.json(); rn = Case.objects.get(case_uid=j["case"]["caseUid"]) if r.status_code == 201 else None
        check("renew -> 201: a new root Draft (no parent), kind renewal", r.status_code == 201 and rn.case_kind == "renewal" and rn.parent_case_id is None and rn.status == "draft" and rn.tw_ref is None and rn.owner_personnel_id == src.owner_personnel_id, (r.status_code, r.content[:200]))
        p = rn.payload
        check("renewal payload: dates moved a year (2/29 -> 2/28), 'Renew', reference to the source, ledger reset, premium kept",
              p["policyFrom"] == "2029-02-28" and p["policyTo"] == "2030-02-28" and p["newOrRenew"] == "Renew" and p["renewedFromTwRef"] == src.tw_ref and p["parentTwRef"] == "" and p["endorsementSeq"] is None
              and p["claims"] == [] and p["paymentEntries"] == [] and p["statementNo"] == "" and p["originalPremium"] == 1000 and p["reinsurers"][0]["premium"] == 600 and p["reinsurers"][0]["settlementRef"] == "", p["policyFrom"])
        check("renewal columns: effective / expiration dates from the shifted policy dates", str(rn.effective_date) == "2029-02-28" and str(rn.expiration_date) == "2030-02-28")
        check("renewal: snapshot renewal_created + audit create_renewal", snaps(rn.case_uid, "renewal_created").count() == 1 and audit(rn.case_uid, "create_renewal").first().metadata == {"workflow": "renewal"} and audit(rn.case_uid, "create_renewal").first().before_data["sourceTwRef"] == src.tw_ref)
        r = wf(sales, "create_renewal", src); check("a second renewal of the same case -> 409 renewal_already_exists", r.status_code == 409 and code(r) == "renewal_already_exists")
        Case.objects.filter(pk=rn.pk).update(recycled_at="2026-01-01T00:00:00Z", recycled_by="t")
        check("...unless the renewal Draft was recycled", wf(sales, "create_renewal", src).status_code == 201)

        # ================= Reverse =================
        rv = c3; Case.objects.filter(pk=rv.pk).update(status="closed", payload={**Case.objects.get(pk=rv.pk).payload, "reversalCycle": 1, "confirmedProductionKeys": ["k"], "productionPartiallyConfirmed": True,
            "transactions": [{"legType": "Leg 1"}, {"legType": "Leg 1", "isReversalEntry": True}, {"legType": "Leg 2", "reversed": False}]}); rv.refresh_from_db()
        r = wf(sales, "reverse_case", c4); check("reverse a non-closed case -> 409 reverse_status (checked before the version)", code(r) == "reverse_status")
        r = wf(sales, "reverse_case", rv, rowVersion=99); check("reverse: stale version -> 409", code(r) == "version_conflict" and r.json()["currentRowVersion"] == rv.row_version)
        r = wf(sales, "reverse_case", rv); j = r.json(); rv.refresh_from_db(); p = rv.payload
        check("reverse -> 200, status reversed, version+1, cycle 2", r.status_code == 200 and rv.status == "reversed" and j["reversalCycle"] == 2 and p["reversalCycle"] == 2 and j["case"]["status"] == "reversed", (r.status_code, j))
        check("reverse payload: transactions flagged reversed except reversal entries, offset pending, production confirmation cleared",
              p["transactions"] == [{"legType": "Leg 1", "reversed": True}, {"legType": "Leg 1", "isReversalEntry": True}, {"legType": "Leg 2", "reversed": True}] and p["pendingReversalOffset"] is True and p["confirmedProductionKeys"] == [] and p["productionPartiallyConfirmed"] is False, p["transactions"])
        check("reverse: audit reverse_case + snapshot case_reversed (VM addition)", audit(rv.case_uid, "reverse_case").first().metadata == {"reversalCycle": 2} and audit(rv.case_uid, "reverse_case").first().before_data["status"] == "closed"
              and snaps(rv.case_uid, "case_reversed").first().entity_version == rv.row_version and snaps(rv.case_uid, "case_reversed").first().snapshot_data["status"] == "reversed")
        bad = create(sales, classCode="BAD", policyFrom="2026-08-01"); Case.objects.filter(pk=bad.pk).update(status="closed", payload={**Case.objects.get(pk=bad.pk).payload, "transactions": [{"legType": "Leg 1"}, None]}); bad.refresh_from_db(); n_audit = AuditLog.objects.count()
        r = wf(sales, "reverse_case", bad); bad2 = Case.objects.get(pk=bad.pk)
        check("a null entry in transactions -> 409 transactions_corrupt (Alpha throws), nothing changed", r.status_code == 409 and code(r) == "transactions_corrupt" and bad2.status == "closed" and bad2.row_version == bad.row_version and bad2.payload == bad.payload and AuditLog.objects.count() == n_audit and not snaps(bad.case_uid, "case_reversed").exists())
        check("a second reverse -> 409 reverse_status", code(wf(sales, "reverse_case", rv)) == "reverse_status")
        check("reversed case: state actions", call(sales, "get", f"/api/case-workflow?caseUid={rv.case_uid}").json()["workflow"]["actions"] == {"canCreateEndorsement": False, "canRenew": False, "canEditAnnounced": True, "canReverse": False, "canNotifyAccounting": True})

        # ================= 通知會計 =================
        nt = c1
        Case.objects.filter(pk=nt.pk).update(payload={**Case.objects.get(pk=nt.pk).payload, "accountingNotifications": []}); nt.refresh_from_db()
        r = wf(sales, "notify_accounting", inc, accountingPersonnelId=fin_p.pk); check("notify a Draft -> 409 notification_status", code(r) == "notification_status")
        r = wf(sales, "notify_accounting", nt, accountingPersonnelId=fin_p.pk, rowVersion=99); check("notify: stale version -> 409", code(r) == "version_conflict")
        for label, pid in (("non-finance person", biz.pk), ("inactive finance person", fin_off.pk), ("unknown id", 99999999), ("not a number", "abc"), ("missing", None)):
            r = wf(sales, "notify_accounting", nt, accountingPersonnelId=pid); check(f"notify: {label} -> 400 accounting_staff_required", r.status_code == 400 and code(r) == "accounting_staff_required", (r.status_code, code(r)))
        v0 = Case.objects.get(pk=nt.pk).row_version
        r = wf(sales, "notify_accounting", nt, accountingPersonnelId=fin_p.pk, note="  please book this  "); j = r.json(); nt.refresh_from_db()
        n = j["notification"]
        check("notify -> 200, notification recorded, version+1", r.status_code == 200 and nt.row_version == v0 + 1 and j["rowVersion"] == v0 + 1 and n["accountingPersonnelId"] == fin_p.pk and n["accountingStaffName"] == fin_p.name
              and n["notifiedByName"] == sales_p.name and n["note"] == "please book this" and nt.payload["accountingNotifications"] == [n], (r.status_code, j))
        check("notification id is a UUID and notifiedAt is an ISO time with milliseconds and Z", uuid.UUID(n["id"]) and len(n["notifiedAt"]) == 24 and n["notifiedAt"].endswith("Z") and n["notifiedAt"][10] == "T", n["notifiedAt"])
        check("notify: audit notify_accounting + snapshot accounting_notified (VM addition)", audit(nt.case_uid, "notify_accounting").first().metadata == {"accountingPersonnelId": fin_p.pk, "notificationId": n["id"]}
              and audit(nt.case_uid, "notify_accounting").first().before_data == {"rowVersion": v0, "accountingNotifications": []} and snaps(nt.case_uid, "accounting_notified").first().entity_version == v0 + 1)
        r = wf(sales, "notify_accounting", nt, accountingPersonnelId=fin2.pk, note="x" * 3000); nt.refresh_from_db()
        check("a second notification is appended; note capped at 2000 characters", len(nt.payload["accountingNotifications"]) == 2 and len(nt.payload["accountingNotifications"][1]["note"]) == 2000)
        check("the notifications are returned by the workflow state", len(call(sales, "get", f"/api/case-workflow?caseUid={nt.case_uid}").json()["workflow"]["notifications"]) == 2)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Insured").count(), "| ZZ sequences =", ReferenceSequence.objects.filter(prefix__startswith="TW").count())
