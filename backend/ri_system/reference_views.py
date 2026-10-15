"""Shared reference downloads and append-only template uploads.

Template content and metadata live together in the backed-up document volume;
an atomic metadata write publishes each complete upload to the shared list.
Release manuals are versioned with the application image.
"""
import hashlib
import logging
import fcntl
import re
from contextlib import contextmanager
import io
import json
import uuid
import zipfile
from pathlib import Path

from django.http import FileResponse
from django.utils import timezone
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from cases import storage
from cases.documents import content_disposition, safe_filename, storable_text
from .authz import NoStoreMixin, RIPermission, AuthError, object_body

log = logging.getLogger(__name__)
MAX_BYTES = 10 * 1024 * 1024
MANUALS = {
    'mdm': 'MDM_主檔管理說明.docx',
    'schema': 'Schema_資料庫結構說明.docx',
    'swiss-pd': 'Swiss_Re_Asia_Facility_PD_Rules_2026-10-14.docx',
    'auw-accounting': 'AUW_Facility_Rules_2026-10-14.docx',
}
OFFICE = {
    'docx': ('word/document.xml', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    'dotx': ('word/document.xml', 'application/vnd.openxmlformats-officedocument.wordprocessingml.template'),
    'xlsx': ('xl/workbook.xml', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    'xltx': ('xl/workbook.xml', 'application/vnd.openxmlformats-officedocument.spreadsheetml.template'),
    'pptx': ('ppt/presentation.xml', 'application/vnd.openxmlformats-officedocument.presentationml.presentation'),
}


def validated_type(filename, data):
    ext = Path(filename).suffix.lower().lstrip('.')
    if ext == 'pdf' and data.startswith(b'%PDF-'):
        return 'application/pdf'
    if ext in OFFICE:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                if '[Content_Types].xml' in names and OFFICE[ext][0] in names:
                    return OFFICE[ext][1]
        except (zipfile.BadZipFile, ValueError):
            pass
    return None


MANUAL_DOWNLOAD_NAMES = {
    'mdm': 'MDM_Master_Data_Management.docx',
    'schema': 'Schema_Database_Structure.docx',
    'swiss-pd': 'Swiss_Re_Asia_Facility_PD_Rules_2026-10-14.docx',
    'auw-accounting': 'AUW Facility 專屬規則_2026-10-14.docx',
}


MANUAL_RELEASE_DATES = {'mdm': '2026-10-13', 'schema': '2026-10-13', 'auw-accounting': '2026-10-14', 'swiss-pd': '2026-10-14'}

def manual_row(key):
    return {'id': key, 'filename': MANUAL_DOWNLOAD_NAMES[key], 'release_date': MANUAL_RELEASE_DATES[key], 'kind': 'manual'}


def target(values):
    manual = values.get('manual')
    if manual is not None:
        if not isinstance(manual, str) or manual not in MANUALS:
            raise AuthError(404, 'reference_not_found', 'System guide not found.')
        return 'manual-' + manual, manual
    try:
        canonical = str(uuid.UUID(str(values.get('fileId', ''))))
    except ValueError:
        raise AuthError(404, 'reference_not_found', 'Document template not found.')
    return canonical, None


def read_row(key, manual=None):
    try:
        with storage.open_read(f'system-reference/{key}.json') as metadata:
            return json.load(metadata)
    except FileNotFoundError:
        if manual:
            return manual_row(manual)
        raise AuthError(404, 'reference_not_found', 'Document template not found.')


@contextmanager
def locked(key):
    # Cross-worker locking prevents rename/delete/restore from losing each other's changes.
    path = storage.path_for(f'system-reference/.locks/{key}.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write_row(key, row):
    storage.put(f'system-reference/{key}.json', json.dumps(row, ensure_ascii=False).encode('utf-8'))


class SystemReferenceView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {method: 'accounts.manage' for method in ('GET', 'POST', 'PATCH', 'DELETE')}
    parser_classes = [MultiPartParser, JSONParser]

    def get(self, request):
        if 'manual' in request.query_params or 'fileId' in request.query_params:
            key, manual = target(request.query_params)
            row = read_row(key, manual)
            if row.get('deleted_at'):
                raise AuthError(404, 'reference_in_trash', 'This file is in the Recycle Bin. Restore it before downloading.')
            try:
                handle = (open(Path(__file__).parent / 'reference_documents' / MANUALS[manual], 'rb')
                          if manual else storage.open_read(f'system-reference/{key}.bin'))
            except FileNotFoundError:
                raise AuthError(404, 'reference_content_missing', 'File content is missing. Contact the System Administrator.')
            response = FileResponse(handle, content_type=OFFICE['docx'][1] if manual else row['content_type'])
            response['Content-Disposition'] = content_disposition(row['filename'])
            return response
        directory = storage.path_for('system-reference')
        rows, unreadable = [], 0
        if directory.exists():
            for path in directory.glob('*.json'):
                if not path.name.startswith('manual-'):
                    # 2026-10-14：單一損壞的中繼資料只略過該檔，不讓整個清單失敗
                    try:
                        row = json.loads(path.read_text(encoding='utf-8'))
                        if not isinstance(row, dict) or not row.get('id') or not row.get('uploaded_at') or not row.get('filename'):
                            raise ValueError('incomplete metadata')
                    except (ValueError, OSError, UnicodeDecodeError):
                        log.warning('System Reference metadata %s is unreadable; skipped', path.name)
                        unreadable += 1
                        continue
                    rows.append({**row, 'kind': 'template'})
        rows.sort(key=lambda row: (str(row['uploaded_at']), str(row['id'])), reverse=True)
        manuals = [read_row('manual-' + key, key) for key in MANUALS]
        trash = [row for row in rows + manuals if row.get('deleted_at')]
        trash.sort(key=lambda row: str(row['deleted_at']), reverse=True)
        return Response({'unreadable': unreadable, 'files': [row for row in rows if not row.get('deleted_at')],
                         'manuals': [row for row in manuals if not row.get('deleted_at')], 'trash': trash})

    def patch(self, request):
        body = object_body(request)
        key, manual = target(body)
        action = body.get('action')
        if action not in ('rename', 'restore'):
            raise AuthError(400, 'invalid_action', 'Choose Rename or Restore.')
        with locked(key):
            row = read_row(key, manual)
            if action == 'rename':
                if row.get('deleted_at'):
                    raise AuthError(409, 'reference_in_trash', 'Restore this file before renaming it.')
                name = body.get('name')
                if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160 or re.search(r'[\x00-\x1f\x7f/\\]', name):
                    raise AuthError(400, 'invalid_filename', 'The name must contain 1 to 160 characters without slashes or control characters.')
                row['filename'] = storable_text(name.strip()) + Path(row['filename']).suffix
            else:
                if not row.get('deleted_at'):
                    raise AuthError(409, 'reference_not_in_trash', 'This file is not in the Recycle Bin.')
                row.pop('deleted_at', None)
                row.pop('deleted_by', None)
            row['updated_at'] = timezone.now().isoformat()
            row['updated_by'] = request.ri_principal.name
            write_row(key, row)
        return Response({'file': row})

    def delete(self, request):
        key, manual = target(request.query_params)
        with locked(key):
            row = read_row(key, manual)
            if not row.get('deleted_at'):
                row['deleted_at'] = timezone.now().isoformat()
                row['deleted_by'] = request.ri_principal.name
                write_row(key, row)
        return Response({'file': row})

    def post(self, request):
        upload = request.FILES.get('file')
        if not upload or upload.size < 1 or upload.size > MAX_BYTES:
            return Response({'message': 'Select a nonempty file no larger than 10 MB.'}, status=413)
        filename = storable_text(safe_filename(upload.name))
        data = upload.read(MAX_BYTES + 1)
        content_type = validated_type(filename, data)
        if len(data) > MAX_BYTES or not content_type:
            return Response({'message': 'Upload a DOCX, DOTX, XLSX, XLTX, PPTX or PDF file whose content matches its extension.'}, status=415)
        file_id = str(uuid.uuid4())
        row = {'id': file_id, 'filename': filename, 'content_type': content_type,
               'byte_size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
               'uploaded_at': timezone.now().isoformat(), 'uploaded_by': request.ri_principal.name, 'kind': 'template'}
        content_key = f'system-reference/{file_id}.bin'
        try:
            storage.put(content_key, data)
            storage.put(f'system-reference/{file_id}.json', json.dumps(row, ensure_ascii=False).encode('utf-8'))
        except BaseException:
            storage.delete(content_key)
            raise
        return Response({'file': row}, status=201)
