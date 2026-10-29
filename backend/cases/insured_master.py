"""Chinese-name insured identity. Case names are immutable historical snapshots
unless that case itself is edited. Histories survive a paused general Audit Log.
All mutations run inside the production-source serialized transaction.
"""
import copy
from django.db.models import F
from django.utils import timezone
from masterdata.models import MasterRecord
from ri_system.authz import AuthError
KEY='insuredDirectoryEnabled'

class MergeRequired(Exception):
    def __init__(self, source, target, name):
        self.data=dict(error='insured_merge_required',message='This Chinese name belongs to another insured master. Confirm they are the same insured before merging.',
            insuredMerge=dict(sourceId=source.pk,targetId=target.pk,sourceVersion=source.row_version,targetVersion=target.row_version,name=name),
            sourceName=source.name,targetName=target.name)

def canonical(record):
    seen=set()
    while record and (record.payload or {}).get('mergedInto'):
        if record.pk in seen: raise AuthError(409,'insured_master_invalid','Insured master merge chain requires review.')
        seen.add(record.pk)
        record=MasterRecord.objects.get(pk=record.payload['mergedInto'],entity_type='insured')
    return record

def information(record):
    record=canonical(record)
    if not record: return None
    return dict(id=record.pk,name=record.name,rowVersion=record.row_version,aliases=(record.payload or {}).get('aliases',[]))

def remember(record, action, actor, **details):
    data=copy.deepcopy(record.payload or {})
    data.setdefault('history',[]).append(dict(at=timezone.now().isoformat(),by=actor.get('id'),byName=actor.get('name'),action=action,**details))
    record.payload=data;record.updated_by=actor['id'];record.row_version+=1

def find_or_create(name,actor):
    record=MasterRecord.objects.filter(entity_type='insured',name=name).first()
    if record: return canonical(record)
    return MasterRecord.objects.create(entity_type='insured',name=name,payload={'aliases':[],'history':[dict(at=timezone.now().isoformat(),by=actor['id'],byName=actor.get('name'),action='created',name=name)]},created_by=actor['id'],updated_by=actor['id'])

def rename(record,name,actor,body,current_case=None):
    record=canonical(record)
    if record.name==name:return record
    expected=body.get('insuredMasterVersion')
    if expected is not None and expected!=record.row_version:
        raise AuthError(409,'insured_version_conflict','The insured master changed elsewhere. Reload the case before renaming it.')
    target=MasterRecord.objects.filter(entity_type='insured',name=name).exclude(pk=record.pk).first()
    matched=target
    target=canonical(target)
    if matched and target.pk==record.pk and matched.pk!=record.pk:
        # A former merged identity retains its name in history, while freeing the unique name for the survivor.
        remember(matched,'retired_alias',actor,before=matched.name,targetId=record.pk)
        matched.payload['mergedName']=matched.name
        matched.name=f'[Merged insured {matched.pk}]'
        matched.save()
    if target and target.pk!=record.pk:
        required=MergeRequired(record,target,name)
        if body.get('insuredMerge')!=required.data['insuredMerge']:raise required
        src_before=copy.deepcopy(record.payload or {})
        aliases=list(dict.fromkeys([*(target.payload or {}).get('aliases',[]),record.name,*src_before.get('aliases',[])]))
        aliases=[n for n in aliases if n!=target.name]
        from .models import Case
        affected=Case.objects.filter(insured_master_id=record.pk)
        if current_case and current_case.pk: affected=affected.exclude(pk=current_case.pk)
        moved=[str(v) for v in affected.values_list('case_uid',flat=True)]
        affected.update(insured_master_id=target.pk,row_version=F('row_version')+1)
        remember(target,'merged',actor,sourceId=record.pk,sourceName=record.name,caseUids=moved,sourceHistory=src_before.get('history',[]))
        target.payload['aliases']=aliases;target.save()
        remember(record,'merged_into',actor,targetId=target.pk,targetName=target.name)
        record.payload['mergedInto']=target.pk;record.is_active=False;record.save()
        return target
    old=record.name
    remember(record,'renamed',actor,before=old,after=name,caseUid=str(current_case.case_uid) if current_case else None)
    record.payload['aliases']=list(dict.fromkeys([*(record.payload or {}).get('aliases',[]),old]))
    record.payload['aliases']=[n for n in record.payload['aliases'] if n!=name]
    record.name=name;record.save()
    return record

def sync(case,payload,actor,body=None,*,new=False,inherit_id=None):
    body=body or {}
    enabled=new or bool(case and ((case.payload or {}).get(KEY) or case.insured_master_id))
    payload.pop(KEY,None)
    if not enabled:return None
    payload[KEY]=True
    name=str(payload.get('originalInsuredCn') or '').strip()[:240]
    master_id=inherit_id or (case.insured_master_id if case else None)
    record=canonical(MasterRecord.objects.get(pk=master_id,entity_type='insured')) if master_id else None
    if not name:return record
    if not record:return find_or_create(name,actor)
    old_name=str((case.payload or {}).get('originalInsuredCn') or '').strip() if case else name
    if not new and name!=old_name:
        record=rename(record,name,actor,body,current_case=case)
    return record
