"""Update reconciliation references without reopening or recalculating a case."""
import copy
import re

from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from coordination.services import PRODUCTION_SOURCES, serialized
from ri_system.authz import NoStoreMixin, RIPermission, actor_from
from .calc.accounting import reconciliation_ref_for
from .calc.jsnum import js_len, js_trim
from .manual_reference import manual_tw_ref_fields
from .views import visible_cases, _parse_uuid


def _references(case):
    payload = case.payload
    reinsurers = payload.get('reinsurers')
    return {
        'caseUid': str(case.case_uid), 'twRef': case.tw_ref or '',
        **manual_tw_ref_fields(payload),
        'status': case.status, 'rowVersion': case.row_version,
        'originalInsured': payload.get('originalInsured') or payload.get('original_insured') or '',
        'originalInsuredCn': payload.get('originalInsuredCn') or '',
        'statementNo': payload.get('statementNo') or '',
        'reinsurers': [
            {'index': index, 'name': row.get('name') or '', 'settlementRef': row.get('settlementRef') or ''}
            for index, row in enumerate(reinsurers if isinstance(reinsurers, list) else []) if isinstance(row, dict)
        ],
    }


def schedule_reference_metadata(payload, row):
    """Schedule-only Accounting rows use the same current references as transactions."""
    party_key = str(row.get('partyKey') or row.get('scheduleKey') or '').rsplit(':', 1)[-1]
    match = re.fullmatch(r'r([1-9][0-9]*)', party_key)
    tx = {'legType': 'Leg 1' if row.get('partyType') == 'cedant' else 'Leg 2',
          'reinsurerIdx': int(match[1]) - 1 if match else -1}
    return {'statementNo': payload.get('statementNo') or '',
            'reconciliationRef': reconciliation_ref_for(payload, tx),
            'originalInsured': payload.get('originalInsured') or payload.get('original_insured') or '',
            'originalInsuredCn': payload.get('originalInsuredCn') or ''}


def _error(status, code, message):
    return Response({'error': code, 'message': message}, status=status)


def _text(value):
    if not isinstance(value, str) or js_len(value) > 160:
        raise ValueError('References must be text of no more than 160 characters.')
    return js_trim(value)


class ReconciliationReferencesView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'GET': 'cases.write', 'POST': 'cases.write'}

    @staticmethod
    def _case(request, uid, lock=False):
        parsed = _parse_uuid(uid)
        if not parsed:
            return None, _error(400, 'case_uid_required', 'A valid Case ID is required.')
        qs = visible_cases(request.ri_principal)
        case = (qs.select_for_update() if lock else qs).filter(case_uid=parsed).first()
        if case is None:
            return None, _error(404, 'case_not_found', 'Case was not found.')
        if case.status not in ('posted', 'closed'):
            return None, _error(409, 'reference_status_locked', 'Use this entry for Announced or Confirmed cases.')
        if not isinstance(case.payload, dict):
            return None, _error(409, 'case_data_unreadable', 'Case data could not be read.')
        return case, None

    def get(self, request):
        case, error = self._case(request, request.query_params.get('caseUid'))
        return error if error is not None else Response({'ok': True, 'case': _references(case)})

    def post(self, request):
        body = request.data
        if not isinstance(body, dict) or set(body) - {'caseUid', 'rowVersion', 'statementNo', 'reinsurers'}:
            return _error(400, 'reference_fields_only', 'Only reconciliation references may be updated here.')
        version = body.get('rowVersion')
        if type(version) is not int or version < 1:
            return _error(400, 'row_version_required', 'A valid rowVersion is required.')
        if not {'statementNo', 'reinsurers'} & body.keys():
            return _error(400, 'references_required', 'Provide Statement No. or Reinsurer Ref.')
        try:
            with serialized(PRODUCTION_SOURCES):
                case, error = self._case(request, body.get('caseUid'), lock=True)
                if error is not None:
                    return error
                if case.row_version != version:
                    return _error(409, 'version_conflict', 'This case changed. Reopen the reference editor before saving.')
                before = _references(case)
                payload = copy.deepcopy(case.payload)
                try:
                    if 'statementNo' in body:
                        payload['statementNo'] = _text(body['statementNo'])
                    if 'reinsurers' in body:
                        changes = body['reinsurers']
                        if not isinstance(changes, list):
                            raise ValueError('Reinsurer references must be a list.')
                        rows = payload.get('reinsurers')
                        rows = rows if isinstance(rows, list) else []
                        seen = set()
                        for item in changes:
                            if not isinstance(item, dict) or set(item) != {'index', 'settlementRef'}:
                                raise ValueError('Provide only the reinsurer index and reference.')
                            index = item['index']
                            if type(index) is not int or index < 0 or index >= len(rows) or index in seen or not isinstance(rows[index], dict):
                                raise ValueError('The selected reinsurer is invalid. Reopen the reference editor.')
                            seen.add(index)
                            rows[index]['settlementRef'] = _text(item['settlementRef'])
                except ValueError as exc:
                    return _error(400, 'invalid_reference', str(exc))
                if payload == case.payload:
                    return Response({'ok': True, 'changed': False, 'case': before})
                actor = actor_from(request.ri_principal)
                case.payload = payload
                case.row_version += 1
                case.updated_by = actor['id']
                case.save(update_fields=['payload', 'row_version', 'updated_by', 'updated_at'])
                after = _references(case)
                record_snapshot(entity_type='case', entity_id=case.case_uid, version=case.row_version,
                                reason='reconciliation_references_updated',
                                data={'caseUid': str(case.case_uid), 'twRef': case.tw_ref, 'status': case.status,
                                      'rowVersion': case.row_version, 'payload': payload}, created_by=actor['id'])
                record_audit(entity_type='case', entity_id=case.case_uid, action='update_reconciliation_references',
                             before=before, after=after, actor=actor, request_id=request_id_from(request))
                return Response({'ok': True, 'changed': True, 'case': after})
        except IntegrityError:
            return _error(409, 'reference_conflict', 'This case changed. Reopen the reference editor before saving.')
