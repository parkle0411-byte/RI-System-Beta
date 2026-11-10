"""Real uploads and Announce guards, each endorsement's own foreign broker note."""
from pathlib import Path
exec(Path('/app/qa/suites/oversea_business.py').read_text().split('try:\n with transaction.atomic():')[0])
import base64, tempfile
from django.test import override_settings
from cases.models import CaseDocument, ReferenceSequence
from cases import storage
from cases.documents import coverage_for as document_coverage
from cases.workflow import coverage_for as announce_coverage

def announce(client, case, ids):
 case.refresh_from_db()
 return call(client,'/api/case-announce',dict(caseUid=str(case.case_uid),rowVersion=case.row_version,confirmed=True,documentIds=ids))

def own_ids(client, case):
 return client.get('/api/case-documents?caseUid='+str(case.case_uid)).json()['coverage']['selected']

try:
 with tempfile.TemporaryDirectory() as directory, override_settings(CASE_DOCUMENT_ROOT=directory), transaction.atomic():
  sales,person=account('sales','sales')
  for typ,name,code in [('class','Fine Art','FA'),('foreign_broker','Oversea QA Broker',None),('reinsured','Oversea QA Cedant',None)]:MasterRecord.objects.create(entity_type=typ,name=name,code=code,payload={},created_by='qa',updated_by='qa')
  raw=fixture(currency="USD",ownerPersonnelId=person.pk,ae=person.name)
  created=call(sales,'/api/cases',{'case':raw});check('Draft can save without a note',created.status_code==201,created.content[:1000]);case=get_case(created.json()['case']['caseUid'])
  before_sequences=ReferenceSequence.objects.count()
  response=announce(sales,case,[]);check('direct API cannot Announce without broker note',response.status_code==400 and response.json()['error']=='documents_not_ready',response.content[:1000]);case.refresh_from_db()
  check('blocked Announce creates no ref, T3 or sequence',case.status=='draft' and not case.tw_ref and not case.payload['transactions'] and ReferenceSequence.objects.count()==before_sequences)
  wrong=call(sales,'/api/case-documents',dict(caseUid=str(case.case_uid),kind='broker_debit',filename='debit.pdf',base64=base64.b64encode(b'%PDF-1.4 note').decode()))
  check('Original cannot upload a Debit Note',wrong.status_code==400 and wrong.json()['error']=='invalid_document_kind')
  invalid=call(sales,'/api/case-documents',dict(caseUid=str(case.case_uid),kind='broker_credit',filename='credit.pdf',base64=base64.b64encode(b'not a pdf').decode()))
  check('invalid note content cannot satisfy upload',invalid.status_code==415 and not CaseDocument.objects.filter(case=case).exists())
  ids=upload_note(sales,case.case_uid);note=CaseDocument.objects.get(pk=ids[0]);check('real Credit Note upload needs no reinsurer mapping',note.kind=='broker_credit' and note.reinsurers==[] and storage.exists(note.storage_key))
  rows=[dict(id=str(note.pk),kind=note.kind,is_selected=True)]
  check('document and Announce coverage agree for credit note',document_coverage(case.payload,rows)['ready'] and announce_coverage(case.payload,rows)['ready'])
  check('ordinary evidence cannot satisfy broker note',not announce_coverage(case.payload,[dict(id='fake',kind='offer',is_selected=True)])['ready'])
  response=announce(sales,case,[]);check('changed review IDs are rejected',response.status_code==409 and response.json()['error']=='document_review_outdated')
  call(sales,'/api/case-documents',dict(caseUid=str(case.case_uid),fileId=str(note.pk),selected=False),method='put')
  response=announce(sales,case,ids);check('deselected note blocks Announce',response.status_code==400 and response.json()['error']=='documents_not_ready')
  call(sales,'/api/case-documents',dict(caseUid=str(case.case_uid),fileId=str(note.pk),selected=True),method='put')
  storage.delete(note.storage_key)
  response=announce(sales,case,ids);check('missing stored file blocks Announce despite metadata',response.status_code==400 and response.json()['error']=='documents_not_ready')
  check('document list exposes missing file readiness',not sales.get('/api/case-documents?caseUid='+str(case.case_uid)).json()['coverage']['ready'])
  response=sales.delete('/api/case-documents?caseUid='+str(case.case_uid)+'&fileId='+str(note.pk));check('Draft can delete and replace a note',response.status_code==200)
  ids=upload_note(sales,case.case_uid);response=announce(sales,case,ids);check('Original announces with its selected Credit Note',response.status_code==200,response.content[:1000]);case.refresh_from_db()
  check('Announce retains selected uploaded note',list(CaseDocument.objects.filter(case=case,is_selected=True).values_list('id',flat=True))==[__import__('uuid').UUID(ids[0])])
  response=sales.delete('/api/case-documents?caseUid='+str(case.case_uid)+'&fileId='+ids[0]);check('announced note cannot be deleted',response.status_code==409)
  original_transactions=copy.deepcopy(case.payload['transactions'])
  source=case
  for index,(kind,amount) in enumerate([('broker_credit',12.34),('broker_debit',-5.67)]):
   created=call(sales,'/api/case-workflow',dict(action='create_endorsement',caseUid=str(source.case_uid),rowVersion=source.row_version));check('create endorsement '+kind,created.status_code==201,created.content[:1000]);child=get_case(created.json()['case']['caseUid']);draft=child.payload
   draft.update(endoEffectiveDate='2049-06-01',endoText='Foreign Broker Note QA',receiptPaymentDate='2050-02-05');draft['reinsurers'][0]['brokerageAmount']=amount
   saved=call(sales,'/api/cases',dict(caseUid=str(child.case_uid),rowVersion=child.row_version,case=draft),method='put');check('endorsement Draft saves without its own note '+kind,saved.status_code==200,saved.content[:1000]);child.refresh_from_db()
   response=announce(sales,child,ids);check('source Credit Note cannot satisfy endorsement '+kind,response.status_code==400 and response.json()['error']=='documents_not_ready')
   check('endorsement has independent empty attachment list '+kind,not CaseDocument.objects.filter(case=child).exists())
   child_ids=upload_note(sales,child.case_uid,kind);response=announce(sales,child,ids);check('other case IDs cannot confirm uploaded child note '+kind,response.status_code==409 and response.json()['error']=='document_review_outdated')
   response=announce(sales,child,child_ids);check('endorsement announces with own '+kind,response.status_code==200,response.content[:1200]);child.refresh_from_db();check('note does not change signed Brokerage '+kind,child.tw_ref==case.tw_ref+f'-E{index+1:02d}' and child.payload['transactions'][0]['amount']==amount)
   source=child
  case.refresh_from_db();check('endorsement notes preserve original transactions',case.payload['transactions']==original_transactions)
  # A generic case cannot use the new Oversea-only upload kinds.
  created=call(sales,'/api/cases',{'case':raw});generic=get_case(created.json()['case']['caseUid']);generic.payload={**generic.payload,'reinsuranceStructure':'QS'};generic.save(update_fields=['payload'])
  response=call(sales,'/api/case-documents',dict(caseUid=str(generic.case_uid),kind='broker_credit',filename='credit.pdf',base64=base64.b64encode(b'%PDF-1.4 note').decode()));check('generic cases reject Oversea broker note kind',response.status_code==400 and response.json()['error']=='invalid_document_kind')
  print(str(len(checks))+' passed Oversea broker-note API checks',flush=True)
  raise Done()
except Done:pass
