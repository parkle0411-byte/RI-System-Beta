"""Convert only an explicitly approved, unbooked pure-AUW case reference."""
import copy
from audit.services import CLI_ACTOR, record_audit, record_snapshot
from coordination.services import PRODUCTION_SOURCES, serialized
from .models import Case
from .manual_reference import is_pure_auw_case, normalize_manual_tw_ref, reference_in_use


def convert_unbooked_pure_auw_reference(case_uid, *, expected_version, expected_old_ref, expected_manual_ref):
    from production.models import ProductionReport, ProductionExclusion
    with serialized(PRODUCTION_SOURCES):
        case = Case.objects.select_for_update().get(case_uid=case_uid)
        old = copy.deepcopy(case.payload or {})
        if case.tw_ref == expected_manual_ref and old.get('twRefSource') == 'auw_manual':
            return {'changedCaseCount': 0, 'caseUid': str(case.case_uid), 'twRef': case.tw_ref, 'rowVersion': case.row_version}
        if case.row_version != expected_version or case.tw_ref != expected_old_ref:
            raise ValueError('The case changed since the reviewed conversion list.')
        if case.status != 'posted' or case.case_kind != 'original' or case.parent_case_id or case.recycled_at or case.is_archived:
            raise ValueError('Only an active, announced original case can use this reviewed conversion.')
        manual, errors = normalize_manual_tw_ref(old.get('manualTwRef'))
        if errors or manual != expected_manual_ref or not is_pure_auw_case(old):
            raise ValueError('The reviewed pure AUW placement or manual reference changed.')
        if reference_in_use(manual, exclude_case_uid=case.case_uid):
            raise ValueError('The proposed AUW reference conflicts with another case.')
        if any(old.get(k) for k in ['transactions','paymentEntries','claims','confirmedProductionKeys']):
            raise ValueError('Booked or claim history requires a separate conversion plan.')
        if Case.objects.filter(parent_case=case).exists() or Case.objects.filter(payload__renewedFromTwRef=case.tw_ref).exists():
            raise ValueError('Linked endorsements or renewals require a separate conversion plan.')
        if ProductionExclusion.objects.filter(case=case).exists():
            raise ValueError('Production deferrals require a separate conversion plan.')
        for report in ProductionReport.objects.all():
            if any(isinstance(r,dict) and (str(r.get('caseUid'))==str(case.case_uid) or str(r.get('caseId'))==str(case.pk) or r.get('twRef')==case.tw_ref or r.get('policyNo')==case.tw_ref) for r in (report.rows or [])+(report.excluded_rows or [])):
                raise ValueError('Existing report snapshots require a separate conversion plan.')
        payload=copy.deepcopy(old)
        payload['twRefSource']='auw_manual'
        payload['previousTwRefs']=list(dict.fromkeys([*(old.get('previousTwRefs') or []),case.tw_ref]))
        allowed={'twRefSource','previousTwRefs'}
        assert {k:v for k,v in payload.items() if k not in allowed}=={k:v for k,v in old.items() if k not in allowed}
        before={'twRef':case.tw_ref,'rowVersion':case.row_version,'payload':old}
        case.tw_ref=manual;case.payload=payload;case.row_version+=1;case.updated_by=CLI_ACTOR['id']
        case.save(update_fields=['tw_ref','payload','row_version','updated_by','updated_at'])
        after={'caseUid':str(case.case_uid),'twRef':case.tw_ref,'status':case.status,'rowVersion':case.row_version,'payload':payload}
        record_snapshot(entity_type='case',entity_id=case.case_uid,version=case.row_version,reason='auw_primary_reference_converted',data=after,created_by=CLI_ACTOR['id'])
        record_audit(entity_type='case',entity_id=case.case_uid,action='auw_primary_reference_converted',before=before,after=after,actor=CLI_ACTOR,source='cli')
        return {'changedCaseCount':1,'caseUid':str(case.case_uid),'oldTwRef':expected_old_ref,'twRef':case.tw_ref,'rowVersion':case.row_version}
