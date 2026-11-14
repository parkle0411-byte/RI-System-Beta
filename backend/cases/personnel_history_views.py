"""Explicit, audited links between legacy case names and Personnel records."""
import copy
import uuid

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from coordination.services import PRODUCTION_SOURCES, serialized
from personnel.models import Personnel
from ri_system.authz import NoStoreMixin, RIPermission, actor_from
from .views import visible_cases


def error(status, code, message):
    return Response({'error': code, 'message': message}, status=status)


class CasePersonnelHistoryView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'GET': 'cases.write', 'POST': 'cases.write'}

    def find(self, request, raw_uid, *, lock=False):
        try:
            uid = uuid.UUID(str(raw_uid))
        except (ValueError, TypeError, AttributeError):
            return None
        query = visible_cases(request.ri_principal)
        if lock:
            query = query.select_for_update()
        return query.filter(case_uid=uid).first()

    @staticmethod
    def permitted(person, case):
        return person.role_code in ('general_manager', 'admin') or bool(case.owner_personnel_id and case.owner_personnel_id == person.pk)

    def get(self, request):
        case = self.find(request, request.query_params.get('caseUid'))
        if not case:
            return error(404, 'case_not_found', 'Case was not found.')
        if not self.permitted(request.ri_principal, case):
            return error(403, 'identity_permission_denied', 'Only the Case Owner, General Manager or System Administrator may confirm historical identities.')
        people = Personnel.objects.order_by('name', 'department', 'id').values('id', 'name', 'department', 'role_code', 'is_active', 'account_status')
        return Response({'people': list(people), 'history': (case.payload or {}).get('personnelIdentityHistory') or [], 'rowVersion': case.row_version})

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        with serialized(PRODUCTION_SOURCES):
            case = self.find(request, body.get('caseUid'), lock=True)
            if not case:
                return error(404, 'case_not_found', 'Case was not found.')
            if not self.permitted(request.ri_principal, case):
                return error(403, 'identity_permission_denied', 'Only the Case Owner, General Manager or System Administrator may confirm historical identities.')
            if isinstance(body.get('rowVersion'), bool) or body.get('rowVersion') != case.row_version:
                return error(409, 'version_conflict', 'This case changed elsewhere. Reload and try again.')
            field = body.get('field')
            if field not in ('ae', 'owner'):
                return error(400, 'invalid_identity_field', 'Select Account Executive or Case Owner.')
            try:
                person_id = int(body.get('personnelId'))
                if isinstance(body.get('personnelId'), bool) or person_id < 1 or str(body.get('personnelId')).strip() != str(person_id):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                return error(400, 'invalid_personnel', 'Select an existing Personnel record.')
            target = Personnel.objects.filter(pk=person_id).first()
            if not target:
                return error(400, 'invalid_personnel', 'Select an existing Personnel record.')
            payload = copy.deepcopy(case.payload or {})
            if payload.get('personnelIdentityVersion') == 'personnel-v1':
                return error(409, 'historical_link_not_applicable', 'This case uses Personnel identities. Change its assignment through the normal Case editor.')
            id_key, name_key = ('aePersonnelId', 'ae') if field == 'ae' else ('ownerPersonnelId', 'ownerPersonnelName')
            old_id = case.ae_personnel_id if field == 'ae' else case.owner_personnel_id
            historical_name = str(payload.get(name_key) or '').strip()
            reason = str(body.get('reason') or '').strip()
            name_changed = historical_name.casefold() != target.name.strip().casefold()
            if (name_changed or old_id is not None and old_id != target.pk) and not reason:
                return error(400, 'reason_required', 'Enter a reason when names differ or an existing link is corrected.')
            if name_changed and body.get('confirmed') is not True:
                return error(400, 'confirmation_required', 'Confirm the historical name and selected Personnel are the same person.')
            if old_id == target.pk:
                return Response({'ok': True, 'unchanged': True, 'rowVersion': case.row_version})
            actor = actor_from(request.ri_principal)
            now = timezone.now().isoformat()
            entry = {'field': field, 'beforePersonnelId': old_id, 'afterPersonnelId': target.pk,
                     'historicalName': historical_name, 'personnelName': target.name, 'reason': reason,
                     'changedBy': actor['id'], 'changedByName': actor['name'], 'changedAt': now}
            payload[id_key] = target.pk
            payload.setdefault('personnelIdentityHistory', []).append(entry)
            if isinstance(payload.get('draftInput'), dict):
                payload['draftInput'][id_key] = target.pk
            if field == 'ae':
                case.ae_personnel_id = target.pk
            else:
                case.owner_personnel_id = target.pk
            case.payload = payload
            case.row_version += 1
            case.updated_by = actor['id']
            case.save()
            record_snapshot(entity_type='case', entity_id=case.case_uid, version=case.row_version, reason='historical_personnel_link', data={'caseUid': str(case.case_uid), 'payload': payload}, created_by=actor['id'])
            record_audit(entity_type='case', entity_id=case.case_uid, action='historical_personnel_link', before={'field': field, 'personnelId': old_id, 'historicalName': historical_name}, after=entry, actor=actor, request_id=request_id_from(request))
            return Response({'ok': True, 'rowVersion': case.row_version, 'entry': entry})
