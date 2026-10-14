"""Explicit, idempotent repair of existing AUW foreign-broker bindings."""
import copy

from audit.services import CLI_ACTOR, record_audit, record_snapshot
from coordination.services import PRODUCTION_SOURCES, serialized

from .manual_reference import AUW_FOREIGN_BROKER, is_auw_reinsurer, requires_manual_tw_ref
from .models import Case


def bind_existing_auw_cases():
    """Change only AUW broker fields, keeping amounts, references and cash history."""
    changed = []
    pending = []
    changed_rows = 0
    with serialized(PRODUCTION_SOURCES):
        for case in Case.objects.select_for_update().order_by('pk'):
            if not requires_manual_tw_ref(case.payload):
                continue
            original = copy.deepcopy(case.payload)
            payload = copy.deepcopy(original)
            affected = []
            for index, row in enumerate(payload['reinsurers']):
                if isinstance(row, dict) and is_auw_reinsurer(row.get('name')) and row.get('foreignBroker') != AUW_FOREIGN_BROKER:
                    row['foreignBroker'] = AUW_FOREIGN_BROKER
                    affected.append(index)
            if affected:
                # Verify the mutation is exactly the requested broker binding.
                restored = copy.deepcopy(payload)
                for index in affected:
                    if 'foreignBroker' in original['reinsurers'][index]:
                        restored['reinsurers'][index]['foreignBroker'] = original['reinsurers'][index]['foreignBroker']
                    else:
                        restored['reinsurers'][index].pop('foreignBroker', None)
                assert restored == original
                before_version = case.row_version
                case.payload = payload
                case.row_version += 1
                case.updated_by = CLI_ACTOR['id']
                case.save(update_fields=['payload', 'row_version', 'updated_by', 'updated_at'])
                snapshot = {'caseUid':str(case.case_uid), 'twRef':case.tw_ref, 'status':case.status,
                            'rowVersion':case.row_version, 'payload':payload}
                record_snapshot(entity_type='case', entity_id=case.case_uid, version=case.row_version,
                                reason='auw_howden_bound', data=snapshot, created_by=CLI_ACTOR['id'])
                record_audit(entity_type='case', entity_id=case.case_uid, action='auw_howden_bound',
                             before={'rowVersion':before_version, 'payload':original}, after=snapshot,
                             actor=CLI_ACTOR, source='cli', metadata={'reinsurerIndices':affected})
                changed.append(str(case.case_uid))
                changed_rows += len(affected)
            reference = payload.get('manualTwRef')
            if not isinstance(reference, str) or not reference.strip():
                pending.append({'caseUid':str(case.case_uid), 'twRef':case.tw_ref or '', 'status':case.status,
                                'caseKind':case.case_kind, 'policyFrom':payload.get('policyFrom') or '',
                                'originalInsured':payload.get('originalInsured') or '',
                                'recycled':case.recycled_at is not None, 'archived':case.is_archived,
                                'rowVersion':case.row_version})
    return {'changedCaseCount':len(changed), 'changedRowCount':changed_rows,
            'changedCaseUids':changed, 'missingManualRefs':pending}
