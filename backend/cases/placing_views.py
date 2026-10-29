"""Placing Slip versions are independent of evidence, finance and official references."""
import hashlib
import copy
import json
import re
import uuid
from django.db import transaction
from django.db.models import Max
from django.http import FileResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from audit.services import record_audit
from audit.services import request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from
from .models import Case, PlacingSlipVersion, MAX_DOCUMENT_BYTES
from .views import visible_cases
from . import storage, documents
from . import placing_rules as rules

def error(code, message, status=409, **extra):
    return Response(dict(error=code, message=message, **extra), status=status)

def signature(p):
    from .draft_input import input_for
    from .resolve import resolve_clause_titles
    p = resolve_clause_titles(copy.deepcopy(input_for(p)))
    keys='classOfBusiness reinsuranceStructure type reinsured originalInsured policyFrom policyTo policyFromTime policyToTime currency interest limitOfLiability aggregateLimit subLimits deductibles selfInsuredRetention reinsuredRetention reinstatementProvisions indemnityPeriod originalExclusions basisOfValuation basisOfValuationOther originalConditions expressWarranties conditionsPrecedent subjectivities occupation construction lossPayee coReinsuranceWarranty notices specialAgreement cglInformation coverages coveragesOther situations sumInsured lossRecord lossRecordYears lossAdvisedDate lossRecordText clauseDetails manualClauses ae aeEmail endoEffectiveDate endoTypes endoText'.split()
    data={k:p.get(k) for k in keys}
    from .construction import scope as construction_scope, FIELDS as construction_fields
    if construction_scope(p) and any(k in p for k in construction_fields):
        data.update({k:p.get(k) for k in construction_fields})
    from .document_generation_views import _ae_email
    from .placing_word import clause_lines
    data['resolvedAeEmail']=_ae_email(p)
    data['resolvedClauses']=clause_lines(p)
    if p.get('parentTwRef'):data['reinsurers']=[r.get('name') for r in p.get('reinsurers') or []]
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()

def row(r, sig):
    return {k:getattr(r,k) for k in ('version','source','filename','content_type','byte_size','description','uploaded_by','uploaded_at','case_version')} | {'id':str(r.pk),'outdated':r.signature!=sig}

def state(case):
    p=case.payload or {}; sig=signature(p)
    rows=list(PlacingSlipVersion.objects.filter(case=case,deleted_at__isnull=True).order_by('-version'))
    eligible=rules.enabled(p) and rules.has_ordinary(p)
    uploaded=any(r.source=='uploaded' for r in rows)
    return {'eligible':eligible,'canGenerate':eligible and case.status=='draft' and not uploaded,
            'canUpload':eligible and case.status=='draft','canDelete':case.status=='draft',
            'versions':[row(r,sig) for r in rows], 'outdated':bool(rows and rows[0].signature!=sig)}

def predicted_references(case):
    from .manual_reference import requires_manual_tw_ref, reference_in_use
    root=case.parent_case
    if root is None or not root.tw_ref:raise ValueError('The Original TW Reference is required.')
    prefix=root.tw_ref+'-E'
    from .models import ReferenceSequence
    current = ReferenceSequence.objects.filter(prefix=prefix).values_list('last_value', flat=True).first()
    sequence=(current or 0)+1
    auw=(root.payload or {}).get('manualTwRef') or (root.tw_ref if (root.payload or {}).get('twRefSource')=='auw_manual' else '')
    if requires_manual_tw_ref(case.payload) and not auw:raise ValueError('The Original AUW reference is required.')
    while True:
        suffix='-E'+str(sequence).zfill(2); primary=root.tw_ref+suffix
        other=auw+suffix if requires_manual_tw_ref(case.payload) else ''
        if not reference_in_use(primary) and (not other or other==primary or not reference_in_use(other)):break
        sequence+=1
    return {'sequence':str(sequence).zfill(2),'root':root.tw_ref+(' & '+auw if auw and auw!=root.tw_ref else ''),'full':primary+(' & '+other if other and other!=primary else '')}

def ready(case):
    from .draft_input import input_for
    from .document_generation_views import _ae_email
    from .data_integrity import response_error
    from .facility_selection import selection_issues
    from .resolve import resolve_clause_titles
    p=resolve_clause_titles(copy.deepcopy(input_for(case.payload or {})))
    bad=response_error(case.payload)
    if bad is not None:return p,'',bad
    email=_ae_email(p)
    issues=selection_issues(p)
    if not str(p.get('ae') or '').strip():issues.append({'field':'ae','label':'Account Executive'})
    if not email:issues.append({'field':'aeEmail','label':'AE Email'})
    if case.case_kind=='endorsement':
        from .endorsement_rules import endorsement_issues, context_for, day
        issues+=endorsement_issues(p,context_for(case))
        for key in ('type','reinsured','originalInsured','policyFrom','policyTo','endoEffectiveDate','endoTypes','endoText'):
            if not p.get(key) or isinstance(p.get(key),str) and not p[key].strip():issues.append({'field':key,'label':key})
        if not day(p.get('endoEffectiveDate')):issues.append({'field':'endoEffectiveDate','label':'Enter a valid endorsement effective date.'})
        if not isinstance(p.get('endoTypes'),list) or any(not isinstance(x,str) or not x.strip() for x in p['endoTypes']):issues.append({'field':'endoTypes','label':'Select endorsement types.'})
        issues += [i for i in rules.extra_issues(p) if i['field'].endswith(('businessLegacyConfirmed','legacyRegionConfirmed'))]
    else:issues+=rules.underwriting_issues(p)
    if case.case_kind=='endorsement':
        from .construction import issues as construction_issues
        issues+=construction_issues(p)
    if issues:return p,email,error('placing_not_ready','Complete the following Placing Slip data.',issues=issues)
    return p,email,None

class PlacingSlipView(NoStoreMixin, APIView):
    permission_classes=[RIPermission]
    permission_map={'GET':'documents.read','POST':'documents.write','DELETE':'documents.write'}

    def find(self,request,uid,lock=False):
        try:uid=uuid.UUID(str(uid))
        except (TypeError,ValueError):return None
        q=visible_cases(request.ri_principal)
        if lock:q=q.select_for_update()
        return q.filter(case_uid=uid).first()

    def get(self,request):
        case=self.find(request,request.query_params.get('caseUid'))
        if case is None:return error('case_not_found','Case was not found.',404)
        if request.query_params.get('fileId'):
            try:file_id=uuid.UUID(request.query_params['fileId'])
            except ValueError:return error('file_not_found','File was not found.',404)
            r=PlacingSlipVersion.objects.filter(case=case,pk=file_id,deleted_at__isnull=True).first()
            if r is None:return error('file_not_found','File was not found.',404)
            try:handle=storage.open_read(r.storage_key)
            except FileNotFoundError:return error('file_content_missing','The saved file is unavailable.',404)
            response=FileResponse(handle,content_type=r.content_type)
            response['Content-Disposition']=documents.content_disposition(r.filename)
            return response
        return Response(state(case))

    def post(self,request):
        body=request.data if isinstance(request.data,dict) else {}
        description=str(body.get('description') or '').strip()
        if not description or len(description)>500:return error('description_required','Enter a version description (at most 500 characters).',400)
        action=body.get('action')
        if action not in ('generate','upload'):return error('invalid_action','Choose generate or upload.',400)
        try:file_id=uuid.UUID(str(body.get('generationId')))
        except ValueError:return error('generation_id_required','A valid retry identifier is required.',400)
        key=None
        try:
            with transaction.atomic():
                case=self.find(request,body.get('caseUid'),lock=True)
                if case is None:return error('case_not_found','Case was not found.',404)
                if not rules.enabled(case.payload) or not rules.has_ordinary(case.payload):return error('placing_scope','Placing Slip requires a new Property/CGL QS case with an ordinary reinsurer or no reinsurer selected.')
                if case.status!='draft':return error('placing_draft_only','Placing Slip can be generated or uploaded only in Draft.')
                prior=PlacingSlipVersion.objects.filter(pk=file_id).first()
                if prior:
                    if prior.case_id!=case.pk or prior.deleted_at or prior.description!=description or prior.source!=('generated' if action=='generate' else 'uploaded'):
                        return error('placing_retry_conflict','Start a new document operation.')
                    if action == 'generate' and prior.snapshot.get('annual') != body.get('annual', True):
                        return error('placing_retry_conflict','Annual changed. Start a new document operation.')
                    if action == 'upload':
                        decoded = documents.decode_and_validate(documents.safe_filename(body.get('filename')),body.get('base64'),MAX_DOCUMENT_BYTES)
                        if 'error' in decoded or documents.safe_filename(body.get('filename')) != prior.filename or hashlib.sha256(decoded['bytes']).hexdigest() != prior.sha256:
                            return error('placing_retry_conflict','The uploaded file changed. Start a new document operation.')
                    if not storage.path_for(prior.storage_key).is_file():return error('file_content_missing','The saved file is unavailable.')
                    return Response({'ok':True,'file':row(prior,signature(case.payload)),**state(case)})
                if type(body.get('rowVersion')) is not int or body['rowVersion']!=case.row_version:return error('version_conflict','The case changed. Reload before saving a Placing Slip.')
                p=case.payload
                if action=='generate':
                    if PlacingSlipVersion.objects.filter(case=case,source='uploaded',deleted_at__isnull=True).exists():return error('placing_manual_versions','An edited version exists. Upload the next edited version, or delete all uploaded versions before generating again.')
                    p,email,problem=ready(case)
                    if problem is not None:return problem
                    if not isinstance(body.get('annual',True),bool):return error('invalid_annual','Annual must be a boolean.',400)
                    previous=None;refs=None
                    if case.case_kind=='endorsement':
                        from .endorsement_rules import previous_case
                        previous=previous_case(case).payload
                        try: refs=predicted_references(case)
                        except ValueError as exc: return error('source_reference_required',str(exc))
                    from .placing_word import render
                    data=render(p,email,annual=body.get('annual',True),previous=previous,references=refs)
                    ext='docx';ctype=documents.CONTENT_TYPES[ext]
                    clean=re.sub(r'[^\w .-]','_',str(p.get('originalInsured') or 'Draft'))[:70]
                    filename=f'PlacingSlip_{clean}_{timezone.localtime():%Y%m%d}.docx'
                else:
                    filename=documents.safe_filename(body.get('filename'));ext=filename.rsplit('.',1)[-1].lower()
                    if ext not in ('pdf','docx'):return error('invalid_file','Upload a DOCX or PDF Placing Slip.',415)
                    decoded=documents.decode_and_validate(filename,body.get('base64'),MAX_DOCUMENT_BYTES)
                    if 'error' in decoded:return error('invalid_file',decoded['error'][1],decoded['error'][0])
                    data=decoded['bytes'];ctype=decoded['contentType']
                number=(PlacingSlipVersion.objects.filter(case=case).aggregate(n=Max('version'))['n'] or 0)+1
                key=f'placing-slips/{case.case_uid}/{file_id}.{ext}'
                storage.put(key,data)
                actor=actor_from(request.ri_principal)
                r=PlacingSlipVersion.objects.create(id=file_id,case=case,version=number,source='generated' if action=='generate' else 'uploaded',filename=filename,content_type=ctype,byte_size=len(data),sha256=hashlib.sha256(data).hexdigest(),storage_key=key,description=description,case_version=case.row_version,signature=signature(p),snapshot={'annual':body.get('annual',True),'estimatedReferences':refs if action=='generate' else None,'case':copy.deepcopy(p)},uploaded_by=actor['name'])
                record_audit(entity_type='placing_slip',entity_id=case.case_uid,action='generate_placing' if action=='generate' else 'upload_placing',before=None,after={'id':str(r.pk),'version':number,'description':description,'sha256':r.sha256},actor=actor,request_id=request_id_from(request))
            return Response({'ok':True,'file':row(r,signature(p)),**state(case)},status=201)
        except BaseException:
            if key:
                from .document_views import _delete_quietly
                _delete_quietly(key)
            raise

    def delete(self,request):
        with transaction.atomic():
            case=self.find(request,request.query_params.get('caseUid'),lock=True)
            if case is None:return error('case_not_found','Case was not found.',404)
            if case.status!='draft':return error('placing_delete_locked','Placing Slip versions cannot be deleted after Announce.')
            try:file_id=uuid.UUID(request.query_params.get('fileId',''))
            except ValueError:return error('file_not_found','File was not found.',404)
            r=PlacingSlipVersion.objects.filter(case=case,pk=file_id,deleted_at__isnull=True).first()
            if r is None:return error('file_not_found','File was not found.',404)
            r.deleted_at=timezone.now();r.save(update_fields=['deleted_at'])
            from .document_views import _delete_quietly
            transaction.on_commit(lambda:_delete_quietly(r.storage_key))
            record_audit(entity_type='placing_slip',entity_id=case.case_uid,action='delete_placing',before={'id':str(r.pk),'version':r.version},after=None,actor=actor_from(request.ri_principal),request_id=request_id_from(request))
        return Response({'ok':True,**state(case)})
