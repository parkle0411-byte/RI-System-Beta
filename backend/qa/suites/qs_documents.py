"""Document-only QS integration checks; disposable DB and synthetic files only."""
import base64
import copy
import hashlib
import io
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client, override_settings
from django.utils import timezone
from cases.models import Case, CaseDocument
from cases import storage
from cases.qs_documents import readiness_issues, scope
from cases.property_original import totals
from personnel.models import Personnel
from audit.models import AuditLog

results = []
def check(name, ok, detail=''): results.append((name, bool(ok), detail))
class Rollback(Exception): pass
def call(client, method, path, body=None):
    client.get('/api/auth/csrf')
    kw = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value}
    if body is not None: kw.update(data=json.dumps(body), content_type='application/json')
    return getattr(client, method)(path, **kw)
def account(role):
    person = Personnel.objects.create(name='ZZ QS DOC '+role, department='reinsurance' if role=='sales' else 'business_1', role_code=role, created_by='qa', updated_by='qa')
    user = get_user_model().objects.create_user(username='zz.qsdoc.'+role, password='Doc-Test-Pass-1')
    person.auth_user_id=str(user.pk);person.account_status='active';person.save()
    client=Client(enforce_csrf_checks=True,HTTP_HOST='localhost',raise_request_exception=False)
    cache.clear()
    assert call(client,'post','/api/auth/login',{'username':user.username,'password':'Doc-Test-Pass-1'}).status_code==200
    return client
def ready(**over):
    payload=dict(construction='A2 Class',constructionSelections=['A2 Class'],reinsuranceStructure='QS', classCode='PD', classOfBusiness='Property', type='Property Facultative Reinsurance',
        reinsured='ZZ Cedant', originalInsured='ZZ Insured', ae='ZZ AE', aeEmail='qa@example.invalid', currency='USD',
        policyFrom='2026-10-01',policyTo='2027-10-01',interest='Building',limitOfLiability=100000,deductibles='As original',
        situations=[dict(address='1 QA Road',postcode='100')],sumInsured=[dict(category='Building',amount=100000,locationIndex=0)],
        reinsurers=[dict(name='ZZ Ordinary Re',sharePct=100,premium=1000,riCommPct=5,taxPct=0,paymentTermsDays=90)],
        lossAdvisedDate='2026-10-24',lossRecordYears=5,lossRecord=[],originalPremium=1000,riCommPct=10,taxPct=1,
        paymentTermsDays=90,installmentEnabled=False)
    payload.update(over);return payload
def fields(payload,kind='cover'): return {r['field'] for r in readiness_issues(payload,kind,'qa@example.invalid')}
def word(text):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
    return b.getvalue()

try:
  with tempfile.TemporaryDirectory() as tmp, override_settings(CASE_DOCUMENT_ROOT=tmp), transaction.atomic():
    sales=account('sales');viewer=account('viewer')
    payload=ready()
    case=Case.objects.create(case_kind='original',status='posted',tw_ref='ZZ-QSDOC-2026',reinsurance_structure='QS',payload=payload,created_by='qa',updated_by='qa',announced_at=timezone.now())
    uid=str(case.case_uid)
    listing='/api/case-documents?caseUid='+uid
    def prepare(kind='cover',**over):
        return call(sales,'post','/api/document-generation-log',dict(format='docx',kind=kind,caseUid=uid,saveWorkflow=1,rowVersion=case.row_version,**over))
    def save(kind='cover',content=None,generation_id=None,**over):
        body=dict(kind=kind,caseUid=uid,generationId=generation_id or str(uuid.uuid4()),rowVersion=case.row_version,
            filename=('CoverNote' if kind=='cover' else 'DebitNote')+'_ZZ-QSDOC-2026_ZZ Insured_2026-10-27.docx',base64=base64.b64encode(content or word(kind)).decode())
        body.update(over)
        return call(sales,'post','/api/generated-case-documents',body)
    check('valid cover permits blank retention',readiness_issues(payload,'cover','qa@example.invalid')==[],readiness_issues(payload,'cover','qa@example.invalid'))
    check('valid debit permits blank retention',readiness_issues(payload,'debit','qa@example.invalid')==[])
    for kind in ('cover','debit'):
        r=prepare(kind);check(kind+' prepare gives locked version and Taiwan date',r.status_code==200 and r.json().get('rowVersion')==1 and len(r.json().get('generationDate',''))==10,r.content)
    r=call(sales,'post','/api/document-generation-log',dict(format='docx',kind='cover',caseUid=uid))
    check('old cached client cannot bypass saving workflow',r.status_code==409 and r.json()['error']=='document_client_refresh_required')
    for version in (0,2,'1',True,None):
        r=call(sales,'post','/api/document-generation-log',dict(format='docx',kind='cover',caseUid=uid,saveWorkflow=1,rowVersion=version))
        check('strict prepare rowVersion '+repr(version),r.status_code==409)
    gaps=ready(reinsured='',originalInsured='',type='',ae='',originalPremium='',interest='',limitOfLiability='',deductibles='',situations=[{}],sumInsured=[{}],lossRecord=[{}],lossAdvisedDate='',lossRecordYears='')
    Case.objects.filter(pk=case.pk).update(payload=gaps)
    r=prepare();issues=r.json().get('issues',[])
    check('all required fields reported together and detail labels retained',r.status_code==409 and len(issues)>=15 and {'situations.0.address','sumInsured.0.amount','lossRecord.0.lossPaid'}.issubset({i['field'] for i in issues}),r.content)
    Case.objects.filter(pk=case.pk).update(payload=payload)
    for bad in (None,'',0,-1,'bad'):
        check('loss amount must exceed zero '+repr(bad),'lossRecord.0.lossPaid' in fields(ready(lossRecord=[dict(date='2026-10-01',cause='QA',lossPaid=bad)])))
    check('positive loss accepted','lossRecord.0.lossPaid' not in fields(ready(lossRecord=[dict(date='2026-10-01',cause='QA',lossPaid=.01)])))
    for bad in (0,-1,14,15.5,'bad'):
        p=ready(installmentEnabled=True,performanceInstallments=[dict(paymentTermsDays=bad),dict(paymentTermsDays=90)])
        check('explicit invalid period days never inherit '+repr(bad),'performanceInstallments.0.paymentTermsDays' in fields(p))
    for blank in (None,'',' \t '):
        check('only blank period may inherit '+repr(blank),'performanceInstallments.0.paymentTermsDays' not in fields(ready(installmentEnabled=True,performanceInstallments=[dict(paymentTermsDays=blank),dict(paymentTermsDays=60)])))
    rows=[dict(ratio=50,paymentBaseDate='2026-10-01',paymentTermsDays=60,reinsurerPaymentTerms={'r1':90}),dict(ratio=50,paymentBaseDate='2027-01-01',paymentTermsDays=90,reinsurerPaymentTerms={'r1':90})]
    check('valid per-period T1 dates accepted',not fields(ready(installmentEnabled=True,performanceInstallments=rows),'debit'))
    broken=copy.deepcopy(rows);broken[0].update(ratio=0,paymentTermsDays=0,paymentBaseDate='bad');broken[1].update(reinsurerPaymentTerms={},paymentTermsDays=None)
    fs=fields(ready(installmentEnabled=True,performanceInstallments=broken),'debit')
    check('all bad allocations, dates and RI terms are reported',{'performanceInstallments.0.premium','performanceInstallments.0.paymentBaseDate','performanceInstallments.0.paymentTermsDays','performanceInstallments.1.paymentTermsDays','performanceInstallments.1.reinsurerPaymentTerms.r1'}.issubset(fs),fs)
    check('whole zero net blocks debit','netDue' in fields(ready(originalPremium=0),'debit'))
    check('whole zero net does not block cover','netDue' not in fields(ready(originalPremium=0),'cover'))
    tiny=ready(currency='TWD',originalPremium=1,riCommPct=0,taxPct=0,installmentEnabled=True,performanceInstallments=rows)
    check('rounded-zero individual T1 allowed when full net positive','netDue' not in fields(tiny,'debit'))
    for changes in (dict(reinsuranceStructure='XOL'),dict(reinsuranceStructure='TREATY'),dict(parentTwRef='OLD'),dict(classCode='CGL',classOfBusiness='Liability')):
        check('new storage excludes '+repr(changes),not scope(ready(**changes),'cover'))
    check('endorsement excluded',not scope(payload,'endorsement'))
    original=copy.deepcopy(case.payload);money=totals(original)
    first_id=str(uuid.uuid4());content=word('same bytes')
    r=save(content=content,generation_id=first_id);check('successful generated save returns201',r.status_code==201,r.content)
    row=CaseDocument.objects.get(pk=first_id)
    check('bytes stored intact and never selected evidence',storage.path_for(row.storage_key).read_bytes()==content and not row.is_selected and row.reinsurers==[] and row.sha256==hashlib.sha256(content).hexdigest())
    r=save(content=content,generation_id=first_id);check('lost-response retry idempotent',r.status_code==200 and CaseDocument.objects.filter(case=case).count()==1)
    r=save(content=word('different'),generation_id=first_id);check('same id conflicting content rejected',r.status_code==409)
    for version in (0,2,'1',True,None):
        r=save(rowVersion=version);check('strict save rowVersion '+repr(version),r.status_code==409)
    count=CaseDocument.objects.count()
    for module in ('cases.generated_document_views.storage.put','cases.generated_document_views.record_audit'):
        with patch(module,side_effect=RuntimeError('synthetic save failure')):
            r=save(content=word('will rollback'))
        check('failure rolls back without replacing latest '+module,r.status_code==500 and CaseDocument.objects.count()==count and len(list(Path(tmp).rglob('*.docx')))==count)
    second=save(content=word('version2'));debit=save('debit')
    state=call(sales,'get',listing).json()
    check('main list has one latest per kind and old version in history',len(state.get('generatedFiles',[]))==2 and len(state.get('generatedHistory',[]))==1 and state['generatedHistory'][0]['id']==first_id and all(x['is_latest'] for x in state['generatedFiles']),state)
    check('generated files do not change placement readiness',state['files']==[] and not state['coverage']['offer'])
    for item in state['generatedFiles']+state['generatedHistory']:
        r=call(sales,'get',listing+'&fileId='+item['id'])
        raw=b''.join(r.streaming_content) if r.status_code==200 else b''
        check('latest and history downloadable '+item['id'],r.status_code==200 and hashlib.sha256(raw).hexdigest()==CaseDocument.objects.get(pk=item['id']).sha256)
    r=call(sales,'put','/api/case-documents',{'caseUid':uid,'fileId':first_id,'isSelected':True})
    check('generated document cannot become signed evidence',r.status_code==409)
    check('generated history cannot be deleted',call(sales,'delete',listing+'&fileId='+first_id).status_code==409)
    # Exercise the boundary rather than mocking the document count.
    for i in range(49):
        CaseDocument.objects.create(case=case,kind='offer',filename='manual.docx',content_type='application/octet-stream',byte_size=1,sha256='a'*64,storage_key='qa/manual/'+str(i),is_selected=True,uploaded_by='qa')
    manual=dict(caseUid=uid,kind='offer',filename='manual.docx',base64=base64.b64encode(word('manual50')).decode())
    r=call(sales,'post','/api/case-documents',manual)
    check('50th manual upload allowed despite generated history',r.status_code==201,r.content)
    r=call(sales,'post','/api/case-documents',manual)
    check('51st manual upload blocked',r.status_code==400 and r.json().get('error')=='document_limit')
    check('generated version still saves at manual50',save(content=word('version3')).status_code==201)
    before_audit=AuditLog.objects.count()
    with override_settings(AUDIT_LOG_PAUSED=True):
        r=save(content=word('audit remains paused'))
    check('production Audit pause remains effective for generated saves',r.status_code==201 and AuditLog.objects.count()==before_audit)
    check('viewer cannot save Word',call(viewer,'post','/api/generated-case-documents',dict(caseUid=uid,kind='cover')).status_code==403)
    check('manual endpoint cannot impersonate generated Word',call(sales,'post','/api/case-documents',{**manual,'kind':'generated_cover'}).status_code==400)
    case.refresh_from_db()
    check('all generation and failures leave Case data/version/accounting unchanged',case.payload==original and case.row_version==1 and totals(case.payload)==money)
    raise Rollback()
except Rollback:
    pass
fails=[x for x in results if not x[1]]
for name,ok,detail in results:print(('PASS ' if ok else 'FAIL ')+name+('' if ok else ' '+str(detail)))
print(f'{len(results)-len(fails)}/{len(results)} passed; synthetic database changes rolled back')
