"""Store generated QS Word versions without changing placement evidence."""
import hashlib
import uuid

from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from . import documents as docs, storage
from .document_generation_views import _check_case
from .document_views import _delete_quietly, _error, file_row
from .models import MAX_DOCUMENT_BYTES, Case, CaseDocument
from .qs_documents import GENERATED_KINDS, scope


def generated_state(case):
    """Version history is separate from the manually uploaded evidence list."""
    latest, history = [], []
    for kind in GENERATED_KINDS:
        records = list(CaseDocument.objects.filter(case=case, kind=kind).order_by("uploaded_at", "id"))
        for index, record in enumerate(records):
            row = {**file_row(record), "version": index + 1, "is_latest": index == len(records) - 1,
                   "generation_kind": "cover" if kind == "generated_cover" else "debit"}
            (latest if row["is_latest"] else history).append(row)
    return {"generatedFiles": latest, "generatedHistory": history}


class GeneratedCaseDocumentView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"POST": "documents.write"}

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        case, kind, error = _check_case(request, body)
        if error is not None:
            return error
        if not scope(case.payload, kind):
            return _error(400, "generated_document_scope", "Automatic Word saving is available for QS Property Cover Note and Debit Note.")
        try:
            file_id = uuid.UUID(str(body.get("generationId", "")))
        except (TypeError, ValueError, AttributeError):
            return _error(400, "generation_id_required", "Generate a new Word document before saving it.")
        if type(body.get("rowVersion")) is not int or body.get("rowVersion") != case.row_version:
            return _error(409, "document_case_changed", "The case changed. Refresh it and generate the Word document again.")
        filename = docs.safe_filename(body.get("filename"))
        if not filename.lower().endswith(".docx"):
            return _error(415, "invalid_file", "Generated files must be Word (.docx) documents.")
        decoded = docs.decode_and_validate(filename, body.get("base64"), MAX_DOCUMENT_BYTES)
        if "error" in decoded:
            return _error(decoded["error"][0], "invalid_file", decoded["error"][1])
        filename = docs.storable_text(filename)
        content = decoded["bytes"]
        digest = hashlib.sha256(content).hexdigest()
        stored_kind = "generated_" + kind
        storage_key = f"case-documents/{case.case_uid}/{file_id}.docx"
        actor = actor_from(request.ri_principal)
        written = False
        try:
            with transaction.atomic():
                locked = Case.objects.select_for_update().get(pk=case.pk)
                # Recheck access/status/data after taking the same Case lock as uploads.
                case, _, error = _check_case(request, body)
                if error is not None:
                    return error
                if not scope(locked.payload, kind) or body.get("rowVersion") != locked.row_version:
                    return _error(409, "document_case_changed", "The case changed. Refresh it and generate the Word document again.")
                existing = CaseDocument.objects.filter(pk=file_id).first()
                if existing is not None:
                    if existing.case_id != locked.pk or existing.kind != stored_kind or existing.sha256 != digest or existing.filename != filename:
                        return _error(409, "generation_id_conflict", "Generate a new Word document before saving it.")
                    if not storage.exists(existing.storage_key):
                        return _error(409, "generated_content_missing", "The saved document is unavailable. Generate it again or contact the system administrator.")
                    return Response({"ok": True, "file": file_row(existing), **generated_state(locked)})
                # Generated Word and all history are intentionally outside the manual 50-file cap.
                storage.put(storage_key, content)
                written = True
                document = CaseDocument.objects.create(
                    id=file_id, case=locked, kind=stored_kind, reinsurers=[],
                    filename=filename, content_type=decoded["contentType"], byte_size=len(content),
                    sha256=digest, storage_key=storage_key, is_selected=False, uploaded_by=actor["id"])
                record_audit(entity_type="case_document", entity_id=locked.case_uid,
                             action="generate_and_store_document", before=None,
                             after={"id": str(document.pk), "kind": kind, "filename": filename,
                                    "sha256": digest, "rowVersion": locked.row_version,
                                    "uploadedAt": document.uploaded_at.isoformat()},
                             actor=actor, request_id=request_id_from(request),
                             metadata={"kind": kind, "format": "docx", "source": "generated_qs_word"})
        except BaseException:
            if written:
                _delete_quietly(storage_key)
            raise
        return Response({"ok": True, "file": file_row(document), **generated_state(locked)}, status=201)
