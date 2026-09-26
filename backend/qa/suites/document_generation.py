import json
import re
import uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client, override_settings
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
             reinsurers=[dict(name="ZZ Re A", sharePct=100, premium=1000, riCommPct=5, taxPct=0)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make_case(c, status="posted"):
    r = call(c, "post", "/api/cases", {"case": ready()}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
    if status != "draft":
        _ref[0] += 1
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-DOC-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case

JPEG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
def page(text): return f'<div class="page" style="position:relative;width:794px;height:1123px"><img class="logo" src="{JPEG}" /><p>{text}</p></div>'
STYLE = "<style>*{box-sizing:border-box}body{margin:0;font-family:Arial,\"Liberation Sans\",\"Noto Sans CJK TC\",sans-serif}</style>"
MARKUP = STYLE + page("ZZ page one 晶華") + page("ZZ page two")
def pdf(c, **body): return call(c, "post", "/api/render-document-pdf", {"markup": MARKUP, **body})
def docx(c, **body): return call(c, "post", "/api/document-generation-log", {"format": "docx", **body})
def gen_audit(uid): return AuditLog.objects.filter(entity_type="case", entity_id=str(uid), action="generate_document")
def pages(data): return len(re.findall(rb"/Type\s*/Page(?!s)", data))

try:
    with transaction.atomic():
        adm_p, sales_p, gm_p = person("admin", "admin"), person("sales", "reinsurance"), person("general_manager", "reinsurance")
        fin_p, view_p = person("accounting", "finance"), person("viewer", "business_1")
        admin, sales, gm, fin, viewer = account(adm_p, "admin"), account(sales_p, "sales"), account(gm_p, "gm"), account(fin_p, "fin"), account(view_p, "view")
        draft, posted = make_case(sales, "draft"), make_case(sales, "posted")
        recycled = make_case(sales, "draft"); Case.objects.filter(pk=recycled.pk).update(recycled_at=timezone.now())
        archived = make_case(sales, "posted"); Case.objects.filter(pk=archived.pk).update(is_archived=True, archived_at=timezone.now(), archived_by="t")

        # ================= 權限 =================
        check("anonymous -> 401", call(new_client(), "post", "/api/render-document-pdf", {"markup": MARKUP}).status_code == 401)
        for label, c in (("finance staff", fin), ("viewer", viewer)):
            check(f"{label}: no documents.read -> PDF 403 and Word log 403",
                  pdf(c, kind="cover", caseUid=str(posted.case_uid)).status_code == 403 and docx(c, kind="cover", caseUid=str(posted.case_uid)).status_code == 403)
        check("GET is not allowed (403 before method dispatch)", call(sales, "get", "/api/render-document-pdf").status_code == 403)

        # ================= markup 檢查（與 Alpha 相同的順序與訊息；逐字比對在差異測試） =================
        for label, body, status, msg in (
            ("markup missing", {}, 400, "PDF markup is required."),
            ("markup whitespace only (JavaScript trim, incl. U+FEFF)", {"markup": " ﻿　\n"}, 400, "PDF markup is required."),
            ("markup not a string", {"markup": ["<p>"]}, 400, "PDF markup is required."),
            ("markup over 2,000,000 UTF-16 units (emoji = 2)", {"markup": "a" * 1_999_999 + "😀"}, 413, "PDF markup is too large."),
            ("<script>", {"markup": MARKUP + "<script>x</script>"}, 400, "PDF markup contains unsupported content."),
            ("event handler", {"markup": MARKUP + '<p onmouseover="x">'}, 400, "PDF markup contains unsupported content."),
            ("javascript: URI", {"markup": MARKUP + '<a href="javascript:x">'}, 400, "PDF markup contains unsupported content."),
            ("css url()", {"markup": MARKUP + '<p style="background:url(http://x)">'}, 400, "PDF markup contains unsupported content."),
            ("non-JPEG image", {"markup": MARKUP + '<img src="data:image/png;base64,iVBOR">'}, 400, "PDF markup contains unsupported content."),
            ("remote image", {"markup": MARKUP + "<img src='http://192.168.1.127/x.jpg'>"}, 400, "PDF markup contains unsupported content."),
        ):
            r = call(sales, "post", "/api/render-document-pdf", {**body, "kind": "cover", "caseUid": str(posted.case_uid)})
            check(f"{label} -> {status}", r.status_code == status and message(r) == msg, (r.status_code, message(r)))
        check("markup errors are checked before the case (Alpha order): bad markup + unknown case -> 400 markup",
              code(call(sales, "post", "/api/render-document-pdf", {"markup": "", "kind": "debit"})) == "markup_required")

        # ================= kind／caseUid =================
        r = pdf(sales, kind="invoice", caseUid=str(posted.case_uid)); check("unknown kind -> 400", r.status_code == 400 and code(r) == "invalid_document_kind")
        r = pdf(sales, kind="debit"); check("debit without caseUid -> 400 with Alpha's message", r.status_code == 400 and message(r) == "caseUid is required to render a Debit Note.")
        r = pdf(sales, kind="cover"); check("cover without caseUid -> 400 (VM: every PDF names its case)", r.status_code == 400 and code(r) == "case_uid_required")
        r = pdf(sales, kind="cover", caseUid=str(uuid.uuid4())); check("unknown case -> 404", r.status_code == 404 and code(r) == "case_not_found")
        r = pdf(sales, kind="cover", caseUid=str(posted.case_uid).upper()); check("upper-case UUID does not match (Alpha compares text) -> 404", r.status_code == 404)
        r = pdf(sales, kind="cover", caseUid="not-a-uuid"); check("malformed caseUid -> 404", r.status_code == 404)
        r = pdf(sales, kind="debit", caseUid=str(draft.case_uid))
        check("Debit Note PDF for a Draft (no TW Ref) -> 409 with Alpha's message", r.status_code == 409 and message(r) == "Debit Note is only available after Announce assigns a TW Reference.", r.content[:200])
        r = pdf(sales, kind="debit", caseUid=str(archived.case_uid)); check("Debit Note for an archived case (has TW Ref) -> 409 (Alpha: is_archived = false)", r.status_code == 409)
        r = pdf(sales, kind="cover", caseUid=str(archived.case_uid)); check("cover for an archived case -> 404", r.status_code == 404)
        r = pdf(sales, kind="cover", caseUid=str(recycled.case_uid)); check("cover for a recycled draft -> 404", r.status_code == 404)
        check("no audit written for any rejected request", not AuditLog.objects.filter(action="generate_document", actor_id=f"personnel:{sales_p.pk}").exists())

        # ================= 成功（真的經過 Gotenberg） =================
        before = gen_audit(draft.case_uid).count()
        r = pdf(sales, kind="cover", caseUid=str(draft.case_uid))
        data = b"".join(r.streaming_content) if getattr(r, "streaming", False) else r.content
        check("cover PDF for a Draft -> 200 application/pdf", r.status_code == 200 and r["Content-Type"] == "application/pdf", (r.status_code, data[:200]))
        check("response is a real PDF with 2 A4 pages", data.startswith(b"%PDF-") and pages(data) == 2 and b"MediaBox [0 0 595.91998 842.88]" in data, (data[:8], pages(data)))
        check("Cache-Control no-store", "no-store" in r.get("Cache-Control", ""))
        a = gen_audit(draft.case_uid).order_by("-id").first()
        check("audit generate_document (pdf, cover) with the actor", gen_audit(draft.case_uid).count() == before + 1 and a.metadata == {"kind": "cover", "format": "pdf"}
              and a.actor_id == f"personnel:{sales_p.pk}" and a.after_data["format"] == "pdf" and "markup" not in json.dumps(a.after_data), a and (a.metadata, a.after_data))
        for label, c in (("general manager", gm), ("admin", admin)):
            check(f"{label} (documents.read) can render", pdf(c, kind="endorsement", caseUid=str(posted.case_uid)).status_code == 200)
        r = pdf(sales, kind="debit", caseUid=str(posted.case_uid)); check("Debit Note PDF after Announce -> 200", r.status_code == 200 and r.content.startswith(b"%PDF-"))
        with override_settings(PDF_RENDERER_URL="http://127.0.0.1:9"):
            n = gen_audit(posted.case_uid).count()
            r = pdf(sales, kind="cover", caseUid=str(posted.case_uid))
            check("renderer unreachable -> 500 'Unable to render PDF.' and no audit", r.status_code == 500 and message(r) == "Unable to render PDF." and gen_audit(posted.case_uid).count() == n)

        # ================= Word 的 Audit =================
        r = docx(sales, kind="cover", caseUid=str(draft.case_uid))
        a = gen_audit(draft.case_uid).order_by("-id").first()
        check("Word cover log -> 204 and audit (docx, cover)", r.status_code == 204 and a.metadata == {"kind": "cover", "format": "docx"})
        r = docx(sales, kind="debit", caseUid=str(draft.case_uid)); check("Word Debit Note for a Draft -> 409 (VM: enforced on the server too)", r.status_code == 409)
        r = docx(sales, kind="debit", caseUid=str(posted.case_uid)); check("Word Debit Note after Announce -> 204", r.status_code == 204)
        r = docx(sales, kind="endorsement", caseUid=str(posted.case_uid)); check("Word Endorsement -> 400 (PDF only)", r.status_code == 400)
        r = call(sales, "post", "/api/document-generation-log", {"format": "pdf", "kind": "cover", "caseUid": str(posted.case_uid)})
        check("log with format pdf -> 400 (PDF is logged when rendered)", r.status_code == 400 and code(r) == "invalid_document_format")
        r = docx(sales, kind="cover", caseUid=str(uuid.uuid4())); check("Word log for an unknown case -> 404", r.status_code == 404)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ DOC").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Doc Insured").count())
