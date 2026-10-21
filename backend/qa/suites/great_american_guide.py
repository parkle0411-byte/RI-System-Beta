"""Download the v2.2 peer guide without creating shared document metadata."""
import hashlib,os,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as E
from django.test import override_settings
from rest_framework.test import APIRequestFactory
from ri_system.reference_views import SystemReferenceView,MANUALS
assert os.environ.get('RI_DISPOSABLE_QA')=='true'
key='great-american-questionnaire'
checks=[]
def check(name,ok):
 assert ok,name
 checks.append(name);print('PASS '+name,flush=True)
factory=APIRequestFactory()
with tempfile.TemporaryDirectory() as folder,override_settings(CASE_DOCUMENT_ROOT=folder):
 def get(query='',role='admin'):
  principal=SimpleNamespace(pk=0,name='Read-only guide verification',role_code=role,must_change_password=False)
  with patch('ri_system.authz.load_principal',return_value=principal),patch('ri_system.authz.is_supervisor',return_value=False):
   return SystemReferenceView.as_view()(factory.get('/api/system-reference'+query))
 listing=get();check('guide list remains available',listing.status_code==200)
 row=next(r for r in listing.data['manuals'] if r['id']==key)
 check('same guide entry exposes v2.2',row['filename']=='Great American Facility Property 結算規則摘要及同仁覆核問卷_v2.2_2026-10-20.docx')
 for ident,filename in MANUALS.items():
  response=get('?manual='+ident);check('guide download '+ident,response.status_code==200)
  data=b''.join(response.streaming_content);response.close()
  check('exact guide bytes '+ident,data==(Path('/app/ri_system/reference_documents')/filename).read_bytes())
  if ident==key:
   check('Word mime type preserved',response['Content-Type']=='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
   with ZipFile(Path('/app/ri_system/reference_documents')/filename) as archive:
    xml=E.fromstring(archive.read('word/document.xml'))
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main';w14='http://schemas.microsoft.com/office/word/2010/wordml'
    text=''.join(t.text or '' for t in xml.iter('{'+w+'}t'))
    check('manual per-case/period registration stated','逐案／逐期登記' in text and '相同的外部系統參考號' in text)
    check('obsolete merge question removed','同期限能否合併' not in text and '尚待確認' not in text)
    controls=list(xml.iter('{'+w+'}sdtPr'));check('52 native controls retained',len(controls)==52)
    boxes=list(xml.iter('{'+w14+'}checked'));check('40 choices remain unchecked',len(boxes)==40 and all(c.get('{'+w14+'}val')=='0' for c in boxes))
    check('all8 review questions retained',all(('GAR-'+str(i).zfill(2)) in text for i in range(1,9)))
 check('existing guide permission preserved',get('?manual='+key,'sales').status_code==403)
 check('anonymous guide access rejected',SystemReferenceView.as_view()(factory.get('/api/system-reference?manual='+key)).status_code==401)
 check('read-only checks write no metadata',not list(Path(folder).rglob('*.json')))
print(f'{len(checks)}/{len(checks)} Great American guide checks passed',flush=True)
