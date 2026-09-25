import base64
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client, TestCase, override_settings
from audit.models import AuditLog
from cases import document_views, storage
from cases.models import MAX_DOCUMENT_BYTES, Case, CaseDocument
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=f"ZZ DOC {role} {_seq[0]}", department=dept, role_code=role, created_by="t", updated_by="t", **kw)
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

PDF = b"%PDF-1.7\nzz synthetic test file\n"
PNG = bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"zz"
def b64(data): return base64.b64encode(data).decode()
def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="DOC", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Cedant", originalInsured="ZZ Doc Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b

ROOT = tempfile.mkdtemp(prefix="ri-doc-test-")
REAL_ROOT = settings.CASE_DOCUMENT_ROOT
def count_files(root):
    return sum(len(files) for _, _, files in os.walk(root)) if os.path.isdir(root) else -1
real_before = count_files(REAL_ROOT)

try:
    with override_settings(CASE_DOCUMENT_ROOT=ROOT), transaction.atomic():
        sales_p, gm_p, view_p, acct_p = person("sales", "reinsurance"), person("general_manager", "reinsurance"), person("viewer", "business_1"), person("accounting", "finance")
        sales, gm, viewer, acct = account(sales_p, "sales"), account(gm_p, "gm"), account(view_p, "view"), account(acct_p, "acct")
        r = call(sales, "post", "/api/cases", {"case": ready()}); assert r.status_code == 201, r.content
        case = Case.objects.get(case_uid=r.json()["case"]["caseUid"]); uid = str(case.case_uid)
        def upload(c=sales, **over):
            body = {"caseUid": uid, "kind": "offer", "filename": "offer.pdf", "base64": b64(PDF), "reinsurers": []}
            body.update(over); return call(c, "post", "/api/case-documents", body)
        def listing(c=sales, u=None): return call(c, "get", f"/api/case-documents?caseUid={u or uid}")

        # --- 權限與案件 ---
        check("anonymous -> 401", call(new_client(), "get", f"/api/case-documents?caseUid={uid}").status_code == 401)
        check("viewer (no documents.read) -> 403", listing(viewer).status_code == 403)
        check("accounting -> 403", listing(acct).status_code == 403 and upload(acct).status_code == 403)
        check("General Manager may read but not upload", listing(gm).status_code == 200 and upload(gm).status_code == 403)
        check("no caseUid -> 400 case_uid_required", code(call(sales, "get", "/api/case-documents")) == "case_uid_required" and code(upload(caseUid="")) == "case_uid_required")
        check("unknown / malformed case -> 404", code(listing(u=str(uuid.uuid4()))) == "case_not_found" and code(listing(u="nope")) == "case_not_found")

        # --- 上傳 ---
        audits = AuditLog.objects.count()
        r = upload(); j = r.json(); f = j.get("file", {})
        check("upload an Offer Slip -> 201", r.status_code == 201, (r.status_code, r.content[:200]))
        check("file row has exactly Alpha's columns (snake_case)", set(f) == {"id", "kind", "reinsurers", "filename", "content_type", "byte_size", "sha256", "is_selected", "uploaded_by", "uploaded_at"}, sorted(f))
        doc = CaseDocument.objects.get(pk=f["id"])
        check("row: kind, size, sha256, content type, selected, uploader, no reinsurers for an offer",
              f["kind"] == "offer" and f["byte_size"] == len(PDF) and f["sha256"] == hashlib.sha256(PDF).hexdigest() and f["content_type"] == "application/pdf"
              and f["is_selected"] is True and f["uploaded_by"] == f"personnel:{sales_p.pk}" and f["reinsurers"] == [])
        check("storage key = case-documents/<caseUid>/<fileId>.pdf", doc.storage_key == f"case-documents/{uid}/{doc.pk}.pdf")
        stored = os.path.join(ROOT, doc.storage_key)
        check("the file is stored with exactly the uploaded bytes", os.path.isfile(stored) and open(stored, "rb").read() == PDF)
        check("no temporary files left beside it", [n for n in os.listdir(os.path.dirname(stored)) if n.endswith(".tmp")] == [])
        a = AuditLog.objects.filter(entity_type="case_document", entity_id=uid, action="upload_document").first()
        check("audit upload_document: after has id/kind/sha256/size, metadata filename+kind", a and a.before_data is None and a.after_data["id"] == str(doc.pk)
              and a.after_data["sha256"] == doc.sha256 and a.after_data["byteSize"] == len(PDF) and a.metadata == {"displayVersion": "V 0.003", "milestone": "case-documents", "filename": "offer.pdf", "kind": "offer"}
              and AuditLog.objects.count() == audits + 1)
        check("response carries coverage + signedSlipReminder", "coverage" in j and "signedSlipReminder" in j and j["coverage"]["offer"] is True)
        r = upload(kind="offer", reinsurers=["ZZ Re A"]); check("an offer ignores the reinsurers list", r.status_code == 201 and r.json()["file"]["reinsurers"] == [])

        # 再保人對應（與 Alpha 相同：文件頁的名稱「不」去掉 (Facility)）
        r = upload(kind="signed", filename="a.pdf", reinsurers=["  zz   RE a ", "ZZ Re A"])
        check("signed slip: names normalised and de-duplicated", r.status_code == 201 and r.json()["file"]["reinsurers"] == ["zz re a"], r.content[:200])
        r = upload(kind="confirmation", filename="b.pdf", reinsurers=["ZZ Re B (Facility)"]); check("confirmation for 'ZZ Re B (Facility)' matches the case's reinsurer name", r.status_code == 201, r.content[:200])
        r = upload(kind="signed", reinsurers=["ZZ Re B"]); check("'ZZ Re B' without the Facility tag is not a case reinsurer here (same as Alpha) -> 400", code(r) == "reinsurer_mapping_required")
        check("signed slip with no reinsurers -> 400 reinsurer_mapping_required", code(upload(kind="signed", reinsurers=[])) == "reinsurer_mapping_required" and code(upload(kind="signed", reinsurers="ZZ Re A")) == "reinsurer_mapping_required")
        check("an unknown reinsurer -> 400", code(upload(kind="signed", reinsurers=["ZZ Re A", "Somebody"])) == "reinsurer_mapping_required")

        # 檔案驗證
        before_files = count_files(ROOT); before_rows = CaseDocument.objects.count()
        for label, over, status, msg in [
            ("bad kind", dict(kind="slip"), 400, None), ("extension not allowed", dict(filename="a.exe"), 415, "Use PDF, DOCX, PNG, JPG, EML or MSG."),
            ("content does not match the extension", dict(filename="a.png"), 415, "File content does not match its extension."),
            ("not base64", dict(base64="%%%"), 400, "Invalid file encoding."), ("empty", dict(base64=""), 413, "Each file must be nonempty and no larger than 10 MB."),
            ("base64 not a string", dict(base64=5), 413, None), ("missing filename", dict(filename=None), 415, None)]:
            r = upload(**over)
            check(f"reject: {label} -> {status}", r.status_code == status and (msg is None or r.json()["message"] == msg), (r.status_code, r.content[:120]))
        check("rejected uploads stored nothing", count_files(ROOT) == before_files and CaseDocument.objects.count() == before_rows)
        for name, data, ctype in [("p.PNG", PNG, "image/png"), ("j.jpeg", bytes([255, 216, 255]) + b"x", "image/jpeg"), ("m.eml", b"x\r\nFrom: a@b.c\r\n", "message/rfc822"),
                                  ("o.msg", bytes([208, 207, 17, 224, 161, 177, 26, 225]) + b"x", "application/vnd.ms-outlook"),
                                  ("w.docx", bytes([80, 75, 3, 4]) + b"[Content_Types].xml word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]:
            r = upload(filename=name, base64=b64(data)); check(f"accept {name} as {ctype}", r.status_code == 201 and r.json()["file"]["content_type"] == ctype, r.content[:150])
        r = upload(filename="a/b\\c\x01.pdf"); check("filename: slashes and control characters replaced by _", r.status_code == 201 and r.json()["file"]["filename"] == "a_b_c_.pdf")
        r = upload(filename="報" * 178 + "😀.pdf"); check("a name longer than 180 UTF-16 units loses its extension -> 415 (same as Alpha)", r.status_code == 415)
        r = upload(filename="報" * 174 + "😀.pdf"); fn = r.json()["file"]["filename"] if r.status_code == 201 else None
        check("a name that fits (emoji included) is kept intact", fn == "報" * 174 + "😀.pdf", (r.status_code, r.content[:120]))
        r = upload(filename="a\ud83db.pdf"); fn = r.json()["file"]["filename"] if r.status_code == 201 else None
        check("a lone surrogate sent in JSON is stored as U+FFFD (as Node/PostgreSQL would), not a server error", fn == "a\ufffdb.pdf", (r.status_code, r.content[:120]))

        # 大小上限 10 MB（Alpha 5 MB）
        big = b"%PDF-" + b"0" * (MAX_DOCUMENT_BYTES - 5)
        r = upload(filename="big.pdf", base64=b64(big)); check("exactly 10 MB -> 201", r.status_code == 201 and r.json()["file"]["byte_size"] == MAX_DOCUMENT_BYTES, (r.status_code, r.content[:120]))
        r = upload(filename="big.pdf", base64=b64(big + b"0")); check("10 MB + 1 byte -> 413 'Maximum file size is 10 MB.'", r.status_code == 413 and r.json()["message"] == "Maximum file size is 10 MB.", (r.status_code, r.content[:120]))
        r = upload(filename="big.pdf", base64="A" * (-(-MAX_DOCUMENT_BYTES // 3) * 4 + 12)); check("base64 longer than the limit -> 413 before decoding", r.status_code == 413 and "no larger than 10 MB" in r.json()["message"])
        check("5 MB < size <= 10 MB is accepted (Alpha would refuse)", upload(filename="mid.pdf", base64=b64(b"%PDF-" + b"1" * (6 * 1024 * 1024))).status_code == 201)

        # 列表與涵蓋
        j = listing().json()
        check("list: ok, displayVersion, files ordered by upload time", j["ok"] is True and j["displayVersion"] == "V 0.003" and [x["uploaded_at"] for x in j["files"]] == sorted(x["uploaded_at"] for x in j["files"]))
        cov = j["coverage"]
        check("coverage: required keeps the Facility tag, both reinsurers covered, ready", cov["required"] == ["zz re a", "zz re b (facility)"] and cov["covered"] == cov["required"] and cov["missing"] == [] and cov["ready"] is True and cov["offer"] is True, cov)
        check("coverage.selected lists every selected file id in list order", cov["selected"] == [x["id"] for x in j["files"] if x["is_selected"]])
        s = j["signedSlipReminder"]
        check("signed slip reminder: B only has a confirmation e-mail, so it is still missing a SIGNED slip", s["missing"] == ["zz re b (facility)"] and s["complete"] is False and s["eligibleStatus"] is False and s["due"] is False)
        check("signed slip reminder: outboundEnabled reported truthfully (false), today is Taipei date, cadence 7, first reminder = effective + 60 days",
              s["outboundEnabled"] is False and len(s["today"]) == 10 and s["cadenceDays"] == 7 and s["firstReminderOn"] == "2026-04-30", s)

        # 下載
        r = sales.get(f"/api/case-documents?caseUid={uid}&fileId={doc.pk}")
        body = b"".join(r.streaming_content) if r.status_code == 200 else b""
        check("download -> the exact bytes with content type", r.status_code == 200 and body == PDF and r["Content-Type"] == "application/pdf", r.status_code)
        check("download headers: attachment, no-store, nosniff, no-referrer", r["Content-Disposition"] == "attachment; filename=document; filename*=UTF-8''offer.pdf"
              and r["Cache-Control"] == "no-store, max-age=0" and r["X-Content-Type-Options"] == "nosniff" and r["Referrer-Policy"] == "no-referrer")
        uni = CaseDocument.objects.get(filename="報" * 174 + "😀.pdf")
        r = gm.get(f"/api/case-documents?caseUid={uid}&fileId={uni.pk}")
        check("download (GM): non-ASCII names percent-encoded like encodeURIComponent", r.status_code == 200 and r["Content-Disposition"] == "attachment; filename=document; filename*=UTF-8''" + "%E5%A0%B1" * 174 + "%F0%9F%98%80.pdf")
        q = CaseDocument.objects.get(filename="a_b_c_.pdf"); CaseDocument.objects.filter(pk=q.pk).update(filename="it's (1) ~ok!*.pdf")
        r = sales.get(f"/api/case-documents?caseUid={uid}&fileId={q.pk}"); check("apostrophe encoded as %27; ( ) ~ ! * kept", r["Content-Disposition"].endswith("UTF-8''it%27s%20(1)%20~ok!*.pdf"), r.get("Content-Disposition"))
        check("download: bad fileId -> 400 invalid_file_id", code(sales.get(f"/api/case-documents?caseUid={uid}&fileId=../../etc/passwd")) == "invalid_file_id")
        check("download: 36 dashes pass the format check but are not a UUID -> 404", code(sales.get(f"/api/case-documents?caseUid={uid}&fileId={'-' * 36}")) == "file_not_found")
        other = Case.objects.get(case_uid=call(sales, "post", "/api/cases", {"case": ready()}).json()["case"]["caseUid"])
        check("download: a file of another case -> 404", code(sales.get(f"/api/case-documents?caseUid={other.case_uid}&fileId={doc.pk}")) == "file_not_found")
        lost = CaseDocument.objects.get(filename="p.PNG"); os.remove(os.path.join(ROOT, lost.storage_key))
        r = sales.get(f"/api/case-documents?caseUid={uid}&fileId={lost.pk}"); check("download: file missing on disk -> 404 file_content_missing (not a crash)", r.status_code == 404 and code(r) == "file_content_missing")

        # 勾選
        r = call(sales, "put", "/api/case-documents", {"caseUid": uid, "fileId": str(doc.pk), "selected": False})
        check("deselect -> 200, row updated, coverage no longer has the offer", r.status_code == 200 and r.json()["file"]["is_selected"] is False and not CaseDocument.objects.get(pk=doc.pk).is_selected
              and r.json()["coverage"]["offer"] is True)  # 另有第二份 offer
        a = AuditLog.objects.filter(entity_type="case_document", entity_id=uid, action="select_document").first()
        check("audit select_document before/after", a and a.before_data == {"id": str(doc.pk), "isSelected": True} and a.after_data == {"id": str(doc.pk), "isSelected": False})
        r = call(sales, "put", "/api/case-documents", {"caseUid": uid, "fileId": str(doc.pk), "selected": "true"}); check("selected must be boolean true (the string stays unselected)", r.json()["file"]["is_selected"] is False)
        check("select: unknown file -> 404, bad id -> 400, GM -> 403",
              code(call(sales, "put", "/api/case-documents", {"caseUid": uid, "fileId": str(uuid.uuid4()), "selected": True})) == "file_not_found"
              and code(call(sales, "put", "/api/case-documents", {"caseUid": uid, "fileId": "x", "selected": True})) == "invalid_file_id"
              and call(gm, "put", "/api/case-documents", {"caseUid": uid, "fileId": str(doc.pk), "selected": True}).status_code == 403)

        # 刪除：Draft 可以
        victim = CaseDocument.objects.get(filename="j.jpeg"); vpath = os.path.join(ROOT, victim.storage_key)
        with TestCase.captureOnCommitCallbacks(execute=True):
            r = call(sales, "delete", f"/api/case-documents?caseUid={uid}&fileId={victim.pk}")
        check("delete in Draft -> 200 deleted, row gone", r.status_code == 200 and r.json()["deleted"] is True and not CaseDocument.objects.filter(pk=victim.pk).exists(), r.content[:150])
        check("...the stored file is removed after the commit", not os.path.exists(vpath))
        a = AuditLog.objects.filter(entity_type="case_document", entity_id=uid, action="delete_document").first()
        check("audit delete_document keeps the whole row incl. storage_key and sha256", a and a.after_data is None and a.before_data["storage_key"] == victim.storage_key and a.before_data["sha256"] == victim.sha256 and a.metadata["filename"] == "j.jpeg")
        check("delete: bad id 400, unknown 404", code(call(sales, "delete", f"/api/case-documents?caseUid={uid}&fileId=zz")) == "invalid_file_id" and code(call(sales, "delete", f"/api/case-documents?caseUid={uid}&fileId={uuid.uuid4()}")) == "file_not_found")

        # Announce：用 API 上傳的文件走完整流程
        ids = sorted(x["id"] for x in listing().json()["files"] if x["is_selected"])
        r = call(sales, "post", "/api/case-announce", {"caseUid": uid, "rowVersion": Case.objects.get(pk=case.pk).row_version, "confirmed": True, "documentIds": ids})
        check("announce with documents uploaded through the API -> 200", r.status_code == 200, r.content[:250])

        # 刪除：Announce 之後不行（VM 規則），只能取消勾選
        keep = CaseDocument.objects.get(filename="w.docx"); kpath = os.path.join(ROOT, keep.storage_key); n = AuditLog.objects.count()
        with TestCase.captureOnCommitCallbacks(execute=True):
            r = call(sales, "delete", f"/api/case-documents?caseUid={uid}&fileId={keep.pk}")
        check("delete after Announce -> 409 document_delete_locked; row, file and audit untouched", r.status_code == 409 and code(r) == "document_delete_locked"
              and CaseDocument.objects.filter(pk=keep.pk).exists() and os.path.exists(kpath) and AuditLog.objects.count() == n, r.content[:150])
        r = call(sales, "put", "/api/case-documents", {"caseUid": uid, "fileId": str(keep.pk), "selected": False}); check("...but it can still be deselected", r.status_code == 200)
        check("signed slip reminder is now eligible (posted)", listing().json()["signedSlipReminder"]["eligibleStatus"] is True)
        check("upload is still allowed after Announce (same as Alpha)", upload(filename="late.pdf").status_code == 201)

        # 上傳時資料庫那一半失敗：檔案要被清掉
        real_audit = document_views.record_audit
        document_views.record_audit = lambda **k: (_ for _ in ()).throw(RuntimeError("audit down"))
        try:
            before_files = count_files(ROOT); before_rows = CaseDocument.objects.count()
            r = upload(filename="fail.pdf")
        finally:
            document_views.record_audit = real_audit
        check("audit failure -> 500, no row and no stored file left behind", r.status_code == 500 and CaseDocument.objects.count() == before_rows and count_files(ROOT) == before_files, (r.status_code, count_files(ROOT), before_files))

        # 50 份上限
        have = CaseDocument.objects.filter(case=other).count()
        for i in range(50 - have):
            CaseDocument.objects.create(case=other, kind="offer", filename=f"f{i}.pdf", content_type="application/pdf", byte_size=1, sha256="0" * 64, storage_key=f"zz-limit-{uuid.uuid4()}", uploaded_by="t")
        r = upload(caseUid=str(other.case_uid)); check("51st document -> 400 document_limit", r.status_code == 400 and code(r) == "document_limit")

        # 回收桶／封存的案件：不能再看或管理文件
        gone = Case.objects.get(case_uid=call(sales, "post", "/api/cases", {"case": ready()}).json()["case"]["caseUid"])
        check("before recycling the case, its documents can be listed", listing(u=str(gone.case_uid)).status_code == 200)
        Case.objects.filter(pk=gone.pk).update(recycled_at="2026-01-01T00:00:00Z", recycled_by="t")
        check("recycled case -> list 404, upload 404", code(listing(u=str(gone.case_uid))) == "case_not_found" and code(upload(caseUid=str(gone.case_uid))) == "case_not_found")
        Case.objects.filter(pk=gone.pk).update(recycled_at=None, recycled_by=None, status="posted", is_archived=True, archived_by="t", archived_at="2026-01-01T00:00:00Z")
        check("archived case -> 404", code(listing(u=str(gone.case_uid))) == "case_not_found")

        # 存放位置的防護
        try:
            storage.path_for("../../etc/passwd"); check("storage refuses keys outside the root", False)
        except storage.StorageError:
            check("storage refuses keys outside the root", True)
        raise Rollback()
except Rollback:
    pass
finally:
    shutil.rmtree(ROOT, ignore_errors=True)
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Doc Insured").count(),
      "| real document volume untouched:", count_files(REAL_ROOT) == real_before, "| temp root removed:", not os.path.exists(ROOT))
