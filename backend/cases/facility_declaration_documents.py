"""Upload and read evidence belonging to a Facility Declaration."""
import hashlib
import uuid

from django.http import FileResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, request_id_from
from coordination.services import PRODUCTION_SOURCES, serialized
from ri_system.authz import NoStoreMixin, RIPermission, actor_from
from . import documents, storage
from .facility_declaration_views import error, parsed
from .models import FacilityDeclaration, FacilityDeclarationDocument, MAX_DOCUMENT_BYTES
from .views import visible_cases


def file_row(row):
    return {'id': str(row.pk), 'filename': row.filename, 'contentType': row.content_type,
            'byteSize': row.byte_size, 'sha256': row.sha256, 'uploadedAt': row.uploaded_at}


class FacilityDeclarationDocumentsView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'GET': 'documents.read', 'POST': 'documents.write'}

    def lookup(self, request, facility_uid, declaration_uid):
        facility_uid, declaration_uid = parsed(facility_uid), parsed(declaration_uid)
        if not facility_uid or not declaration_uid:
            return None
        return FacilityDeclaration.objects.select_related('facility').filter(
            declaration_uid=declaration_uid, facility__in=visible_cases(request.ri_principal).filter(
                case_uid=facility_uid, reinsurance_structure='FACILITY')).first()

    def get(self, request):
        declaration = self.lookup(request, request.query_params.get('facilityUid'), request.query_params.get('declarationUid'))
        if not declaration:
            return error(404, 'declaration_not_found', 'Declaration was not found.')
        file_id = request.query_params.get('fileId')
        if not file_id:
            return Response({'ok': True, 'files': [file_row(x) for x in declaration.documents.order_by('uploaded_at', 'id')]})
        uid = parsed(file_id)
        document = declaration.documents.filter(pk=uid).first() if uid else None
        if not document:
            return error(404, 'document_not_found', 'Document was not found.')
        try:
            handle = storage.open_read(document.storage_key)
        except FileNotFoundError:
            return error(404, 'file_content_missing', 'Document content is unavailable.')
        response = FileResponse(handle, content_type=document.content_type)
        response['Content-Disposition'] = documents.content_disposition(document.filename)
        response['X-Content-Type-Options'] = 'nosniff'
        return response

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        declaration = self.lookup(request, body.get('facilityUid'), body.get('declarationUid'))
        if not declaration:
            return error(404, 'declaration_not_found', 'Declaration was not found.')
        name = documents.safe_filename(body.get('filename'))
        decoded = documents.decode_and_validate(name, body.get('base64'), MAX_DOCUMENT_BYTES)
        if 'error' in decoded:
            return error(decoded['error'][0], 'invalid_file', decoded['error'][1])
        file_id = uuid.uuid4()
        key = f'facility-declarations/{declaration.declaration_uid}/{file_id}.{decoded["ext"]}'
        actor = actor_from(request.ri_principal)
        written = False
        try:
            with serialized(PRODUCTION_SOURCES):
                declaration = FacilityDeclaration.objects.select_for_update().get(pk=declaration.pk)
                if declaration.status != 'draft':
                    return error(409, 'declaration_not_draft', 'Evidence can be added to a Draft Declaration only.')
                if declaration.documents.count() >= 50:
                    return error(400, 'document_limit', 'A Declaration can contain at most 50 documents.')
                storage.put(key, decoded['bytes'])
                written = True
                row = FacilityDeclarationDocument.objects.create(
                    id=file_id, declaration=declaration, filename=documents.storable_text(name),
                    content_type=decoded['contentType'], byte_size=len(decoded['bytes']),
                    sha256=hashlib.sha256(decoded['bytes']).hexdigest(), storage_key=key, uploaded_by=actor['id'])
                record_audit(entity_type='facility_declaration', entity_id=declaration.declaration_uid,
                             action='upload_document', after=file_row(row), actor=actor,
                             request_id=request_id_from(request))
        except BaseException:
            if written:
                storage.delete(key)
            raise
        return Response({'ok': True, 'file': file_row(row)}, status=201)
