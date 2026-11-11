"""Read cached XLSX values only. Never execute formulas, load comments or pivots.

Formula text is kept as plain text (2026-11-11) so simple rate formulas such as ROUND(U4*0.15,0)
can be recognised; it is never evaluated."""
import hashlib
import posixpath
import re
import zipfile
from datetime import datetime, timedelta
from io import BytesIO
from xml.etree import ElementTree as ET

T = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
MAX_BYTES = 30 * 1024 * 1024


def label(value):
    return ' '.join(str(value or '').split()).strip()


def date_value(value):
    if value in (None, '', 'N/A'):
        return ''
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()
    except (ValueError, OverflowError, TypeError):
        return str(value)


def read_workbook(content):
    if not 0 < len(content) <= MAX_BYTES:
        raise ValueError('Select a nonempty XLSX file no larger than 30 MiB.')
    try:
        archive = zipfile.ZipFile(BytesIO(content))
        if sum(x.file_size for x in archive.infolist()) > 300 * 1024 * 1024 or len(archive.infolist()) > 5000:
            raise ValueError('The expanded workbook is too large.')
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        props = workbook.find(T+'workbookPr')
        if props is not None and props.get('date1904') in ('1','true'):
            raise ValueError('Convert the workbook to the standard 1900 date system before importing.')
        rels = {x.get('Id'): x.get('Target') for x in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = list(workbook.find(T+'sheets'))
        sheet = next((x for x in sheets if x.get('name') == 'Facultative'), None)
        if sheet is None:
            raise ValueError('A Facultative worksheet is required.')
        target = rels[sheet.get(R+'id')]
        path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(n.text or '' for n in e.iter(T+'t')) for e in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        header = None
        rows = []
        shared = {}
        for _, row in ET.iterparse(archive.open(path), events=('end',)):
            if row.tag != T+'row':
                continue
            cells = {}
            errors = []
            formulas = {}
            for cell in row.findall(T+'c'):
                col = re.sub(r'\d', '', cell.get('r',''))
                value = cell.find(T+'v')
                value = value.text if value is not None else None
                kind = cell.get('t')
                if kind == 's' and value is not None:
                    value = strings[int(value)]
                elif kind == 'inlineStr':
                    value = ''.join(n.text or '' for n in cell.iter(T+'t'))
                if kind == 'e' or cell.find(T+'f') is not None and value is None:
                    errors.append(cell.get('r'))
                if value is not None:
                    cells[col] = value
                f = cell.find(T+'f')
                if f is not None:
                    text = f.text
                    if f.get('t') == 'shared':
                        if text: shared[f.get('si')] = text
                        else: text = shared.get(f.get('si'))
                    if text: formulas[col] = text[:500]
            if header is None and cells:
                header = {k: label(v) for k,v in cells.items()}
                if not {'流水號','TW Ref. No.','Currency','Class','Full-closed'}.issubset(set(header.values())):
                    raise ValueError('The Facultative worksheet has missing required headers.')
            elif cells:
                values = {header[k]:v for k,v in cells.items() if k in header}
                if values.get('流水號'):
                    rows.append(dict(row=int(row.get('r')), values=values, errors=errors,
                                     formulas={header[k]: v for k, v in formulas.items() if k in header}))
                    if len(rows) > 50000:
                        raise ValueError('A batch may contain at most 50,000 transactions.')
            row.clear()
        if not rows:
            raise ValueError('No transactions were found.')
        return dict(sha256=hashlib.sha256(content).hexdigest(), rows=rows)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError) as exc:
        raise ValueError('The XLSX workbook cannot be read.') from exc
