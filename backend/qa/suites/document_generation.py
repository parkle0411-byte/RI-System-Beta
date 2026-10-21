import json
import uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog
from cases.models import Case
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept):
    _seq[0] += 1
    return Personnel.objects.create(name=f"ZZ DOC {role} {_seq[0]}", department=dept, role_code=role, created_by="t", updated_by="t")
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.doc.{tag}", password="Doc-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Doc-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None
def message(r):
    try: return r.json().get("message")
    except Exception: return None

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Doc Cedant", originalInsured="ZZ Doc Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             # 2026-10-16「92 項會計規則重新確認」：每家再保人付款天數須獨立填寫，不繼承 Case 預設（缺漏時 Debit Note 409）；
             # 一般 fixture 明確填 30 天，讓其他欄位的檢查維持原意。
             reinsurers=[dict(name="ZZ Re A", sharePct=100, premium=1000, riCommPct=5, taxPct=0, paymentTermsDays=30)],
             limitOfLiability=1000000, reinsuredRetention="Advice of Reinsured's retention waived.", deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make_case(c, status="posted"):
    r = call(c, "post", "/api/cases", {"case": ready()}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
    Case.objects.filter(pk=case.pk).update(payload={**case.payload, "aeEmail": "zz.case.email@example.invalid"})
    if status != "draft":
        _ref[0] += 1
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-DOC-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case

def pdf(c, **body): return call(c, "post", "/api/render-document-pdf", {"markup": "<p>Retired</p>", **body})
def docx(c, **body): return call(c, "post", "/api/document-generation-log", {"format": "docx", **body})
def gen_audit(uid): return AuditLog.objects.filter(entity_type="case", entity_id=str(uid), action="generate_document")

try:
    with transaction.atomic():
        adm_p, sales_p, gm_p = person("admin", "admin"), person("sales", "reinsurance"), person("general_manager", "reinsurance")
        fin_p, view_p = person("accounting", "finance"), person("viewer", "business_1")
        admin, sales, gm, fin, viewer = account(adm_p, "admin"), account(sales_p, "sales"), account(gm_p, "gm"), account(fin_p, "fin"), account(view_p, "view")
        draft, posted = make_case(sales, "draft"), make_case(sales, "posted")
        original_draft_payload = dict(draft.payload)
        recycled = make_case(sales, "draft"); Case.objects.filter(pk=recycled.pk).update(recycled_at=timezone.now())
        archived = make_case(sales, "posted"); Case.objects.filter(pk=archived.pk).update(is_archived=True, archived_at=timezone.now(), archived_by="t")

        # ================= 權限 =================
        check("anonymous PDF -> 401", call(new_client(), "post", "/api/render-document-pdf", {"markup": "<p>Retired</p>"}).status_code == 401)
        for label, c in (("finance staff", fin), ("viewer", viewer)):
            check(f"{label}: no documents.read -> PDF 403 and Word log 403",
                  pdf(c, kind="cover", caseUid=str(posted.case_uid)).status_code == 403 and docx(c, kind="cover", caseUid=str(posted.case_uid)).status_code == 403)
        check("GET is not allowed (403 before method dispatch)", call(sales, "get", "/api/render-document-pdf").status_code == 403)

        check("anonymous Word -> 401", docx(new_client(), kind="cover", caseUid=str(posted.case_uid)).status_code == 401)
        for kind in ("cover", "debit", "endorsement"):
            before = gen_audit(posted.case_uid).count()
            r = pdf(sales, kind=kind, caseUid=str(posted.case_uid))
            check(f"retired {kind} PDF -> 410, no audit, no PDF", r.status_code == 410 and code(r) == "pdf_generation_retired"
                  and not r.content.startswith(b"%PDF-") and gen_audit(posted.case_uid).count() == before)
        r = call(sales, "post", "/api/render-document-pdf", {"markup": "<script>invalid</script>", "kind": "cover"})
        check("retired endpoint cannot render supplied markup", r.status_code == 410 and code(r) == "pdf_generation_retired")

        # ================= kind／caseUid =================
        r = docx(sales, kind="invoice", caseUid=str(posted.case_uid)); check("unknown kind -> 400", r.status_code == 400 and code(r) == "invalid_document_kind")
        r = docx(sales, kind="debit"); check("debit without caseUid -> 400 with Alpha's message", r.status_code == 400 and message(r) == "caseUid is required to render a Debit Note.")
        r = docx(sales, kind="cover"); check("cover without caseUid -> 400 (VM: every Word names its case)", r.status_code == 400 and code(r) == "case_uid_required")
        r = docx(sales, kind="cover", caseUid=str(uuid.uuid4())); check("unknown case -> 404", r.status_code == 404 and code(r) == "case_not_found")
        r = docx(sales, kind="cover", caseUid=str(posted.case_uid).upper()); check("upper-case UUID does not match (Alpha compares text) -> 404", r.status_code == 404)
        r = docx(sales, kind="cover", caseUid="not-a-uuid"); check("malformed caseUid -> 404", r.status_code == 404)
        r = docx(sales, kind="debit", caseUid=str(draft.case_uid))
        check("Debit Note Word for a Draft (no TW Ref) -> 409 with Alpha's message", r.status_code == 409 and message(r) == "Debit Note is only available after Announce assigns a TW Reference.", r.content[:200])
        r = docx(sales, kind="cover", caseUid=str(draft.case_uid))
        check("Cover Note Word without a TW Ref -> 409", r.status_code == 409 and code(r) == "cover_requires_tw_ref")
        r = docx(sales, kind="debit", caseUid=str(archived.case_uid)); check("Debit Note for an archived case (has TW Ref) -> 409 (Alpha: is_archived = false)", r.status_code == 409)
        r = docx(sales, kind="cover", caseUid=str(archived.case_uid)); check("cover for an archived case -> 404", r.status_code == 404)
        r = docx(sales, kind="cover", caseUid=str(recycled.case_uid)); check("cover for a recycled draft -> 404", r.status_code == 404)
        # Word validates stored Case fields, including whitespace.
        original_payload = dict(posted.payload)
        for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　")):
            payload = dict(original_payload)
            if label == "missing":
                payload.pop("reinsured", None)
            else:
                payload["reinsured"] = value
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            for kind in ("cover", "debit"):
                for fmt, generate in (("docx", docx),):
                    r = generate(sales, kind=kind, caseUid=str(posted.case_uid))
                    check(f"{kind} {fmt}: {label} Reinsured -> 409", r.status_code == 409 and code(r) == "reinsured_required"
                          and message(r) == "Complete Reinsured in the case before generating a Cover Note or Debit Note.")
        for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff"), ("Chinese name only", "")):
            payload = dict(original_payload)
            if label == "missing":
                payload.pop("originalInsured", None)
            else:
                payload["originalInsured"] = value
            if label == "Chinese name only":
                payload["originalInsuredCn"] = "測試被保險人"
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            for kind in ("cover", "debit"):
                for fmt, generate in (("docx", docx),):
                    r = generate(sales, kind=kind, caseUid=str(posted.case_uid))
                    check(f"{kind} {fmt}: {label} Original Insured -> 409", r.status_code == 409 and code(r) == "original_insured_required"
                          and message(r) == "Complete Original Insured in the case before generating a Cover Note or Debit Note.")
        for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff"), ("components only", "")):
            payload = dict(original_payload)
            if label == "missing":
                payload.pop("type", None)
            else:
                payload["type"] = value
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            for kind in ("cover", "debit"):
                for fmt, generate in (("docx", docx),):
                    r = generate(sales, kind=kind, caseUid=str(posted.case_uid))
                    check(f"{kind} {fmt}: {label} Type -> 409", r.status_code == 409 and code(r) == "type_required"
                          and message(r) == "Complete Type in the case before generating a Cover Note or Debit Note.")
        for field in ("policyFrom", "policyTo"):
            for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
                payload = dict(original_payload)
                if label == "missing":
                    payload.pop(field, None)
                else:
                    payload[field] = value
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                for kind in ("cover", "debit"):
                    r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                    check(f"{kind}: {label} {field} -> 409", r.status_code == 409 and code(r) == "policy_period_required"
                          and message(r) == "Complete the policy start and end dates in the case before generating a Cover Note or Debit Note.")
            # Supplied dates cannot override missing dates in the stored Case.
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, field: ""})
            for kind in ("cover", "debit"):
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid), policyFrom="2026-01-01", policyTo="2027-01-01")
                check(f"{kind}: request dates cannot replace missing Case {field}", r.status_code == 409 and code(r) == "policy_period_required")
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "policyFrom": "", "policyTo": ""})
        for kind in ("cover", "debit"):
            r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
            check(f"{kind}: both policy dates missing -> 409", r.status_code == 409 and code(r) == "policy_period_required")
        for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
            payload = dict(original_payload)
            if label == "missing":
                payload.pop("ae", None)
            else:
                payload["ae"] = value
            # A stale alias or request field cannot replace the selected Case AE.
            payload["aeName"] = "Legacy AE Name"
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            for kind in ("cover", "debit", "endorsement"):
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid), ae="Request AE", aeName="Request Alias")
                check(f"{kind}: {label} Case AE -> 409 without audit", r.status_code == 409 and code(r) == "ae_required"
                      and message(r) == "Select an AE in the case before generating a document." and gen_audit(posted.case_uid).count() == before)
        for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
            payload = dict(original_payload)
            if label == "missing":
                payload.pop("aeEmail", None)
            else:
                payload["aeEmail"] = value
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            for kind in ("cover", "debit", "endorsement"):
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid), aeEmail="request@example.invalid")
                check(f"{kind}: {label} AE Email without personnel fallback -> 409, no audit", r.status_code == 409
                      and code(r) == "ae_email_required" and message(r) == "Complete the AE Email in the case or Personnel before generating a document."
                      and gen_audit(posted.case_uid).count() == before)
        for structure in ("QS", "XOL"):
            for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("interest", None)
                else:
                    payload["interest"] = value
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), interest="Request-supplied Interest")
                check(f"Cover {structure}: {label} Case Interest -> 409, no audit", r.status_code == 409
                      and code(r) == "interest_required" and message(r) == "Complete Interest in the case before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
        for structure in ("QS", "XOL"):
            for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("limitOfLiability", None)
                else:
                    payload["limitOfLiability"] = value
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), limitOfLiability=1000)
                check(f"Cover {structure}: {label} stored Limit of Liability -> 409, no audit", r.status_code == 409
                      and code(r) == "limit_of_liability_required" and message(r) == "Complete Limit of Liability in the case before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
        for structure in ("XOL",):
            for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
                payload = {**original_payload, "reinsuranceStructure": structure}
                if label == "missing":
                    payload.pop("underlyingLimits", None)
                else:
                    payload["underlyingLimits"] = value
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), underlyingLimits="Request layer terms")
                check(f"Cover {structure}: {label} stored Underlying Limits -> 409, no audit", r.status_code == 409
                      and code(r) == "underlying_limits_required" and message(r) == "Complete Underlying Limits in the case before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
        for structure in ("QS", "XOL"):
            for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("deductibles", None)
                else:
                    payload["deductibles"] = value
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), deductibles="Request-supplied Deductibles")
                check(f"Cover {structure}: {label} stored Deductibles -> 409, no audit", r.status_code == 409
                      and code(r) == "deductibles_required" and message(r) == "Complete Deductibles in the case before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
        for structure in ("QS", "XOL"):
            for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff")):
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("reinsuredRetention", None)
                else:
                    payload["reinsuredRetention"] = value
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), reinsuredRetention="Request-supplied Reinsured’s Retention")
                check(f"Cover {structure}: {label} stored Reinsured’s Retention -> 409, no audit", r.status_code == 409
                      and code(r) == "reinsured_retention_required" and message(r) == "Complete Reinsured’s Retention in the case before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
        # Stored Situation addresses cannot be supplied by the document request.
        invalid_situations = (("missing", None), ("null", None), ("not an array", {}), ("empty list", []),
                              ("empty row", [{}]), ("null row", [None]), ("missing address with postcode", [{"postcode": "100"}]),
                              ("empty address", [{"address": ""}]), ("null address", [{"address": None}]),
                              ("whitespace address", [{"address": " \t\n"}]), ("fullwidth address", [{"address": "　"}]),
                              ("BOM address", [{"address": "\ufeff"}]),
                              ("later row empty", [{"address": "Valid Risk"}, {"address": ""}]),
                              ("first row empty", [{"address": ""}, {"address": "Valid Risk"}]))
        for structure in ("QS", "XOL"):
            for label, rows in invalid_situations:
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("situations", None)
                else:
                    payload["situations"] = rows
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), situations=[{"address": "Request-supplied address"}])
                check(f"Cover {structure}: {label} stored Situation -> 409, no audit", r.status_code == 409
                      and code(r) == "situation_address_required" and message(r) == "Complete Risk Address for every Situation in the case before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
        # Every stored Postcode must be complete; request data cannot override it.
        invalid_postcodes = (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"),
                            ("fullwidth whitespace", "　"), ("BOM whitespace", "\ufeff"),
                            ("too short", "12"), ("too long", "1234567"), ("letters", "12A"),
                            ("fullwidth digits", "１２３"), ("internal space", "123 45"),
                            ("internal newline", "123\n456"), ("sign", "+123"), ("decimal", "123.0"))
        for structure in ("QS", "XOL"):
            for label, value in invalid_postcodes:
                row = {"address": "Valid Risk"}
                if label != "missing":
                    row["postcode"] = value
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "situations": [row]}
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), situations=[{"address": "Request address", "postcode": "100"}])
                check(f"Cover {structure}: {label} stored Postcode -> 409, no audit", r.status_code == 409
                      and code(r) == "situation_postcode_required" and message(r) == "Complete a 3–6 digit Postcode for every Situation in the case before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
            for rows in ([{"address": "Risk A", "postcode": "100"}, {"address": "Risk B", "postcode": ""}],
                         [{"address": "Risk A", "postcode": ""}, {"address": "Risk B", "postcode": "100"}]):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "situations": rows})
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
                check(f"Cover {structure}: any row with blank Postcode -> 409, no audit", r.status_code == 409 and code(r) == "situation_postcode_required" and gen_audit(posted.case_uid).count() == before)
        for structure in ("QS", "XOL"):
            for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth whitespace", "　"), ("BOM", "\ufeff")):
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("originalPremium", None)
                else:
                    payload["originalPremium"] = value
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                for kind in ("cover", "debit"):
                    before = gen_audit(posted.case_uid).count()
                    r = docx(sales, kind=kind, caseUid=str(posted.case_uid), originalPremium=1000)
                    check(f"{kind} {structure}: {label} stored 100% Premium -> 409, no audit", r.status_code == 409
                          and code(r) == "original_premium_required" and message(r) == "Complete 100% Premium in the case before generating a Cover Note or Debit Note."
                          and gen_audit(posted.case_uid).count() == before)
        invalid_reinsurers = (("missing", None), ("null", None), ("not an array", {}), ("empty list", []),
                              ("empty row", [{}]), ("null row", [None]), ("null share", [{"sharePct": None}]),
                              ("empty share", [{"sharePct": ""}]), ("whitespace share", [{"sharePct": " \t\n"}]),
                              ("fullwidth share", [{"sharePct": "　"}]), ("BOM share", [{"sharePct": "\ufeff"}]),
                              ("later share empty", [{"sharePct": 30}, {"sharePct": ""}]),
                              ("first share empty", [{"sharePct": ""}, {"sharePct": 30}]))
        for structure in ("QS", "XOL"):
            for label, rows in invalid_reinsurers:
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("reinsurers", None)
                else:
                    payload["reinsurers"] = rows
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                for kind in ("cover", "debit"):
                    before = gen_audit(posted.case_uid).count()
                    r = docx(sales, kind=kind, caseUid=str(posted.case_uid), reinsurers=[{"name": "Request Reinsurer", "sharePct": 100}])
                    check(f"{kind} {structure}: {label} stored Order hereon -> 409, no audit", r.status_code == 409
                          and code(r) == "order_hereon_required" and message(r) == "Add at least one Reinsurer and complete Order hereon for every Reinsurer in the case before generating a Cover Note or Debit Note."
                          and gen_audit(posted.case_uid).count() == before)
        invalid_sums = (("missing", None), ("null", None), ("not an array", {}), ("empty list", []),
                        ("empty row", [{}]), ("null row", [None]), ("null name", [{"category": None, "amount": 1000}]),
                        ("empty name", [{"category": "", "amount": 1000}]), ("whitespace name", [{"category": " \t\n"}]),
                        ("fullwidth name", [{"category": "　"}]), ("BOM name", [{"category": "\ufeff"}]),
                        ("later name empty with zero", [{"category": "Building", "amount": 1000}, {"category": "", "amount": 0}]),
                        ("first name empty", [{"category": "", "amount": 1000}, {"category": "Plant", "amount": 1000}]))
        for structure in ("QS", "XOL"):
            for label, rows in invalid_sums:
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
                if label == "missing":
                    payload.pop("sumInsured", None)
                else:
                    payload["sumInsured"] = rows
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), sumInsured=[{"category": "Request-supplied name", "amount": 1000}])
                check(f"Cover {structure}: {label} stored Sum Insured name -> 409, no audit", r.status_code == 409
                      and code(r) == "sum_insured_name_required" and message(r) == "Add at least one Sum Insured entry and complete Interest insured for every entry before generating a Cover Note."
                      and gen_audit(posted.case_uid).count() == before)
        # Leading/trailing whitespace around real field values remains valid.
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsured": "  ZZ Doc Cedant  "})
        from unittest.mock import patch
        from types import SimpleNamespace
        from cases.document_generation_views import _check_case
        for kind in ("cover", "debit"):
            with patch("cases.document_generation_views._find_case", return_value=Case.objects.get(pk=posted.pk)):
                _, _, err = _check_case(None, {"kind": kind, "caseUid": str(posted.case_uid)})
                check(f"{kind}: a real Reinsured with surrounding whitespace is allowed", err is None)
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "originalInsured": "  ZZ Doc Insured  "})
        for kind in ("cover", "debit"):
            with patch("cases.document_generation_views._find_case", return_value=Case.objects.get(pk=posted.pk)):
                _, _, err = _check_case(None, {"kind": kind, "caseUid": str(posted.case_uid)})
                check(f"{kind}: a real Original Insured with surrounding whitespace is allowed", err is None)
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "type": "  Property Facultative Reinsurance  "})
        for kind in ("cover", "debit"):
            with patch("cases.document_generation_views._find_case", return_value=Case.objects.get(pk=posted.pk)):
                _, _, err = _check_case(None, {"kind": kind, "caseUid": str(posted.case_uid)})
                check(f"{kind}: a real Type with surrounding whitespace is allowed", err is None)
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "ae": "  ZZ AE  "})
        for kind in ("cover", "debit", "endorsement"):
            with patch("cases.document_generation_views._find_case", return_value=Case.objects.get(pk=posted.pk)):
                _, _, err = _check_case(None, {"kind": kind, "caseUid": str(posted.case_uid)})
                check(f"{kind}: selected AE with surrounding whitespace is allowed", err is None)
        # Active Personnel fallback follows the same trim, case and ordering rules as Word.
        from cases.document_generation_views import _ae_email
        Personnel.objects.filter(pk=sales_p.pk).update(email="zz.master.email@example.invalid")
        for value in (None, "", " \t", "　", "\ufeff"):
            payload = {**original_payload, "ae": "  " + sales_p.name.upper() + "  ", "aeEmail": value}
            check(f"blank Case Email {value!r} resolves active Personnel", _ae_email(payload) == "zz.master.email@example.invalid")
        check("Case Email overrides active Personnel", _ae_email({**original_payload, "ae": sales_p.name}) == "zz.case.email@example.invalid")
        options = call(sales, "get", "/api/personnel-options")
        chosen = next((p for p in options.json().get("personnel", []) if p["id"] == sales_p.pk), {})
        check("case-writing sales receive AE work Email in personnel options", options.status_code == 200 and chosen.get("email") == "zz.master.email@example.invalid")
        check("anonymous cannot read personnel option emails", call(new_client(), "get", "/api/personnel-options").status_code == 401)
        check("finance cannot read personnel option emails", call(fin, "get", "/api/personnel-options").status_code == 403)
        inactive = person("sales", "business_1")
        Personnel.objects.filter(pk=inactive.pk).update(email="zz.inactive.email@example.invalid", is_active=False, deactivated_at=timezone.now(), deactivated_by="test")
        check("inactive Personnel is not an AE Email fallback", _ae_email({"ae": inactive.name}) == "")
        check("inactive Personnel is absent from options", inactive.pk not in {p["id"] for p in call(sales, "get", "/api/personnel-options").json()["personnel"]})
        # Missing Email on the matching person cannot borrow another person's Email.
        Personnel.objects.filter(pk=sales_p.pk).update(email=None)
        check("blank master Email remains missing", _ae_email({"ae": sales_p.name}) == "")
        Personnel.objects.filter(pk=sales_p.pk).update(email="zz.master.email@example.invalid")
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "interest": "  Buildings  "})
        with patch("cases.document_generation_views._find_case", return_value=Case.objects.get(pk=posted.pk)):
            _, _, err = _check_case(None, {"kind": "cover", "caseUid": str(posted.case_uid)})
            check("Cover Interest with surrounding whitespace is allowed", err is None)
        # Earlier Cover/Debit-only field rules still exclude Endorsement.

        with patch("cases.document_generation_views._find_case", return_value=SimpleNamespace(tw_ref="", payload={"ae": "ZZ AE", "aeEmail": "zz.case.email@example.invalid"})):
            _, _, err = _check_case(None, {"kind": "endorsement", "caseUid": str(posted.case_uid)})
            check("Endorsement without Reinsured retains existing rules", err is None)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        check("no audit written for any rejected request", not AuditLog.objects.filter(action="generate_document", actor_id=f"personnel:{sales_p.pk}").exists())

        # Word generation checks permissions, case gates and metadata logging.
        for kind in ("cover", "debit", "endorsement"):
            before = gen_audit(posted.case_uid).count()
            r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
            a = gen_audit(posted.case_uid).order_by("-id").first()
            check(f"Word {kind} -> 204 with exactly one metadata audit", r.status_code == 204
                  and gen_audit(posted.case_uid).count() == before + 1 and a.metadata == {"kind": kind, "format": "docx"}
                  and a.actor_id == f"personnel:{sales_p.pk}" and a.after_data["format"] == "docx"
                  and "markup" not in json.dumps(a.after_data))
            check(f"Word {kind} response no-store", "no-store" in r.get("Cache-Control", ""))
        for label, c in (("general manager", gm), ("admin", admin)):
            check(f"{label} (documents.read) can generate Endorsement Word", docx(c, kind="endorsement", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "ae": sales_p.name, "aeEmail": " "})
        for kind in ("cover", "debit", "endorsement"):
            r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
            check(f"{kind}: active Personnel Email permits Word -> 204", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "interest": ""})
        for kind in ("debit", "endorsement"):
            r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
            check(f"{kind}: missing Interest does not block Word", r.status_code == 204)
        for structure in ("QS", "XOL"):
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "interest": "  Buildings  "})
            r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
            check(f"Cover {structure}: saved Interest permits Word", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "limitOfLiability": None})
        for kind in ("debit", "endorsement"):
            r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
            check(f"{kind}: missing Limit of Liability does not block Word", r.status_code == 204)
        for structure in ("QS", "XOL"):
            for value in (0, "0", 1000):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "limitOfLiability": value})
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
                check(f"Cover {structure}: stored Limit of Liability {value!r} permits Word", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for value in (None, "", " \t\n", "　", "\ufeff"):
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": "QS", "underlyingLimits": value})
            r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
            check(f"Cover QS: blank Underlying Limits {value!r} remains permitted", r.status_code == 204)
        for structure in ("XOL",):
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": ""})
            for kind in ("debit", "endorsement"):
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                check(f"{kind} {structure}: blank Underlying Limits does not block Word", r.status_code == 204)
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "  Primary layer limit  "})
            r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
            check(f"Cover {structure}: saved Underlying Limits permits Word", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "deductibles": ""})
            for kind in ("debit", "endorsement"):
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                check(f"{kind} {structure}: blank Deductibles does not block Word", r.status_code == 204)
            for value in ("  10%  ", "Nil", "基本自負額\n依原保單"):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "deductibles": value})
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
                check(f"Cover {structure}: saved Deductibles {value!r} permits Word", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "reinsuredRetention": ""})
            for kind in ("debit", "endorsement"):
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                check(f"{kind} {structure}: blank Reinsured’s Retention does not block Word", r.status_code == 204)
            for value in ("  Advice of Reinsured's retention waived.  ", "Nil", "自留額 <A> & <B>\n依原保單"):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "reinsuredRetention": value})
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
                check(f"Cover {structure}: saved Reinsured’s Retention {value!r} permits Word", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "situations": []})
            for kind in ("debit", "endorsement"):
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                check(f"{kind} {structure}: missing Situation does not block Word", r.status_code == 204)
            for rows in ([{"address": "  Sample Risk  ", "postcode": "100"}], [{"address": "Sample Risk", "postcode": "001"}],
                         [{"address": "Risk A", "postcode": "100"}, {"address": "風險 <B> & C\n二樓", "postcode": "123456"}]):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "situations": rows, "sumInsured": [{"category": "Building", "amount": 1000, "locationIndex": index} for index in range(len(rows))]})
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
                check(f"Cover {structure}: all addresses and postcodes saved {rows!r} -> 204", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            for value in ("001", "1234", "12345", "123456", " 100 ", "\ufeff001　"):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "situations": [{"address": "Valid Risk", "postcode": value}]})
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
                check(f"Cover {structure}: valid stored Postcode {value!r} -> 204", r.status_code == 204)
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "situations": [{"address": "Valid Risk", "postcode": ""}]})
            for kind in ("debit", "endorsement"):
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                check(f"{kind} {structure}: missing Postcode does not block Word", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            for value in (0, "0", 1000):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "originalPremium": value})
                for kind in ("cover", "debit"):
                    r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                    check(f"{kind} {structure}: stored 100% Premium {value!r} -> 204", r.status_code == 204)
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "originalPremium": None})
            r = docx(sales, kind="endorsement", caseUid=str(posted.case_uid))
            check(f"Endorsement {structure}: missing 100% Premium remains permitted", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            for rows in ([{"sharePct": 0}], [{"sharePct": "0"}], [{"sharePct": 20}, {"sharePct": 30}], [{"sharePct": 12.3456}, {"sharePct": 0}, {"sharePct": 7.6544}]):
                # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
                rows = [{**row, "name": f"Sample Reinsurer {index + 1}", "paymentTermsDays": 30} for index, row in enumerate(rows)]
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "reinsurers": rows})
                for kind in ("cover", "debit"):
                    r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                    check(f"{kind} {structure}: saved Order hereon {rows!r} -> 204", r.status_code == 204)
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "reinsurers": []})
            r = docx(sales, kind="endorsement", caseUid=str(posted.case_uid))
            check(f"Endorsement {structure}: missing Reinsurer shares remains permitted", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            for rows in ([{"category": "Building", "amount": 1000}], [{"category": "  Plant  ", "amount": 1}],
                         [{"category": "設備 <A> & B", "amount": 1000}, {"category": "Second item", "amount": 1000}]):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "sumInsured": rows})
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid))
                check(f"Cover {structure}: saved names {rows!r} -> 204, positive amounts", r.status_code == 204)
            Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "sumInsured": []})
            for kind in ("debit", "endorsement"):
                r = docx(sales, kind=kind, caseUid=str(posted.case_uid))
                check(f"{kind} {structure}: missing Sum Insured names remains permitted", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        for structure in ("QS", "XOL"):
            for value in (None, "", "　", "\ufeff", 0, "0", -1, "-1", "bad", "1bad", "Infinity"):
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "sumInsured": [{"category": "First", "amount": 1000}, {"category": "Second", "amount": value}]}
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                r = docx(sales, kind="cover", caseUid=str(posted.case_uid), sumInsured=[{"category": "Request", "amount": 1000}])
                check(f"Cover {structure}: stored amount {value!r} blocked without audit", r.status_code == 409 and code(r) == "sum_insured_amount_required" and message(r) == "Enter an Amount greater than 0 for every Sum Insured entry before generating a Cover Note." and gen_audit(posted.case_uid).count() == before)
                for kind in ("debit", "endorsement"):
                    check(f"{kind} {structure}: amount {value!r} imposes no document restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
            for value in (0.01, 1, "1", " 1000.25 "):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "sumInsured": [{"category": "Building", "amount": value}]})
                check(f"Cover {structure}: positive amount {value!r} accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Saved Location assignments and within-group unique names govern Cover.
        from cases.sum_insured import placement_issues
        situations = [{"address": "Risk A", "postcode": "100"}, {"address": "Risk B", "postcode": "200"}]
        valid_rows = [{"category": "Building", "amount": 1000, "locationIndex": 0}, {"category": "Building", "amount": 2000, "locationIndex": 1}]
        scenarios = [
            ("valid two Locations", valid_rows, None),
            ("missing second Location", valid_rows[:1], "sum_insured_locations_required"),
            ("unassigned", [{**row, "locationIndex": None} for row in valid_rows], "sum_insured_locations_required"),
            ("out of range", [valid_rows[0], {**valid_rows[1], "locationIndex": 3}], "sum_insured_locations_required"),
            ("fractional", [valid_rows[0], {**valid_rows[1], "locationIndex": 0.5}], "sum_insured_locations_required"),
            ("duplicate within Location", valid_rows + [{"category": " building ", "amount": 1, "locationIndex": 0}], "sum_insured_duplicate_names"),
        ]
        for structure in ("QS", "XOL"):
            for label, rows, expected in scenarios:
                payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "situations": situations, "sumInsured": rows}
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                response = docx(sales, kind="cover", caseUid=str(posted.case_uid), sumInsured=valid_rows)
                check(f"Cover {structure}: {label}", code(response) == expected and response.status_code == (409 if expected else 204) and gen_audit(posted.case_uid).count() == before + (0 if expected else 1), response.content[:150])
                for kind in ("debit", "endorsement"):
                    check(f"{kind} {structure}: Location/duplicate rules do not gate document", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
            facility = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "situations": situations, "reinsurers": [{"name": "RI (Facility)", "sharePct": 100, "paymentTermsDays": 30}], "sumInsured": [{"category": "Building", "amount": 3000, "locationIndex": None}]}  # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
            Case.objects.filter(pk=posted.pk).update(payload=facility)
            check(f"Cover {structure}: all Facility skips Location coverage", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
            facility["sumInsured"].append({"category": "BUILDING", "amount": 1000, "locationIndex": 1})
            Case.objects.filter(pk=posted.pk).update(payload=facility)
            check(f"Cover {structure}: all Facility still requires unique names", code(docx(sales, kind="cover", caseUid=str(posted.case_uid))) == "sum_insured_duplicate_names")
            facility["reinsurers"].append({"name": "Non-Facility RI", "sharePct": 0, "paymentTermsDays": 30})
            facility["sumInsured"] = [{"category": "Building", "amount": 1000, "locationIndex": 0}]
            Case.objects.filter(pk=posted.pk).update(payload=facility)
            check(f"Cover {structure}: mixed RI requires every Location", code(docx(sales, kind="cover", caseUid=str(posted.case_uid))) == "sum_insured_locations_required")
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # The advice date is read from saved Case data, including clean loss histories.
        for structure in ("QS", "XOL"):
            for facility in (False, True):
                for value in (None, "", " \t\n", "　", "\ufeff"):
                    payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "lossAdvisedDate": value, "lossRecordYears": 0, "lossRecord": []}
                    if facility:
                        payload["reinsurers"] = [{"name": "RI (Facility)", "sharePct": 100, "paymentTermsDays": 30}]  # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
                    Case.objects.filter(pk=posted.pk).update(payload=payload)
                    before = gen_audit(posted.case_uid).count()
                    response = docx(sales, kind="cover", caseUid=str(posted.case_uid), lossAdvisedDate="2026-10-13")
                    check(f"Cover {structure}/Facility={facility}: blank saved advice date {value!r} blocked without audit", response.status_code == 409 and code(response) == "loss_advised_date_required" and message(response) == "Complete the Loss Record advised date in the case before generating a Cover Note." and gen_audit(posted.case_uid).count() == before)
                    for kind in ("debit", "endorsement"):
                        check(f"{kind} {structure}: missing advice date has no document restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
            payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
            payload.pop("lossAdvisedDate", None)
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            check(f"Cover {structure}: missing saved advice date blocked", code(docx(sales, kind="cover", caseUid=str(posted.case_uid))) == "loss_advised_date_required")
            for value in ("2026-10-13", "2024-02-29", " 2026-01-01 "):
                Case.objects.filter(pk=posted.pk).update(payload={**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "lossAdvisedDate": value})
                check(f"Cover {structure}: saved advice date {value!r} accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Missing saved history years must never become a fictional 5-year history.
        for structure in ("QS", "XOL"):
            for facility in (False, True):
                for label, value in (("missing", None), ("null", None), ("empty", ""), ("whitespace", " \t\n"), ("fullwidth", "　"), ("BOM", "\ufeff")):
                    payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "newOrRenew": "New", "lossRecord": []}
                    if label == "missing":
                        payload.pop("lossRecordYears", None)
                    else:
                        payload["lossRecordYears"] = value
                    if facility:
                        payload["reinsurers"] = [{"name": "RI (Facility)", "sharePct": 100, "paymentTermsDays": 30}]  # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
                    Case.objects.filter(pk=posted.pk).update(payload=payload)
                    before = gen_audit(posted.case_uid).count()
                    response = docx(sales, kind="cover", caseUid=str(posted.case_uid), lossRecordYears=5)
                    check(f"Cover {structure}/Facility={facility}: {label} saved history years blocked without audit/request override", response.status_code == 409 and code(response) == "loss_record_years_required" and message(response) == 'Complete Past year(s) in the Loss Record section of the case before generating a Cover Note.' and gen_audit(posted.case_uid).count() == before)
                    for kind in ("debit", "endorsement"):
                        check(f"{kind} {structure}/Facility={facility}: blank history years has no new restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
                for value in (0, "0", " 0 ", 1, 5):
                    payload = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "newOrRenew": "New", "lossRecordYears": value, "lossRecord": []}
                    if facility:
                        payload["reinsurers"] = [{"name": "RI (Facility)", "sharePct": 100, "paymentTermsDays": 30}]  # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
                    Case.objects.filter(pk=posted.pk).update(payload=payload)
                    check(f"Cover {structure}/Facility={facility}: saved years {value!r} accepted including zero", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Every saved loss entry requires a date; do not invent one from the request.
        dated_loss = {"date": "2024-02-29", "cause": "Fire", "lossPaid": 0}
        undated_losses = [("missing date", [{"cause": "Fire", "lossPaid": 0}])]
        undated_losses += [(f"blank date {value!r}", [{**dated_loss, "date": value}]) for value in (None, "", " \t\n", "　", "\ufeff")]
        undated_losses += [("first date missing", [{**dated_loss, "date": ""}, dated_loss]), ("later date missing", [dated_loss, {**dated_loss, "date": ""}]), ("null loss row", [None])]
        for structure in ("QS", "XOL"):
            for facility in (False, True):
                base = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "lossRecordYears": 5}
                if facility:
                    base["reinsurers"] = [{"name": "RI (Facility)", "sharePct": 100, "paymentTermsDays": 30}]  # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
                for label, losses in undated_losses:
                    Case.objects.filter(pk=posted.pk).update(payload={**base, "lossRecord": losses})
                    before = gen_audit(posted.case_uid).count()
                    response = docx(sales, kind="cover", caseUid=str(posted.case_uid), lossRecord=[dated_loss])
                    check(f"Cover {structure}/Facility={facility}: {label} blocked without audit/request override", response.status_code == 409 and code(response) == "loss_record_date_required" and message(response) == 'Complete Date of Loss for every Loss Record entry in the case before generating a Cover Note.' and gen_audit(posted.case_uid).count() == before)
                    for kind in ("debit", "endorsement"):
                        check(f"{kind} {structure}/Facility={facility}: loss date has no new restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
                for label, losses in (("clean history", []), ("one dated loss", [dated_loss]), ("multiple dated losses", [dated_loss, {**dated_loss, "date": "2026-10-13"}])):
                    Case.objects.filter(pk=posted.pk).update(payload={**base, "lossRecord": losses})
                    check(f"Cover {structure}/Facility={facility}: {label} accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
                payload = {**base, "lossRecordYears": 0, "newOrRenew": "New"}
                payload.pop("lossRecord", None)
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                check(f"Cover {structure}/Facility={facility}: no loss rows and New zero accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Every saved loss entry requires a Cause, with dates completed first.
        described_loss = {"date": "2024-02-29", "cause": "Fire", "lossPaid": 0}
        missing_causes = [("missing cause", [{"date": "2024-02-29", "lossPaid": 0}])]
        missing_causes += [(f"blank cause {value!r}", [{**described_loss, "cause": value}]) for value in (None, "", " \t\n", "　", "\ufeff")]
        missing_causes += [("first cause missing", [{**described_loss, "cause": ""}, described_loss]), ("later cause missing", [described_loss, {**described_loss, "cause": ""}])]
        for structure in ("QS", "XOL"):
            for facility in (False, True):
                cause_base = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "lossRecordYears": 5}
                if facility:
                    cause_base["reinsurers"] = [{"name": "RI (Facility)", "sharePct": 100, "paymentTermsDays": 30}]  # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
                for label, losses in missing_causes:
                    Case.objects.filter(pk=posted.pk).update(payload={**cause_base, "lossRecord": losses})
                    before = gen_audit(posted.case_uid).count()
                    response = docx(sales, kind="cover", caseUid=str(posted.case_uid), lossRecord=[described_loss])
                    check(f"Cover {structure}/Facility={facility}: {label} blocked without audit/request override", response.status_code == 409 and code(response) == "loss_record_cause_required" and message(response) == 'Complete Cause for every Loss Record entry in the case before generating a Cover Note.' and gen_audit(posted.case_uid).count() == before)
                    for kind in ("debit", "endorsement"):
                        check(f"{kind} {structure}/Facility={facility}: loss cause has no new restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
                for label, losses in (("clean history", []), ("one described loss", [described_loss]), ("multiple described losses", [described_loss, {**described_loss, "date": "2026-10-13", "cause": "Flood"}])):
                    Case.objects.filter(pk=posted.pk).update(payload={**cause_base, "lossRecord": losses})
                    check(f"Cover {structure}/Facility={facility}: {label} accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
                payload = {**cause_base, "lossRecordYears": 0, "newOrRenew": "New"}
                payload.pop("lossRecord", None)
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                check(f"Cover {structure}/Facility={facility}: no loss rows and New zero accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Saved Loss Paid is required for every entry; numeric zero is present.
        paid_loss = {"date": "2024-02-29", "cause": "Fire", "lossPaid": 0}
        unpaid_amounts = [("missing paid amount", [{"date": "2024-02-29", "cause": "Fire"}])]
        unpaid_amounts += [(f"blank paid amount {value!r}", [{**paid_loss, "lossPaid": value}]) for value in (None, "", " \t\n", "　", "\ufeff")]
        unpaid_amounts += [("first paid amount missing", [{**paid_loss, "lossPaid": ""}, paid_loss]), ("later paid amount missing", [paid_loss, {**paid_loss, "lossPaid": ""}])]
        for structure in ("QS", "XOL"):
            for facility in (False, True):
                paid_base = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit", "lossRecordYears": 5}
                if facility:
                    paid_base["reinsurers"] = [{"name": "RI (Facility)", "sharePct": 100, "paymentTermsDays": 30}]  # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
                for label, losses in unpaid_amounts:
                    Case.objects.filter(pk=posted.pk).update(payload={**paid_base, "lossRecord": losses})
                    before = gen_audit(posted.case_uid).count()
                    response = docx(sales, kind="cover", caseUid=str(posted.case_uid), lossRecord=[paid_loss])
                    check(f"Cover {structure}/Facility={facility}: {label} blocked without audit/request override", response.status_code == 409 and code(response) == "loss_record_paid_required" and message(response) == 'Complete Loss Paid for every Loss Record entry in the case before generating a Cover Note.' and gen_audit(posted.case_uid).count() == before)
                    for kind in ("debit", "endorsement"):
                        check(f"{kind} {structure}/Facility={facility}: paid amount has no new restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
                for amount in (0, "0", " 0 ", 0.01, 125.5):
                    Case.objects.filter(pk=posted.pk).update(payload={**paid_base, "lossRecord": [{**paid_loss, "lossPaid": amount}]})
                    check(f"Cover {structure}/Facility={facility}: saved Loss Paid {amount!r} accepted including zero", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
                for label, losses in (("clean history", []), ("multiple paid entries", [paid_loss, {**paid_loss, "date": "2026-10-13", "cause": "Flood", "lossPaid": 125.5}])):
                    Case.objects.filter(pk=posted.pk).update(payload={**paid_base, "lossRecord": losses})
                    check(f"Cover {structure}/Facility={facility}: {label} accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
                payload = {**paid_base, "lossRecordYears": 0, "newOrRenew": "New"}
                payload.pop("lossRecord", None)
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                check(f"Cover {structure}/Facility={facility}: no loss rows and New zero accepted", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Reinsurer identity comes from saved name, not Foreign RI Broker/request.
        # 2026-10-16「92 項會計規則重新確認」：再保人付款天數須獨立填寫、不繼承 Case 預設；替換的再保人列明確填 30 天，維持原本只測其他欄位的意圖。
        named_ri = {"name": "ZZ Named Reinsurer", "sharePct": 100, "foreignBroker": "ZZ Foreign Broker", "paymentTermsDays": 30}
        missing_names = [("missing name", [{"sharePct": 0, "foreignBroker": "ZZ Foreign Broker", "paymentTermsDays": 30}])]
        missing_names += [(f"blank name {value!r}", [{**named_ri, "name": value}]) for value in (None, "", " \t\n", "　", "\ufeff")]
        missing_names += [("first name missing", [{**named_ri, "name": "", "sharePct": 0}, named_ri]), ("later name missing", [named_ri, {**named_ri, "name": "", "sharePct": 0}])]
        for structure in ("QS", "XOL"):
            name_base = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary layer limit"}
            for label, reinsurers in missing_names:
                Case.objects.filter(pk=posted.pk).update(payload={**name_base, "reinsurers": reinsurers})
                before = gen_audit(posted.case_uid).count()
                response = docx(sales, kind="cover", caseUid=str(posted.case_uid), reinsurers=[named_ri])
                check(f"Cover {structure}: {label} blocked despite broker/request, without audit", response.status_code == 409 and code(response) == "reinsurer_name_required" and message(response) == 'Complete the Reinsurer name for every Schedule of Security entry in the case before generating a Cover Note.' and gen_audit(posted.case_uid).count() == before)
                for kind in ("debit", "endorsement"):
                    check(f"{kind} {structure}: no new Reinsurer name restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
            for reinsurers in ([named_ri], [{**named_ri, "name": "  ZZ Named Reinsurer  ", "sharePct": 0}], [{**named_ri, "name": "ZZ RI (Facility)", "sharePct": 60}, {**named_ri, "name": "ZZ Second RI (Facility)", "sharePct": 40}]):
                Case.objects.filter(pk=posted.pk).update(payload={**name_base, "reinsurers": reinsurers})
                check(f"Cover {structure}: saved Reinsurer names accepted with Foreign RI Broker", docx(sales, kind="cover", caseUid=str(posted.case_uid)).status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Non-installment Debit Notes require effective terms for every saved RI.
        # 2026-10-16「92 項會計規則重新確認」：每家普通再保人的付款天數須獨立填寫，沒有預設繼承（不再以 Case 預設補位）；
        # 錯誤訊息改為 "...independently for every Reinsurer..."，以下 Case 預設相關斷言依此更新。
        terms_bad = [None, "", " \t\n", "　", "\ufeff", 0, "0", -1, 14, "14", 15.5, "15.5", "bad", "90days", True, False, [], {}, [None], "１５"]
        terms_ri = {"name": "ZZ Terms RI", "sharePct": 50}
        for structure in ("QS", "XOL"):
            terms_base = {**original_payload, "reinsuranceStructure": structure, "underlyingLimits": "Primary", "installmentEnabled": False}
            for value in terms_bad:
                payload = {**terms_base, "paymentTermsDays": value, "reinsurers": [{**terms_ri, "paymentTermsDays": value}]}
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before = gen_audit(posted.case_uid).count()
                response = docx(sales, kind="debit", caseUid=str(posted.case_uid), paymentTermsDays=90, installmentEnabled=True, reinsurers=[{**terms_ri, "paymentTermsDays": 90}])
                check(f"Debit {structure}: invalid terms {value!r} blocked without request override/audit", response.status_code == 409 and code(response) == "debit_payment_terms_required" and message(response) == 'Complete valid Payment Terms Days (an integer of at least 15) independently for every Reinsurer, before generating a Debit Note.' and gen_audit(posted.case_uid).count() == before)
                for kind in ("cover", "endorsement"):
                    check(f"{kind} {structure}: no new payment term restriction", docx(sales, kind=kind, caseUid=str(posted.case_uid)).status_code == 204)
            mixed = [{**terms_ri, "paymentTermsDays": 90}, {**terms_ri, "name": "ZZ Terms RI 2", "paymentTermsDays": None}]
            for rows in (mixed, mixed[::-1], [{**mixed[0], "sharePct": 100}, {**mixed[1], "sharePct": 0}]):
                Case.objects.filter(pk=posted.pk).update(payload={**terms_base, "paymentTermsDays": None, "reinsurers": rows})
                response = docx(sales, kind="debit", caseUid=str(posted.case_uid))
                check(f"Debit {structure}: every RI requires terms, including zero-share RI", response.status_code == 409 and code(response) == "debit_payment_terms_required")
            payload = {**terms_base, "reinsurers": [terms_ri]};payload.pop("paymentTermsDays",None)
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            response = docx(sales, kind="debit", caseUid=str(posted.case_uid))
            check(f"Debit {structure}: both term fields missing blocked", response.status_code == 409 and code(response) == "debit_payment_terms_required")
            for value in (15, "15", 15.0, "15.0", 90, " 90 ", "9e1", "0x5a"):
                Case.objects.filter(pk=posted.pk).update(payload={**terms_base, "paymentTermsDays": None, "reinsurers": [{**terms_ri, "paymentTermsDays": value}]})
                check(f"Debit {structure}: valid effective terms None/{value!r} accepted", docx(sales, kind="debit", caseUid=str(posted.case_uid)).status_code == 204)
                # 2026-10-16：只有 Case 預設天數、再保人未填 -> 不繼承，阻擋（原斷言為 204）。
                Case.objects.filter(pk=posted.pk).update(payload={**terms_base, "paymentTermsDays": value, "reinsurers": [{**terms_ri, "paymentTermsDays": None}]})
                response = docx(sales, kind="debit", caseUid=str(posted.case_uid))
                check(f"Debit {structure}: valid Case default {value!r} alone is not inherited by the Reinsurer", response.status_code == 409 and code(response) == "debit_payment_terms_required")
            for value in terms_bad:
                # 2026-10-16：再保人天數無效時不得以有效的 Case 預設 90 取代（原斷言為 204）。
                Case.objects.filter(pk=posted.pk).update(payload={**terms_base, "paymentTermsDays": 90, "reinsurers": [{**terms_ri,"paymentTermsDays":value}]})
                response = docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: invalid RI terms {value!r} not replaced by valid Case default", response.status_code==409 and code(response)=="debit_payment_terms_required")
            for enabled in (True,False,None,0,1,"true"):
                # 2026-10-16：分期天數須逐期逐家再保人填寫（reinsurerPaymentTerms），期別預設 paymentTermsDays 不再繼承，故補 r1。
                Case.objects.filter(pk=posted.pk).update(payload={**terms_base,"installmentEnabled":enabled,"paymentTermsDays":None,"reinsurers":[terms_ri],"performanceInstallments":[{"paymentBaseDate":"2026-03-01","paymentTermsDays":90,"reinsurerPaymentTerms":{"r1":90},"ratio":100}]})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: installment flag {enabled!r} respects strict boolean scope", response.status_code==(204 if enabled is True else 409) and (enabled is True or code(response)=="debit_payment_terms_required"))
        for enabled in (True,False):
            Case.objects.filter(pk=draft.pk).update(payload={"reinsuranceStructure":"TREATY","installmentEnabled":enabled,"paymentTermsDays":None,"reinsurers":[terms_ri],"performanceInstallments":[{"paymentBaseDate":"2026-03-01","paymentTermsDays":90,"ratio":100}]})
            check(f"Treaty Draft debit terms exempt, installments={enabled}",docx(sales,kind="debit",caseUid=str(draft.case_uid)).status_code==204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Every installment needs its own real ISO calendar date; no fallback.
        base_dates_bad=[None,""," \t\n","　","\ufeff","2026-02-30","2025-02-29","1900-02-29","2026-04-31","2026-00-01","2026-13-01","2026-01-00","2026-01-32","2026-1-01","2026-01-1","01/01/2026","2026-01-01T00:00:00Z"," 2026-01-01 ","2026-01-01\n","0000-01-01","not a date",0,False,[],{},["2026-01-01"],"２０２６-０１-０１"]
        base_dates_valid=["2026-01-01","2024-02-29","2000-02-29","2400-02-29","0001-01-01","9999-01-01","2026-12-31","1900-03-01","2026-02-28","2026-04-30","2027-01-01","2026-03-01"]
        # 2026-10-16「92 項會計規則重新確認」：每期每家再保人天數獨立填寫，fixture 明確填 r1，讓本段只測日期。
        good_inst={"performanceMonth":"2026-03","paymentBaseDate":"2026-03-01","ratio":100,"reinsurerPaymentTerms":{"r1":30}}
        bad_inst_rows=[None,{},[],[None],[{}],[good_inst,{**good_inst,"paymentBaseDate":""}],[{**good_inst,"paymentBaseDate":""},good_inst],[good_inst,None]]
        for structure in ("QS","XOL"):
            dates_base={**original_payload,"reinsuranceStructure":structure,"underlyingLimits":"Primary","installmentEnabled":True}
            for value in base_dates_bad:
                Case.objects.filter(pk=posted.pk).update(payload={**dates_base,"performanceInstallments":[{**good_inst,"paymentBaseDate":value}]})
                before=gen_audit(posted.case_uid).count()
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid),performanceInstallments=[good_inst],installmentEnabled=False)
                check(f"Debit {structure}: invalid saved installment date {value!r} blocked without fallback/request override/audit",response.status_code==409 and code(response)=="debit_installment_base_date_required" and message(response)=='Add at least one installment and complete a valid Payment Base Date for every installment before generating a Debit Note.' and gen_audit(posted.case_uid).count()==before)
                for kind in ("cover","endorsement"):
                    check(f"{kind} {structure}: no new installment date requirement",docx(sales,kind=kind,caseUid=str(posted.case_uid)).status_code==204)
            for rows in bad_inst_rows:
                Case.objects.filter(pk=posted.pk).update(payload={**dates_base,"performanceInstallments":rows})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: malformed/missing/incomplete installment rows {rows!r} blocked",response.status_code==409 and code(response)=="debit_installment_base_date_required")
            payload={**dates_base};payload.pop("performanceInstallments",None)
            Case.objects.filter(pk=posted.pk).update(payload=payload)
            response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
            check(f"Debit {structure}: missing installment array blocked",response.status_code==409 and code(response)=="debit_installment_base_date_required")
            for value in base_dates_valid:
                Case.objects.filter(pk=posted.pk).update(payload={**dates_base,"performanceInstallments":[{**good_inst,"paymentBaseDate":value}]})
                check(f"Debit {structure}: saved real installment date {value!r} accepted",docx(sales,kind="debit",caseUid=str(posted.case_uid)).status_code==204)
            for rows in ([good_inst,{**good_inst,"paymentBaseDate":"2026-06-01"}],[good_inst,{**good_inst,"paymentBaseDate":"2024-02-29"}]):
                Case.objects.filter(pk=posted.pk).update(payload={**dates_base,"performanceInstallments":rows})
                check(f"Debit {structure}: all valid installments accepted without new coverage-range restriction",docx(sales,kind="debit",caseUid=str(posted.case_uid)).status_code==204)
            for enabled in (True,False,None,0,1,"true"):
                Case.objects.filter(pk=posted.pk).update(payload={**dates_base,"installmentEnabled":enabled,"performanceInstallments":[]})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: installment date requirement scope is strict boolean {enabled!r}",response.status_code==(409 if enabled is True else 204) and (enabled is not True or code(response)=="debit_installment_base_date_required"))
        for rows in (None,[],[{"paymentBaseDate":"2026-02-30"}]):
            Case.objects.filter(pk=draft.pk).update(payload={"reinsuranceStructure":"TREATY","installmentEnabled":True,"performanceInstallments":rows})
            check("Treaty Draft debit remains exempt from installment dates",docx(sales,kind="debit",caseUid=str(draft.case_uid)).status_code==204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Every installment/RI pair must resolve terms from the four sources.
        # 2026-10-16「92 項會計規則重新確認」：「每期每家普通再保人的約定天數須獨立填寫，沒有預設繼承」。
        # 原本四個來源（期別×再保人、再保人預設、期別預設、Case 預設）任一有效即可；現只有期別×再保人（reinsurerPaymentTerms）有效，
        # 其餘三個來源單獨存在或作為後備都必須阻擋。以下斷言依此改為 409。
        inst_terms_bad=[None,""," \t\n","　","\ufeff",0,"0",-1,14,"14",15.5,"15.5","bad","90days",True,False,[],{},[None],"１５"]
        inst_terms_good=(15,"15",15.0,"15.0",90," 90 ","9e1","0x5a")
        inst_terms_ri={"name":"ZZ Installment Terms RI","sharePct":50,"paymentTermsDays":None}
        inst_terms_row={"performanceMonth":"2026-03","paymentBaseDate":"2026-03-01","ratio":50,"paymentTermsDays":None,"reinsurerPaymentTerms":{"r1":None,"r2":None}}
        for structure in ("QS","XOL"):
            pair_base={**original_payload,"reinsuranceStructure":structure,"underlyingLimits":"Primary","installmentEnabled":True,"paymentTermsDays":None}
            pair_ris=[inst_terms_ri,{**inst_terms_ri,"name":"ZZ Second RI"}]
            for value in inst_terms_bad:
                row={**inst_terms_row,"paymentTermsDays":value,"reinsurerPaymentTerms":{"r1":value,"r2":value}}
                payload={**pair_base,"paymentTermsDays":value,"reinsurers":[{**r,"paymentTermsDays":value} for r in pair_ris],"performanceInstallments":[row]}
                Case.objects.filter(pk=posted.pk).update(payload=payload)
                before=gen_audit(posted.case_uid).count()
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid),paymentTermsDays=90,reinsurers=[{**r,"paymentTermsDays":90} for r in pair_ris],performanceInstallments=[{**row,"paymentTermsDays":90,"reinsurerPaymentTerms":{"r1":90,"r2":90}}],installmentEnabled=False)
                check(f"Debit {structure}: invalid installment terms {value!r} blocked without request override/audit",response.status_code==409 and code(response)=="debit_installment_payment_terms_required" and message(response)=='Complete valid Payment Terms Days (an integer of at least 15) for every Reinsurer in every installment before generating a Debit Note.' and gen_audit(posted.case_uid).count()==before)
                for kind in ("cover","endorsement"):
                    check(f"{kind} {structure}: no new installment term requirement",docx(sales,kind=kind,caseUid=str(posted.case_uid)).status_code==204)
            for value in inst_terms_good:
                for source_index in range(4):
                    payload={**pair_base,"reinsurers":pair_ris,"performanceInstallments":[inst_terms_row]}
                    if source_index==0:payload["performanceInstallments"]=[{**inst_terms_row,"reinsurerPaymentTerms":{"r1":value,"r2":value}}]
                    elif source_index==1:payload["reinsurers"]=[{**r,"paymentTermsDays":value} for r in pair_ris]
                    elif source_index==2:payload["performanceInstallments"]=[{**inst_terms_row,"paymentTermsDays":value}]
                    else:payload["paymentTermsDays"]=value
                    Case.objects.filter(pk=posted.pk).update(payload=payload)
                    response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                    if source_index==0:
                        check(f"Debit {structure}: source 1 (installment x Reinsurer) alone resolves valid terms {value!r}",response.status_code==204)
                    else:
                        check(f"Debit {structure}: source {source_index+1} alone is not inherited {value!r}",response.status_code==409 and code(response)=="debit_installment_payment_terms_required")
            for value in inst_terms_bad:
                for fallback in (1,2,3):
                    payload={**pair_base,"reinsurers":pair_ris,"performanceInstallments":[{**inst_terms_row,"reinsurerPaymentTerms":{"r1":value,"r2":value}}]}
                    if fallback==1:payload["reinsurers"]=[{**r,"paymentTermsDays":90} for r in pair_ris]
                    elif fallback==2:payload["performanceInstallments"][0]["paymentTermsDays"]=90
                    else:payload["paymentTermsDays"]=90
                    Case.objects.filter(pk=posted.pk).update(payload=payload)
                    response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                    check(f"Debit {structure}: invalid override {value!r} not replaced by fallback source {fallback+1}",response.status_code==409 and code(response)=="debit_installment_payment_terms_required")
            complete={**inst_terms_row,"reinsurerPaymentTerms":{"r1":90,"r2":90}}
            incomplete={**inst_terms_row,"performanceMonth":"2026-04","paymentBaseDate":"2026-04-01","reinsurerPaymentTerms":{"r1":90,"r2":None}}
            for rows,ris in (([complete,incomplete],pair_ris),([{**incomplete,"reinsurerPaymentTerms":{"r1":None,"r2":90}},complete],pair_ris),([complete,{**incomplete,"reinsurerPaymentTerms":{}}],pair_ris),([incomplete],[{**pair_ris[0],"sharePct":100},{**pair_ris[1],"sharePct":0}])):
                Case.objects.filter(pk=posted.pk).update(payload={**pair_base,"reinsurers":ris,"performanceInstallments":rows})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: every pair checked including later/first/entire-period/zero-share gaps",response.status_code==409 and code(response)=="debit_installment_payment_terms_required")
            for mapping in (None,[],90,"bad",{}):
                Case.objects.filter(pk=posted.pk).update(payload={**pair_base,"paymentTermsDays":90,"reinsurers":pair_ris,"performanceInstallments":[{**inst_terms_row,"reinsurerPaymentTerms":mapping}]})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: malformed override mapping is safely blocked, not filled from Case default",response.status_code==409 and code(response)=="debit_installment_payment_terms_required")
            for enabled in (True,False,None,0,1,"true"):
                Case.objects.filter(pk=posted.pk).update(payload={**pair_base,"installmentEnabled":enabled,"reinsurers":pair_ris,"performanceInstallments":[inst_terms_row]})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                expected="debit_installment_payment_terms_required" if enabled is True else "debit_payment_terms_required"
                check(f"Debit {structure}: term scope respects strict boolean {enabled!r}",response.status_code==409 and code(response)==expected)
        for enabled in (True,False):
            Case.objects.filter(pk=draft.pk).update(payload={"reinsuranceStructure":"TREATY","installmentEnabled":enabled,"reinsurers":[inst_terms_ri],"performanceInstallments":[inst_terms_row]})
            check("Treaty Draft debit remains exempt from installment term checks",docx(sales,kind="debit",caseUid=str(draft.case_uid)).status_code==204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # All installments lacking both allocation sources must not silently split equally.
        # 2026-10-16「92 項會計規則重新確認」：每期每家再保人天數獨立填寫，fixture 明確填 r1，讓本段只測分配。
        allocation_row={"performanceMonth":"2026-03","paymentBaseDate":"2026-03-01","reinsurerPaymentTerms":{"r1":90}}
        allocation_blanks=(None,""," \t\n","　","\ufeff")
        for structure in ("QS","XOL"):
            allocation_base={**original_payload,"reinsuranceStructure":structure,"underlyingLimits":"Primary","installmentEnabled":True,"paymentTermsDays":90}
            rows=[allocation_row,{**allocation_row,"paymentBaseDate":"2026-06-01"}]
            for premium in allocation_blanks:
                for ratio in allocation_blanks:
                    saved_rows=[{**r,"premium":premium,"ratio":ratio} for r in rows]
                    Case.objects.filter(pk=posted.pk).update(payload={**allocation_base,"performanceInstallments":saved_rows})
                    before=gen_audit(posted.case_uid).count()
                    response=docx(sales,kind="debit",caseUid=str(posted.case_uid),performanceInstallments=[{**allocation_row,"premium":1000,"ratio":100}],installmentEnabled=False)
                    check(f"Debit {structure}: all blank allocation {premium!r}/{ratio!r} blocked without request override/audit",response.status_code==409 and code(response)=="debit_installment_allocation_required" and message(response)=='Complete Premium or Ratio for every installment before generating a Debit Note.' and gen_audit(posted.case_uid).count()==before)
            for saved_rows in ([allocation_row],rows,[{**r,"premium":None} for r in rows],[{**r,"ratio":""} for r in rows]):
                Case.objects.filter(pk=posted.pk).update(payload={**allocation_base,"performanceInstallments":saved_rows})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: missing allocation fields and single/multiple rows blocked",response.status_code==409 and code(response)=="debit_installment_allocation_required")
                for kind in ("cover","endorsement"):
                    check(f"{kind} {structure}: no new installment allocation requirement",docx(sales,kind=kind,caseUid=str(posted.case_uid)).status_code==204)
            for key in ("premium","ratio"):
                for value in (1,"1",1.25," 1 ",50.25):
                    for index in (0,1):
                        saved_rows=[dict(r) for r in rows];saved_rows[index][key]=value;saved_rows[1-index]["ratio"]=50
                        Case.objects.filter(pk=posted.pk).update(payload={**allocation_base,"performanceInstallments":saved_rows})
                        check(f"Debit {structure}: every period allocated with saved {key}={value!r} at period {index+1} accepted",docx(sales,kind="debit",caseUid=str(posted.case_uid)).status_code==204)
            for enabled in (False,None,0,1,"true"):
                Case.objects.filter(pk=posted.pk).update(payload={**allocation_base,"installmentEnabled":enabled,"performanceInstallments":rows})
                check(f"Debit {structure}: allocation rule uses strict boolean flag {enabled!r}",docx(sales,kind="debit",caseUid=str(posted.case_uid)).status_code==204)
            Case.objects.filter(pk=posted.pk).update(payload={**allocation_base,"performanceInstallments":[{**allocation_row,"paymentBaseDate":""}]})
            response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
            check(f"Debit {structure}: existing base-date guard keeps priority",code(response)=="debit_installment_base_date_required")
            # 2026-10-16：Case 預設已不參與分期天數，改以移除逐期再保人天數觸發付款天數檢查，仍驗證其優先於分配檢查。
            Case.objects.filter(pk=posted.pk).update(payload={**allocation_base,"paymentTermsDays":None,"performanceInstallments":[{**r,"reinsurerPaymentTerms":{}} for r in rows]})
            response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
            check(f"Debit {structure}: existing payment-term guard keeps priority",code(response)=="debit_installment_payment_terms_required")
        for saved_rows in ([allocation_row],[{**allocation_row,"premium":None,"ratio":"　"}],[]):
            Case.objects.filter(pk=draft.pk).update(payload={"reinsuranceStructure":"TREATY","installmentEnabled":True,"performanceInstallments":saved_rows})
            for kind in ("cover","debit","endorsement"):
                check(f"Treaty Draft {kind}: blank allocation remains exempt",docx(sales,kind=kind,caseUid=str(draft.case_uid)).status_code==204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # A missing first, middle or final allocation blocks even when other periods are filled.
        for structure in ("QS","XOL"):
            each_allocation_base={**original_payload,"reinsuranceStructure":structure,"underlyingLimits":"Primary","installmentEnabled":True,"paymentTermsDays":90}
            # 2026-10-16：每期每家再保人天數獨立填寫，fixture 明確填 r1。
            complete_rows=[{"performanceMonth":month,"paymentBaseDate":day,"ratio":1,"reinsurerPaymentTerms":{"r1":90}} for month,day in (("2026-03","2026-03-01"),("2026-06","2026-06-01"),("2026-09","2026-09-01"))]
            for gap in range(3):
                for premium,ratio in ((None,None),("","　")):
                    saved_rows=[dict(r) for r in complete_rows];saved_rows[gap].update(premium=premium,ratio=ratio)
                    saved={**each_allocation_base,"performanceInstallments":saved_rows}
                    Case.objects.filter(pk=posted.pk).update(payload=saved)
                    before=gen_audit(posted.case_uid).count()
                    response=docx(sales,kind="debit",caseUid=str(posted.case_uid),performanceInstallments=complete_rows,installmentEnabled=False)
                    check(f"Debit {structure}: period {gap+1} blank allocation blocked without override/audit/data changes",response.status_code==409 and code(response)=="debit_installment_allocation_required" and message(response)=='Complete Premium or Ratio for every installment before generating a Debit Note.' and gen_audit(posted.case_uid).count()==before and Case.objects.get(pk=posted.pk).payload==saved)
            for kind in ("cover","endorsement"):
                check(f"{kind} {structure}: partial installment allocation remains outside scope",docx(sales,kind=kind,caseUid=str(posted.case_uid)).status_code==204)
            Case.objects.filter(pk=posted.pk).update(payload={**each_allocation_base,"originalPremium":0,"performanceInstallments":complete_rows})
            check(f"Debit {structure}: zero original premium with every ratio filled accepted",docx(sales,kind="debit",caseUid=str(posted.case_uid)).status_code==204)
            Case.objects.filter(pk=posted.pk).update(payload={**each_allocation_base,"performanceInstallments":[{**r,"premium":0,"ratio":None} for r in complete_rows]})
            response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
            check(f"Debit {structure}: explicit zero allocation for every period blocked",response.status_code==409 and code(response)=="debit_installment_allocation_positive_required")
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Effective installment weights must be positive, even when original premium is zero.
        positive_cases=[
            ({"premium":0,"ratio":50},False),({"premium":"0","ratio":50},False),
            ({"premium":-1,"ratio":50},False),({"premium":"-1","ratio":50},False),
            ({"premium":" \t\n","ratio":50},False),({"premium":False,"ratio":50},False),
            ({"premium":[],"ratio":50},False),({"ratio":0},False),({"ratio":"0"},False),
            ({"ratio":-1},False),({"ratio":"bad"},False),({"premium":"bad","ratio":0},False),
            ({"premium":1,"ratio":0},True),({"premium":0.01,"ratio":0},True),
            ({"premium":" 1 ","ratio":0},True),({"premium":None,"ratio":50},True),
            ({"premium":"","ratio":50},True),({"ratio":0.01},True),
            ({"premium":"bad","ratio":50},True),({"premium":{},"ratio":50},True),
        ]
        for structure in ("QS","XOL"):
            positive_base={**original_payload,"reinsuranceStructure":structure,"underlyingLimits":"Primary","installmentEnabled":True,"paymentTermsDays":90}
            # 2026-10-16：每期每家再保人天數獨立填寫，fixture 明確填 r1，讓本段只測正數分配。
            row_base={"performanceMonth":"2026-03","paymentBaseDate":"2026-03-01","reinsurerPaymentTerms":{"r1":90}}
            for original in (0,1000):
                for fields,valid in positive_cases:
                    saved_rows=[{**row_base,**fields},{**row_base,"paymentBaseDate":"2026-06-01","ratio":1}]
                    saved={**positive_base,"originalPremium":original,"performanceInstallments":saved_rows}
                    Case.objects.filter(pk=posted.pk).update(payload=saved)
                    before=gen_audit(posted.case_uid).count()
                    response=docx(sales,kind="debit",caseUid=str(posted.case_uid),performanceInstallments=[{**row_base,"premium":1000,"ratio":100}],originalPremium=1000,installmentEnabled=False)
                    if valid:
                        check(f"Debit {structure}: original={original}, effective positive {fields!r} accepted",response.status_code==204)
                    else:
                        check(f"Debit {structure}: original={original}, invalid effective allocation {fields!r} blocked without override/audit/data change",response.status_code==409 and code(response)=="debit_installment_allocation_positive_required" and message(response)=='Use a Premium or Ratio greater than 0 for every installment before generating a Debit Note.' and gen_audit(posted.case_uid).count()==before and Case.objects.get(pk=posted.pk).payload==saved)
            for gap in range(3):
                saved_rows=[{**row_base,"ratio":1} for _ in range(3)];saved_rows[gap]["ratio"]=0
                Case.objects.filter(pk=posted.pk).update(payload={**positive_base,"performanceInstallments":saved_rows})
                response=docx(sales,kind="debit",caseUid=str(posted.case_uid))
                check(f"Debit {structure}: zero effective weight at period {gap+1} blocked",response.status_code==409 and code(response)=="debit_installment_allocation_positive_required")
            for kind in ("cover","endorsement"):
                check(f"{kind} {structure}: no new positive allocation requirement",docx(sales,kind=kind,caseUid=str(posted.case_uid)).status_code==204)
            Case.objects.filter(pk=posted.pk).update(payload={**positive_base,"installmentEnabled":False,"performanceInstallments":[{**row_base,"premium":0}]})
            check(f"Debit {structure}: non-installment zero rows outside scope",docx(sales,kind="debit",caseUid=str(posted.case_uid)).status_code==204)
        for fields,valid in positive_cases[:12]:
            Case.objects.filter(pk=draft.pk).update(payload={"reinsuranceStructure":"TREATY","installmentEnabled":True,"performanceInstallments":[{**row_base,**fields}]})
            check("Treaty Draft: non-positive installment allocation exempt",docx(sales,kind="debit",caseUid=str(draft.case_uid)).status_code==204)
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        # Treaty requirements are intentionally deferred, including reference/AE.
        Case.objects.filter(pk=draft.pk).update(payload={"reinsuranceStructure": "TREATY"})
        for kind in ("cover", "debit", "endorsement"):
            r = docx(sales, kind=kind, caseUid=str(draft.case_uid))
            check(f"Treaty draft {kind}: no reference or business fields -> 204", r.status_code == 204)
        Case.objects.filter(pk=posted.pk).update(payload={"reinsuranceStructure": "QS"})
        r = docx(sales, kind="cover", caseUid=str(posted.case_uid), reinsuranceStructure="TREATY")
        check("request Treaty flag cannot bypass stored QS requirements", r.status_code == 409 and code(r) == "reinsured_required")
        Case.objects.filter(pk=posted.pk).update(payload=original_payload)
        Case.objects.filter(pk=draft.pk).update(payload=original_draft_payload)
        # Existing Endorsement draft/blank-field behavior is retained.
        r = docx(sales, kind="endorsement", caseUid=str(draft.case_uid))
        check("Endorsement Word on draft retains existing availability", r.status_code == 204)
        for fmt in ("pdf", "", "xlsx", None):
            before = gen_audit(posted.case_uid).count()
            r = call(sales, "post", "/api/document-generation-log", {"format": fmt, "kind": "cover", "caseUid": str(posted.case_uid)})
            check(f"format {fmt!r} is rejected without audit", r.status_code == 400 and code(r) == "invalid_document_format" and gen_audit(posted.case_uid).count() == before)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ DOC").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Doc Insured").count())
