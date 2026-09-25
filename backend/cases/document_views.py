"""
案件文件 API - 對應 Hatchable Alpha 的 api/case-documents.js（含 #11）。

  GET    /api/case-documents?caseUid=…              documents.read   列表 + coverage + Signed Slip 提醒狀態
  GET    /api/case-documents?caseUid=…&fileId=…     documents.read   下載檔案
  POST   /api/case-documents                        documents.write  上傳 {caseUid, kind, filename, base64, reinsurers}
  PUT    /api/case-documents                        documents.write  勾選／取消勾選 {caseUid, fileId, selected}
  DELETE /api/case-documents?caseUid=…&fileId=…     documents.write  刪除（VM：只有 Draft 可以刪）

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - 單檔上限 10 MB（Alpha 5 MB）。
  - Announce 之後不能刪除文件（只能取消勾選），檔案保留作為證據；Draft 仍可刪。
  - signedSlipReminder.outboundEnabled 如實回報（依設定，VM 尚未設定寄信 → false）。
  - 資料庫有紀錄但檔案本體不見時，下載回 404 file_content_missing（Alpha 會是未處理的錯誤）。
"""
import hashlib
import logging
import re
import uuid

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from . import documents as docs
from . import storage
from .calc.jsnum import get, is_array, js_or, js_to_string, js_trim
from .calc.signed_slip import signed_slip_tracking
from .models import MAX_DOCUMENT_BYTES, Case, CaseDocument
from .views import visible_cases

logger = logging.getLogger(__name__)
DISPLAY_VERSION = "V 0.003"
MAX_DOCUMENTS_PER_CASE = 50
_FILE_ID = re.compile(r"[a-f0-9-]{36}\Z", re.I)
AUDIT_METADATA = {"displayVersion": DISPLAY_VERSION, "milestone": "case-documents"}


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


def file_row(document):
    """與 Alpha 的 COLUMNS 相同的欄位與命名（snake_case）。"""
    return {
        "id": str(document.pk), "kind": document.kind, "reinsurers": document.reinsurers,
        "filename": document.filename, "content_type": document.content_type, "byte_size": document.byte_size,
        "sha256": document.sha256, "is_selected": document.is_selected, "uploaded_by": document.uploaded_by,
        "uploaded_at": document.uploaded_at,
    }


def _rows(case):
    return [file_row(d) for d in CaseDocument.objects.filter(case=case).order_by("uploaded_at", "id")]


def _payload(case):
    return case.payload if isinstance(case.payload, dict) else {}


def _tracking(case, rows):
    result = signed_slip_tracking({**_payload(case), "status": case.status}, rows)
    result["outboundEnabled"] = settings.SIGNED_SLIP_OUTBOUND_ENABLED  # VM 如實回報
    return result


def _state(case, **extra):
    rows = _rows(case)
    return {"ok": True, **extra, "coverage": docs.coverage_for(_payload(case), rows),
            "signedSlipReminder": _tracking(case, rows)}


def _find_file(case, file_id, lock=False):
    try:
        pk = uuid.UUID(file_id)
    except ValueError:
        return None  # 例如 36 個「-」：格式檢查通過但不是 UUID
    qs = CaseDocument.objects.select_for_update() if lock else CaseDocument.objects
    return qs.filter(case=case, pk=pk).first()


class CaseDocumentsView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "documents.read", "POST": "documents.write", "PUT": "documents.write",
                      "DELETE": "documents.write"}

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "no-referrer"
        return response

    def _case(self, request, raw_uid):
        case_uid = js_trim(js_to_string(js_or(raw_uid, "")))
        if not case_uid:
            return None, _error(400, "case_uid_required", "Save and open a case before managing documents.")
        try:
            parsed = uuid.UUID(case_uid)
        except ValueError:
            parsed = None
        case = visible_cases(request.ri_principal).filter(case_uid=parsed).first() if parsed else None
        if case is None:
            return None, _error(404, "case_not_found", "Case was not found.")
        return case, None

    @staticmethod
    def _file_id(value):
        file_id = js_to_string(js_or(value, ""))
        return file_id if _FILE_ID.match(file_id) else None

    # ---- 列表 / 下載 ----
    def get(self, request):
        case, error = self._case(request, request.query_params.get("caseUid"))
        if error:
            return error
        if request.query_params.get("fileId"):
            file_id = self._file_id(request.query_params.get("fileId"))
            if file_id is None:
                return _error(400, "invalid_file_id", "Invalid file ID.")
            document = _find_file(case, file_id)
            if document is None:
                return _error(404, "file_not_found", "File was not found for this case.")
            try:
                handle = storage.open_read(document.storage_key)
            except FileNotFoundError:
                logger.error("case document %s has no stored file (%s)", document.pk, document.storage_key)
                return _error(404, "file_content_missing",
                              "The stored file for this document is missing. Contact the system administrator.")
            response = FileResponse(handle, content_type=document.content_type)
            response["Content-Disposition"] = docs.content_disposition(document.filename)
            return response
        return Response({**_state(case), "displayVersion": DISPLAY_VERSION, "files": _rows(case)})

    # ---- 勾選 ----
    def put(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        case, error = self._case(request, body.get("caseUid"))
        if error:
            return error
        file_id = self._file_id(body.get("fileId"))
        if file_id is None:
            return _error(400, "invalid_file_id", "Invalid file ID.")
        selected = body.get("selected") is True
        with transaction.atomic():
            document = _find_file(case, file_id, lock=True)
            if document is None:
                return _error(404, "file_not_found", "File was not found for this case.")
            before = document.is_selected
            document.is_selected = selected
            document.save(update_fields=["is_selected"])
            record_audit(entity_type="case_document", entity_id=case.case_uid, action="select_document",
                         before={"id": file_id, "isSelected": before}, after={"id": file_id, "isSelected": selected},
                         actor=actor_from(request.ri_principal), request_id=request_id_from(request),
                         metadata=AUDIT_METADATA)
        return Response(_state(case, file=file_row(document)))

    # ---- 刪除（VM：只有 Draft）----
    def delete(self, request):
        case, error = self._case(request, request.query_params.get("caseUid"))
        if error:
            return error
        file_id = self._file_id(request.query_params.get("fileId"))
        if file_id is None:
            return _error(400, "invalid_file_id", "Invalid file ID.")
        with transaction.atomic():
            locked_case = Case.objects.select_for_update().get(pk=case.pk)
            document = _find_file(locked_case, file_id, lock=True)
            if document is None:
                return _error(404, "file_not_found", "File was not found for this case.")
            if locked_case.status != "draft":
                return _error(409, "document_delete_locked",
                              "Documents cannot be deleted after Announce. Deselect the document instead.")
            existing = {**file_row(document), "storage_key": document.storage_key}
            key = document.storage_key
            document.delete()
            record_audit(entity_type="case_document", entity_id=case.case_uid, action="delete_document",
                         before=existing, after=None, actor=actor_from(request.ri_principal),
                         request_id=request_id_from(request),
                         metadata={**AUDIT_METADATA, "filename": existing["filename"]})
            # 資料庫的刪除與稽核一起成功之後，才刪檔案本體；刪檔失敗最多留下一個孤兒檔，不會變成「刪了卻沒有紀錄」
            transaction.on_commit(lambda: _delete_quietly(key))
        return Response(_state(case, deleted=True))

    # ---- 上傳 ----
    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        case, error = self._case(request, body.get("caseUid"))
        if error:
            return error
        kind = body.get("kind")
        if kind not in ("offer", "signed", "confirmation"):
            return _error(400, "invalid_document_kind",
                          "Choose Offer Slip, Reinsurer Signed Slip or Reinsurer Confirmation E-mail.")
        filename = docs.safe_filename(body.get("filename"))
        decoded = docs.decode_and_validate(filename, body.get("base64"), MAX_DOCUMENT_BYTES)
        if "error" in decoded:
            return _error(decoded["error"][0], "invalid_file", decoded["error"][1])
        allowed = docs.required_reinsurers(_payload(case))
        supplied = body.get("reinsurers")
        names = [] if kind == "offer" else list(dict.fromkeys(
            k for k in (docs.reinsurer_key(v) for v in (supplied if is_array(supplied) else [])) if k))
        if kind != "offer" and (not names or any(name not in allowed for name in names)):
            return _error(400, "reinsurer_mapping_required", "Select the reinsurer(s) covered by this evidence.")

        filename = docs.storable_text(filename)
        data = decoded["bytes"]
        file_id = uuid.uuid4()
        storage_key = f"case-documents/{case.case_uid}/{file_id}.{decoded['ext']}"
        actor = actor_from(request.ri_principal)
        written = False
        try:
            with transaction.atomic():
                Case.objects.select_for_update().filter(pk=case.pk).first()  # 同一個案件的上傳依序處理（50 份上限）
                if CaseDocument.objects.filter(case=case).count() >= MAX_DOCUMENTS_PER_CASE:
                    return _error(400, "document_limit", "This case already has 50 stored documents.")
                storage.put(storage_key, data)
                written = True
                document = CaseDocument.objects.create(
                    id=file_id, case=case, kind=kind, reinsurers=names, filename=filename,
                    content_type=decoded["contentType"], byte_size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(), storage_key=storage_key,
                    is_selected=True, uploaded_by=actor["id"],
                )
                after = {"id": str(file_id), "kind": kind, "reinsurers": names, "filename": filename,
                         "contentType": decoded["contentType"], "byteSize": len(data),
                         "sha256": document.sha256, "isSelected": True, "uploadedBy": actor["id"]}
                record_audit(entity_type="case_document", entity_id=case.case_uid, action="upload_document",
                             before=None, after=after, actor=actor, request_id=request_id_from(request),
                             metadata={**AUDIT_METADATA, "filename": filename, "kind": kind})
        except BaseException:
            # 檔案已寫入，但資料庫的紀錄或稽核沒有成功（含提交失敗）：刪掉檔案，不留下沒有紀錄的孤兒檔
            if written:
                _delete_quietly(storage_key)
            raise
        return Response(_state(case, file=file_row(document)), status=201)


def _delete_quietly(storage_key):
    try:
        storage.delete(storage_key)
    except OSError:
        logger.exception("could not delete stored document %s (orphaned file left behind)", storage_key)

