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

def information(record, official=None):
    record=canonical(record)
    if not record: return None
    if official is None:official=is_official(record)
    return dict(id=record.pk,name=record.name,rowVersion=record.row_version,aliases=(record.payload or {}).get('announcedAliases' if official else 'aliases',[]))

def remember(record, action, actor, **details):
    data=copy.deepcopy(record.payload or {})
    data.setdefault('history',[]).append(dict(at=timezone.now().isoformat(),by=actor.get('id'),byName=actor.get('name'),action=action,**details))
    record.payload=data;record.updated_by=actor['id'];record.row_version+=1

def combination_key(name):
    """The complete slash-separated membership; order is not identity."""
    parts = [part.strip() for part in str(name or "").strip().split("/")]
    if not all(parts):
        raise AuthError(400, 'insured_name_required', 'Enter a Chinese insured name for every member separated by /.')
    return tuple(sorted(set(part.casefold() for part in parts)))


def equivalent(name, exclude_id=None):
    key = combination_key(name)
    records = list(MasterRecord.objects.filter(entity_type='insured').exclude(pk=exclude_id).order_by('id'))
    # Prefer current membership to former names; never match a subset of members.
    active = [r for r in records if r.is_active and not (r.payload or {}).get('mergedInto')]
    for record in active:
        if combination_key(record.name) == key:
            return record
    for record in active:
        if any(combination_key(alias) == key and len(key) == len(combination_key(record.name)) for alias in (record.payload or {}).get('announcedAliases', [])):
            return record
    exact = next((r for r in records if r.name == name), None)
    return canonical(exact)


def find_or_create(name, actor):
    record = equivalent(name)
    if record:
        return record
    record = MasterRecord.objects.create(entity_type='insured', name=name,
        payload={'aliases': [], 'history': [dict(at=timezone.now().isoformat(), by=actor['id'],
            byName=actor.get('name'), action='created', name=name)]}, created_by=actor['id'], updated_by=actor['id'])
    record._created_for_announce = True
    return record


def merge_records(record, target, actor, current_case=None):
    """Keep both histories and policy snapshots; retire, never delete, the source."""
    src_before = copy.deepcopy(record.payload or {})
    aliases = list(dict.fromkeys([*(target.payload or {}).get('aliases', []), record.name, *src_before.get('aliases', [])]))
    from .models import Case
    affected = Case.objects.filter(insured_master_id=record.pk)
    if current_case and current_case.pk:
        affected = affected.exclude(pk=current_case.pk)
    moved = [str(v) for v in affected.values_list('case_uid', flat=True)]
    affected.update(insured_master_id=target.pk, row_version=F('row_version') + 1)
    remember(target, 'merged', actor, sourceId=record.pk, sourceName=record.name,
             caseUids=moved, sourceHistory=src_before.get('history', []))
    target.payload['aliases'] = [n for n in aliases if n != target.name]
    target.save()
    remember(record, 'merged_into', actor, targetId=target.pk, targetName=target.name)
    record.payload['mergedInto'] = target.pk
    record.is_active = False
    record.save()
    return target


def rename(record, name, actor, body, current_case=None):
    record = canonical(record)
    expected = body.get('insuredMasterVersion')
    if expected is not None and expected != record.row_version:
        raise AuthError(409, 'insured_version_conflict', 'The insured master changed elsewhere. Reload the case before renaming it.')
    current_key, next_key = combination_key(record.name), combination_key(name)
    if len(current_key) != len(next_key):
        raise AuthError(400, 'insured_membership_change', 'Adding or removing insured members requires a separate insured master. Edit the policy to change its insured combination.')
    # Rearranging the same members does not constitute a rename.
    if current_key == next_key:
        return record
    matched = MasterRecord.objects.filter(entity_type='insured', name=name).exclude(pk=record.pk).first()
    target = canonical(matched) if matched else equivalent(name, exclude_id=record.pk)
    if matched and target.pk == record.pk and matched.pk != record.pk:
        remember(matched, 'retired_alias', actor, before=matched.name, targetId=record.pk)
        matched.payload['mergedName'] = matched.name
        matched.name = f'[Merged insured {matched.pk}]'
        matched.save()
    if target and target.pk != record.pk:
        required = MergeRequired(record, target, name)
        if body.get('insuredMerge') != required.data['insuredMerge']:
            raise required
        return merge_records(record, target, actor, current_case)
    old = record.name
    remember(record, 'renamed', actor, before=old, after=name,
             caseUid=str(current_case.case_uid) if current_case else None)
    record.payload['aliases'] = list(dict.fromkeys([*(record.payload or {}).get('aliases', []), old]))
    record.payload['aliases'] = [n for n in record.payload['aliases'] if n != name]
    if (record.payload or {}).get(OFFICIAL_KEY):
        record.payload['announcedAliases'] = list(dict.fromkeys([*(record.payload or {}).get('announcedAliases', []), old]))
    record.name = name
    record.save()
    return record


OFFICIAL_KEY = 'insuredAnnouncedAt'


def is_official(record):
    if (record.payload or {}).get(OFFICIAL_KEY):
        return True
    from .models import Case
    return Case.objects.filter(insured_master_id=record.pk, announced_at__isnull=False).exists()


def activate(record, actor, case):
    if not (record.payload or {}).get(OFFICIAL_KEY):
        data = copy.deepcopy(record.payload or {})
        history = data.setdefault('history', [])
        created_now = getattr(record, '_created_for_announce', False)
        if created_now:
            history[-1]['caseUid'] = str(case.case_uid)
        else:
            for row in history:
                row['beforeAnnounce'] = True
            history.append(dict(at=timezone.now().isoformat(), by=actor['id'], byName=actor.get('name'),
                                action='created', name=record.name, caseUid=str(case.case_uid)))
            record.row_version += 1
        data[OFFICIAL_KEY] = timezone.now().isoformat()
        record.payload = data
        record.updated_by = actor['id']
        record.save()
    return record


def change_context(case, payload, *, announcing=False):
    if case is None:
        return None
    source = case
    if announcing and case.case_kind == 'endorsement':
        from .endorsement_rules import previous_case
        source = previous_case(case)
    elif case.status not in ('posted', 'closed'):
        return None
    if source is None:
        return None
    before = str((source.payload or {}).get('originalInsuredCn') or '').strip()
    after = str(payload.get('originalInsuredCn') or '').strip()
    if not before or not after or combination_key(before) == combination_key(after):
        return None
    record = canonical(source.insured_master) if source.insured_master_id else equivalent(before)
    return dict(caseUid=str(case.case_uid), rowVersion=case.row_version, before=before, after=after,
                insuredMasterId=record.pk if record else None,
                insuredMasterVersion=record.row_version if record else None,
                masterName=record.name if record else before)


def check_change(case, payload, body, *, announcing=False):
    if not announcing and case is not None and case.status in ('posted', 'closed'):
        before = str((case.payload or {}).get('originalInsuredCn') or '').strip()
        after = str(payload.get('originalInsuredCn') or '').strip()
        if before != after and (case.status == 'closed' or (case.payload or {}).get('confirmedProductionKeys')):
            raise AuthError(409, 'insured_confirmed_locked', 'Any Confirmed portion locks insured changes. Create an Endorsement instead.')
        if before and not after:
            raise AuthError(400, 'insured_name_required', 'An Announced case requires a Chinese insured name.')
    context = change_context(case, payload, announcing=announcing)
    if not context:
        return None
    if not announcing and (case.status == 'closed' or (case.payload or {}).get('confirmedProductionKeys')):
        raise AuthError(409, 'insured_confirmed_locked', 'Any Confirmed portion locks insured changes. Create an Endorsement instead.')
    if body.get('insuredChange') != context or body.get('insuredChangeKind') not in ('correction', 'combination'):
        raise ChangeRequired(context)
    return context


class ChangeRequired(Exception):
    def __init__(self, context):
        self.data = dict(error='insured_change_required', message='Confirm whether this is a name correction or a different insured combination.', insuredChange=context)


def sync(case, payload, actor, body=None, *, new=False, inherit_id=None, announcing=False):
    from .oversea import enabled as oversea_enabled
    if oversea_enabled(payload) and not str(payload.get('originalInsuredCn') or '').strip() and not (case and case.insured_master_id):
        payload.pop(KEY, None)
        return None
    body = body or {}
    payload[KEY] = True
    # All Drafts, including renewals and endorsements, retain names only on Case.
    if not announcing and (case is None or case.status == 'draft'):
        return None
    if not announcing and case.status not in ('posted', 'closed'):
        return case.insured_master
    name = str(payload.get('originalInsuredCn') or '').strip()[:240]
    if not name:
        return case.insured_master if case else None
    context = check_change(case, payload, body, announcing=announcing)
    if context and body['insuredChangeKind'] == 'correction':
        record = MasterRecord.objects.get(pk=context['insuredMasterId']) if context['insuredMasterId'] else find_or_create(context['before'], actor)
        record = activate(record, actor, case)
        target = equivalent(name, exclude_id=record.pk)
        if target and target.pk != record.pk:
            activate(target, actor, case)
        record = rename(record, name, actor, {**body, 'insuredMasterVersion':record.row_version}, current_case=case)
    else:
        record = find_or_create(name, actor)
    return activate(record, actor, case)
