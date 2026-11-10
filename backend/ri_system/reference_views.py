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
    'insured-list': 'Insured_List_2026-11-03.xlsx',
    'mdm': 'MDM_主檔管理說明.docx',
    'schema': 'Schema_資料庫結構說明.docx',
    'swiss-pd': 'Swiss_Re_Facility_PD_Exclusive_Rules_2026-10-29.docx',
    'qbe-pd': 'QBE_Facility_PD_Exclusive_Rules_2026-10-29.docx',
    'swiss-cgl': 'Swiss_Re_Facility_CGL_Exclusive_Rules_2026-10-29.docx',
    'auw-accounting': 'Syndicate_609_AUW_Facility_PD_Exclusive_Rules_2026-10-29.docx',
    'great-american-questionnaire': 'Great_American_Facility_PD_Exclusive_Rules_2026-10-29.docx',
    'allianz-questionnaire': 'Allianz_Facility_PD_Exclusive_Rules_2026-10-30.docx',
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
    'insured-list': 'Insured 清單_2026-11-03.xlsx',
    'mdm': 'MDM_Master_Data_Management.docx',
    'schema': 'Schema_Database_Structure.docx',
    'swiss-pd': 'Swiss Re Facility - PD 專屬規則_2026-10-29.docx',
    'qbe-pd': 'QBE Facility - PD 專屬規則.docx',
    'swiss-cgl': 'Swiss Re Facility - CGL 專屬規則_2026-10-29.docx',
    'auw-accounting': 'Syndicate 609 AUW Facility - PD 專屬規則.docx',
    'great-american-questionnaire': 'Great American Facility - PD 專屬規則_2026-10-29.docx',
    'allianz-questionnaire': 'Allianz Facility - PD 專屬規則_2026-10-30.docx',
}


MANUAL_RELEASE_DATES = {'insured-list': '2026-11-03', 'mdm': '2026-11-02', 'schema': '2026-11-02', 'auw-accounting': '2026-10-29', 'swiss-cgl': '2026-10-29', 'swiss-pd': '2026-10-29', 'qbe-pd': '2026-10-29', 'great-american-questionnaire': '2026-10-29', 'allianz-questionnaire': '2026-10-30'}

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


def reference_rows():
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
    return rows, manuals, trash, unreadable


def read_order(category):
    try:
        with storage.open_read(f'system-reference/.orders/{category}.json') as handle:
            ids = json.load(handle)
        if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids) or len(ids) != len(set(ids)):
            raise ValueError('invalid order')
        return ids
    except FileNotFoundError:
        return []
    except (ValueError, OSError, UnicodeDecodeError):
        raise AuthError(503, 'reference_order_unreadable', 'The saved order could not be read. Contact the System Administrator.')


def ordered_rows(category, rows):
    ranks = {key: index for index, key in enumerate(read_order(category))}
    return sorted(rows, key=lambda row: ranks.get(row['id'], len(ranks)))


def order_version(rows):
    return hashlib.sha256(json.dumps([row['id'] for row in rows]).encode()).hexdigest()


def reorder(body):
    category = body.get('category')
    ids = body.get('ids')
    if category not in ('files', 'manuals') or not isinstance(ids, list) or any(not isinstance(key, str) for key in ids) or len(ids) != len(set(ids)):
        raise AuthError(400, 'invalid_reference_order', 'Choose a category and provide each file ID exactly once.')
    with locked('order-' + category):
        files, manuals, _, _ = reference_rows()
        rows = ordered_rows(category, [row for row in (manuals if category == 'manuals' else files) if not row.get('deleted_at')])
        if body.get('orderVersion') != order_version(rows) or set(ids) != {row['id'] for row in rows}:
            raise AuthError(409, 'reference_order_conflict', 'The list changed. Reload and try ordering it again.')
        # Keep deleted entries in their existing slots so Restore retains their position.
        old = read_order(category)
        remaining = iter(ids)
        merged = [next(remaining) if key in ids else key for key in old]
        merged.extend(remaining)
        storage.put(f'system-reference/.orders/{category}.json', json.dumps(merged).encode())
    return Response({'orderVersion': order_version([{'id': key} for key in ids])})


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
            response = FileResponse(handle, content_type=OFFICE[Path(MANUALS[manual]).suffix.lstrip('.')][1] if manual else row['content_type'])
            response['Content-Disposition'] = content_disposition(row['filename'])
            return response
        rows, manuals, trash, unreadable = reference_rows()
        files = ordered_rows('files', [row for row in rows if not row.get('deleted_at')])
        manuals = ordered_rows('manuals', [row for row in manuals if not row.get('deleted_at')])
        return Response({'unreadable': unreadable, 'files': files, 'manuals': manuals, 'trash': trash,
                         'orderVersions': {'files': order_version(files), 'manuals': order_version(manuals)}})

    def patch(self, request):
        body = object_body(request)
        action = body.get('action')
        if action == 'reorder':
            return reorder(body)
        key, manual = target(body)
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
