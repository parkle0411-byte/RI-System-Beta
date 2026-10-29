"""Download the current PD exclusive-rules guide without creating shared document metadata."""
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
 check('same guide entry exposes latest PD rules',row['filename']=='Great American Facility - PD 專屬規則_2026-10-29.docx')
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
    check('PD scope stated','Great American Insurance Company, Singapore Branch (Facility)' in text and 'Property' in text)
    check('current quarter rules stated','Q＋80' in text and 'Q＋90' in text and 'B＋75' in text and 'B＋90' in text)
    codes=['EX-GRATIA','FOLLOW_FORTUNES','LMA3100','LMA5018','LMA5019','LMA5393','LMA5411','LPO438','NMA1622','NMA2919','NMA2962','PROP_FAC']
    check('all12 mapped PD clauses listed',all(c in text for c in codes))
    check('leap-year example retained','2028/03/30' in text)
    check('formal guide replaces peer questionnaire','GAR-01' not in text and '第7、14、21天' not in text)
 check('existing guide permission preserved',get('?manual='+key,'sales').status_code==403)
 check('anonymous guide access rejected',SystemReferenceView.as_view()(factory.get('/api/system-reference?manual='+key)).status_code==401)
 check('read-only checks write no metadata',not list(Path(folder).rglob('*.json')))
print(f'{len(checks)}/{len(checks)} Great American guide checks passed',flush=True)
