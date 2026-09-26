"""
產生 Cover Note／Debit Note／Endorsement - 對應 Hatchable Alpha 的 api/render-document-pdf.js。

Word（.docx）與 PDF 的版面都在瀏覽器端組好（Alpha 的 docx-generator.js／pdf-generator.js 原樣照搬）：
  POST /api/render-document-pdf         documents.read   {markup, kind, caseUid} → A4 PDF
       Alpha 用 Hatchable 內建的無頭 Chromium；VM 送到內部的 Gotenberg（Chromium，見 compose.yaml 的 pdf 服務）。
  POST /api/document-generation-log     documents.read   {kind, format: "docx", caseUid} → 204
       Word 完全在瀏覽器產生，伺服器看不到；前端下載 Word 之前先呼叫這裡寫 Audit（2026-09-26 你的決定）。

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - 需要 documents.read（Alpha 只要登入）。
  - kind 必須是 cover／endorsement／debit，caseUid 必填且必須是看得到的案件（Alpha 只有 debit 才帶 caseUid）；
    每次成功產生都寫一筆 generate_document Audit（Alpha 不記錄；不存文件內容）。
  - Debit Note 的 Word 也在伺服器檢查已有 TW Ref（Alpha 的 Word 路徑只有前端擋）。
"""
import logging
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from .calc.jsnum import get, is_nullish, js_to_string, js_trim
from .document_markup import markup_problem
from .document_views import visible_cases

log = logging.getLogger(__name__)

KINDS = ("cover", "endorsement", "debit")
DOCUMENT_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page { size: 794px 1123px; margin: 0; }
  html, body { margin: 0; padding: 0; background: #fff; }
  .page { break-after: page; page-break-after: always; }
  .page:last-child { break-after: auto; page-break-after: auto; }
</style>
</head>
<body>%s</body>
</html>"""


def _error(status, code, message):
    return Response({"error": code, "message": message}, status=status)


def _text(body, key):
    value = get(body, key)
    return js_trim("" if is_nullish(value) else js_to_string(value))


def _find_case(request, case_uid):
    """Alpha：case_uid::text = $1 AND recycled_at IS NULL AND is_archived = false（文字比對，所以大寫的 UUID 對不到）。"""
    try:
        parsed = uuid.UUID(case_uid)
    except ValueError:
        return None
    if str(parsed) != case_uid:
        return None
    return visible_cases(request.ri_principal).filter(case_uid=parsed, recycled_at__isnull=True, is_archived=False).first()


def _check_case(request, body):
    """回傳 (case, 錯誤回應)。"""
    kind = _text(body, "kind")
    if kind not in KINDS:
        return None, kind, _error(400, "invalid_document_kind", "Document kind must be cover, endorsement or debit.")
    case_uid = _text(body, "caseUid")
    if not case_uid:
        if kind == "debit":
            return None, kind, _error(400, "case_uid_required", "caseUid is required to render a Debit Note.")
        return None, kind, _error(400, "case_uid_required", "caseUid is required to generate a document.")
    case = _find_case(request, case_uid)
    if kind == "debit" and (case is None or not case.tw_ref):
        return None, kind, _error(409, "debit_requires_tw_ref", "Debit Note is only available after Announce assigns a TW Reference.")
    if case is None:
        return None, kind, _error(404, "case_not_found", "Case was not found.")
    return case, kind, None


def _audit(request, case, kind, fmt):
    with transaction.atomic():   # 專案規則：Audit 一律在交易內寫入（audit.services._guard）
        record_audit(entity_type="case", entity_id=case.case_uid, action="generate_document",
                     after={"kind": kind, "format": fmt, "twRef": case.tw_ref, "rowVersion": case.row_version},
                     actor=actor_from(request.ri_principal), request_id=request_id_from(request),
                     metadata={"kind": kind, "format": fmt})


def _multipart(fields, files):
    boundary = f"----ri-{uuid.uuid4().hex}"
    out = bytearray()
    for name, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    for name, (filename, data, content_type) in files.items():
        out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n").encode() + data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def render_pdf(document_html):
    """
    Alpha：browser.pdf(url, { format: "A4", printBackground: true })。
    Gotenberg 的紙張以英吋計：A4 = 8.27 × 11.7；邊界預設 0.39 英吋，要明確設成 0（版面本身就是 794×1123 px 的絕對定位）。
    """
    body, content_type = _multipart(
        {"paperWidth": "8.27", "paperHeight": "11.7", "marginTop": "0", "marginBottom": "0", "marginLeft": "0",
         "marginRight": "0", "printBackground": "true", "preferCssPageSize": "false"},
        {"files": ("index.html", document_html.encode("utf-8"), "text/html; charset=utf-8")})
    req = urllib.request.Request(f"{settings.PDF_RENDERER_URL.rstrip('/')}/forms/chromium/convert/html", data=body,
                                 method="POST", headers={"Content-Type": content_type})
    with urllib.request.urlopen(req, timeout=settings.PDF_RENDERER_TIMEOUT) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF-"):
        raise ValueError("renderer did not return a PDF")
    return data


class RenderDocumentPdfView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"POST": "documents.read"}

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        markup = body.get("markup")
        problem = markup_problem(markup)
        if problem:
            return _error(*problem)
        case, kind, err = _check_case(request, body)
        if err:
            return err
        try:
            pdf = render_pdf(DOCUMENT_HTML % markup)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            log.error("Document PDF rendering failed: %s", exc)
            return _error(500, "pdf_render_failed", "Unable to render PDF.")
        _audit(request, case, kind, "pdf")
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Cache-Control"] = "no-store"
        return response


class DocumentGenerationLogView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"POST": "documents.read"}

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        if _text(body, "format") != "docx":
            return _error(400, "invalid_document_format", "Only Word (docx) generation is logged here; PDF is logged when it is rendered.")
        case, kind, err = _check_case(request, body)
        if err:
            return err
        if kind == "endorsement":
            return _error(400, "invalid_document_kind", "Endorsement is generated as PDF only.")
        _audit(request, case, kind, "docx")
        return Response(status=204)
