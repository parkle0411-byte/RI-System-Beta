"""Save Facility Placement drafts without creating insured masters or accounting."""
from copy import deepcopy
from uuid import UUID

from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from coordination.services import PRODUCTION_SOURCES, serialized
from ri_system.authz import NoStoreMixin, RIPermission, actor_from
from .facility_placement import normalize_facility_draft, validate_facility
from .models import Case
from .personnel_identity import assign_creator, resolve_ae
from .resolve import resolve_case_owner, resolve_master_references
from .views import visible_cases


def err(status, code, message):
    return Response({'error': code, 'message': message}, status=status)


def snapshot(case):
    return {'caseUid': str(case.case_uid), 'status': case.status, 'rowVersion': case.row_version,
            'reinsuranceStructure': case.reinsurance_structure, 'payload': deepcopy(case.payload)}


class FacilityPlacementView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'POST': 'cases.write', 'PUT': 'cases.write'}

    def post(self, request):
        return self.save_draft(request, False)

    def put(self, request):
        return self.save_draft(request, True)

    def save_draft(self, request, editing):
        body = request.data if isinstance(request.data, dict) else {}
        try:
            payload = normalize_facility_draft(body.get('case'))
            uid = UUID(str(body.get('caseUid'))) if editing else None
        except (ValueError, TypeError) as exc:
            return err(400, 'validation_failed', str(exc))
        actor = actor_from(request.ri_principal)
        with serialized(PRODUCTION_SOURCES):
            current = visible_cases(request.ri_principal).select_for_update().filter(case_uid=uid, reinsurance_structure='FACILITY').first() if editing else None
            if editing and current is None:
                return err(404, 'facility_not_found', 'Facility was not found.')
            if current and (isinstance(body.get('rowVersion'), bool) or body.get('rowVersion') != current.row_version):
                return err(409, 'version_conflict', 'This Facility changed. Reload before saving.')
            if current and current.status in ('posted', 'closed'):
                return self.update_announced(request, current, payload, actor)
            if current and current.status != 'draft':
                return err(409, 'facility_not_draft', 'This Facility cannot be edited.')
            before = snapshot(current) if current else None
            if not current:
                owner = payload.get('ownerPersonnelId')
                ae = payload.get('aePersonnelId')
                try:
                    assign_creator(payload, request.ri_principal)
                except ValueError as exc:
                    return err(403, 'draft_creator_ineligible', str(exc))
                if owner:
                    payload['ownerPersonnelId'] = owner
                if ae:
                    payload['aePersonnelId'] = ae
            owner = resolve_case_owner(payload, current.owner_personnel_id if current else None)
            if 'error' in owner:
                return Response(owner, status=400)
            ae = resolve_ae(payload, current=current)
            if 'error' in ae:
                return Response(ae, status=400)
            masters = resolve_master_references(payload)
            if not current:
                current = Case(reinsurance_structure='FACILITY', case_kind='original', status='draft',
                               created_by=actor['id'])
            else:
                current.row_version += 1
            current.class_master_id = masters['classMasterId']
            current.class_name_snapshot = payload.get('classOfBusiness') or None
            current.class_code_snapshot = payload.get('classCode') or None
            current.reinsured_master_id = masters['reinsuredMasterId']
            current.reinsured_name_snapshot = payload.get('reinsured') or None
            current.owner_personnel_id = owner['id']
            current.ae_personnel_id = ae['id']
            current.ae_name_snapshot = payload.get('ae') or None
            current.currency = payload.get('currency') or None
            current.effective_date = payload.get('policyFrom') or None
            current.expiration_date = payload.get('policyTo') or None
            current.payload = payload
            current.updated_by = actor['id']
            current.save()
            after = snapshot(current)
            record_snapshot(entity_type='case', entity_id=current.case_uid, version=current.row_version,
                            reason='draft_created' if not editing else 'facility_draft_saved', data=after, created_by=actor['id'])
            record_audit(entity_type='case', entity_id=current.case_uid, action='create_draft' if not editing else 'update_draft',
                         before=before, after=after, actor=actor, request_id=request_id_from(request))
        return Response({'ok': True, 'case': {'caseUid': str(current.case_uid), 'status': current.status,
                                               'rowVersion': current.row_version}}, status=200 if editing else 201)

    def update_announced(self, request, current, payload, actor):
        previous = normalize_facility_draft(current.payload)
        old_rows, new_rows = previous.get('reinsurers', []), payload.get('reinsurers', [])
        if len(old_rows) != len(new_rows):
            return err(409, 'facility_terms_locked', 'Reinsurer terms are locked after Announce.')
        for old, new in zip(old_rows, new_rows):
            if {k: v for k, v in old.items() if k != 'facilityReference'} != {k: v for k, v in new.items() if k != 'facilityReference'}:
                return err(409, 'facility_terms_locked', 'Reinsurer terms are locked after Announce.')
            if not new.get('facilityReference'):
                return err(400, 'reference_required', 'Each Reinsurer requires a reference number.')
        allowed = {'reinsurers', 'policyFrom'}
        if any(previous.get(k) != payload.get(k) for k in set(previous) | set(payload) if k not in allowed):
            return err(409, 'facility_terms_locked', 'Only Reinsurer references and the Facility start date may be changed after Announce.')
        before = snapshot(current)
        try:
            validate_facility(payload)
        except (ValueError, TypeError) as exc:
            return err(400, 'validation_failed', str(exc))
        declarations = current.facility_declarations.select_for_update().order_by('period_from', 'id')
        first = declarations.first()
        if first and payload.get('policyFrom') != first.period_from.isoformat():
            from .facility_declaration_views import FacilityDeclarationsView, state
            from .facility_placement import validate_declaration
            data = {'periodFrom': payload['policyFrom'], 'periodTo': first.period_to.isoformat(),
                    'statementNo': first.statement_no, 'premium': first.payload.get('premium'),
                    'claim': first.payload.get('claim')}
            others = [{'id': str(row.declaration_uid), 'periodFrom': row.period_from.isoformat(),
                       'periodTo': row.period_to.isoformat(), 'statementNo': row.statement_no} for row in declarations]
            proposed = {**current.payload, 'policyFrom': payload['policyFrom']}
            try:
                checked = validate_declaration(proposed, data, others, exclude_id=str(first.declaration_uid))
            except (ValueError, TypeError) as exc:
                return err(400, 'validation_failed', str(exc))
            if first.status == 'posted':
                # Reuse the normal correction path, including close, Finance and cash safeguards.
                current.payload = proposed
                result = FacilityDeclarationsView()._correct_open(request, {'rowVersion': first.row_version},
                                                                 actor, current, first, declarations, data)
                if result.status_code != 200:
                    return result
            elif first.status == 'draft':
                first.facility = current
                old_declaration = state(first)
                first.period_from = checked['periodFrom']
                first.row_version += 1
                first.updated_by = actor['id']
                first.save()
                first.refresh_from_db()
                first.facility = current
                new_declaration = state(first)
                record_snapshot(entity_type='facility_declaration', entity_id=first.declaration_uid,
                                version=first.row_version, reason='facility_start_updated', data=new_declaration, created_by=actor['id'])
                record_audit(entity_type='facility_declaration', entity_id=first.declaration_uid,
                             action='facility_start_updated', before=old_declaration, after=new_declaration,
                             actor=actor, request_id=request_id_from(request))
            else:
                return err(409, 'declaration_locked', 'The first Declaration cannot be corrected in its current status.')
        stored = deepcopy(current.payload)
        stored['policyFrom'] = payload.get('policyFrom')
        for old, new in zip(stored.get('reinsurers') or [], new_rows):
            old['facilityReference'] = new['facilityReference']
        current.payload = stored
        current.effective_date = payload.get('policyFrom') or None
        current.row_version += 1
        current.updated_by = actor['id']
        current.save()
        after = snapshot(current)
        record_snapshot(entity_type='case', entity_id=current.case_uid, version=current.row_version,
                        reason='facility_terms_updated', data=after, created_by=actor['id'])
        record_audit(entity_type='case', entity_id=current.case_uid, action='facility_terms_updated',
                     before=before, after=after, actor=actor, request_id=request_id_from(request))
        return Response({'ok': True, 'case': {'caseUid': str(current.case_uid), 'status': current.status, 'rowVersion': current.row_version}})


class FacilityAnnounceView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'POST': 'cases.announce'}

    def post(self, request):
        from django.db import connection
        from django.utils import timezone
        from .manual_reference import reference_in_use
        from .workflow import reference_prefix
        body = request.data if isinstance(request.data, dict) else {}
        try:
            uid = UUID(str(body.get('caseUid')))
        except (ValueError, TypeError):
            return err(400, 'invalid_reference', 'A valid Facility reference is required.')
        if body.get('confirmed') is not True:
            return err(400, 'confirmation_required', 'Review and confirm the Facility before Announce.')
        actor = actor_from(request.ri_principal)
        with serialized(PRODUCTION_SOURCES):
            current = visible_cases(request.ri_principal).select_for_update().filter(case_uid=uid, reinsurance_structure='FACILITY').first()
            if not current:
                return err(404, 'facility_not_found', 'Facility was not found.')
            if current.status != 'draft':
                return err(409, 'facility_not_draft', 'Only a Draft Facility can be Announced.')
            if isinstance(body.get('rowVersion'), bool) or body.get('rowVersion') != current.row_version:
                return err(409, 'version_conflict', 'This Facility changed. Reload before Announce.')
            try:
                ready = validate_facility(current.payload)
            except (ValueError, TypeError) as exc:
                return err(400, 'facility_not_ready', str(exc))
            if not current.owner_personnel_id or not current.ae_personnel_id:
                return err(400, 'personnel_required', 'A Case Owner and Account Executive are required.')
            prefix = reference_prefix(current.payload)
            if not prefix:
                return err(400, 'effective_date_required', 'A valid Facility start date is required.')
            now = timezone.now()
            before = snapshot(current)
            while True:
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO ri_reference_sequences (prefix, `last_value`, updated_at) VALUES (%s, 1, %s) AS new ON DUPLICATE KEY UPDATE `last_value` = ri_reference_sequences.`last_value` + 1, updated_at = new.updated_at', [prefix, now])
                    cursor.execute('SELECT `last_value` FROM ri_reference_sequences WHERE prefix = %s', [prefix])
                    reference = prefix + str(cursor.fetchone()[0]).zfill(3)
                if not reference_in_use(reference):
                    break
            current.tw_ref = reference
            current.status = 'posted'
            current.announced_at = now
            current.announced_by = actor['id']
            current.updated_by = actor['id']
            current.row_version += 1
            current.payload = {**current.payload, 'type': ready['type'], 'twRefSource': 'system'}
            current.save()
            after = snapshot(current)
            after['twRef'] = reference
            record_snapshot(entity_type='case', entity_id=current.case_uid, version=current.row_version,
                            reason='announced', data=after, created_by=actor['id'])
            record_audit(entity_type='case', entity_id=current.case_uid, action='announce', before=before, after=after,
                         actor=actor, request_id=request_id_from(request))
        return Response({'ok': True, 'case': {'caseUid': str(current.case_uid), 'twRef': reference,
                                               'status': current.status, 'rowVersion': current.row_version}})


class FacilityRenewalView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'POST': 'cases.write'}

    def post(self, request):
        from .workflow import shift_year
        body = request.data if isinstance(request.data, dict) else {}
        try:
            uid = UUID(str(body.get('caseUid')))
        except (ValueError, TypeError):
            return err(400, 'invalid_reference', 'A valid Facility reference is required.')
        actor = actor_from(request.ri_principal)
        with serialized(PRODUCTION_SOURCES):
            source = visible_cases(request.ri_principal).select_for_update().filter(case_uid=uid, reinsurance_structure='FACILITY').first()
            if not source:
                return err(404, 'facility_not_found', 'Facility was not found.')
            if source.status not in ('posted', 'closed') or not source.tw_ref:
                return err(409, 'renewal_source_status', 'Only an Announced Facility can be renewed.')
            if isinstance(body.get('rowVersion'), bool) or body.get('rowVersion') != source.row_version:
                return err(409, 'version_conflict', 'This Facility changed. Reload before renewal.')
            if Case.objects.filter(recycled_at__isnull=True, is_archived=False, payload__renewedFromTwRef=source.tw_ref).exists():
                return err(409, 'renewal_already_exists', 'A renewal already exists for this Facility.')
            payload = normalize_facility_draft(source.payload)
            payload.update(renewedFromTwRef=source.tw_ref, newOrRenew='Renew',
                           policyFrom=source.payload.get('policyTo') or '', policyTo=shift_year(source.payload.get('policyTo') or ''))
            try:
                assign_creator(payload, request.ri_principal)
            except ValueError as exc:
                return err(403, 'draft_creator_ineligible', str(exc))
            row = Case.objects.create(case_kind='renewal', status='draft', reinsurance_structure='FACILITY',
                class_master_id=source.class_master_id, class_code_snapshot=source.class_code_snapshot,
                class_name_snapshot=source.class_name_snapshot, reinsured_master_id=source.reinsured_master_id,
                reinsured_name_snapshot=source.reinsured_name_snapshot, currency=source.currency,
                ae_personnel_id=payload['aePersonnelId'], ae_name_snapshot=payload['ae'],
                owner_personnel_id=payload['ownerPersonnelId'], effective_date=payload['policyFrom'] or None,
                expiration_date=payload['policyTo'] or None, payload=payload,
                created_by=actor['id'], updated_by=actor['id'])
            after = snapshot(row)
            record_snapshot(entity_type='case', entity_id=row.case_uid, version=1, reason='renewal_created', data=after, created_by=actor['id'])
            record_audit(entity_type='case', entity_id=row.case_uid, action='create_renewal',
                         before={'sourceCaseUid': str(source.case_uid), 'sourceTwRef': source.tw_ref},
                         after=after, actor=actor, request_id=request_id_from(request))
        return Response({'ok': True, 'case': {'caseUid': str(row.case_uid), 'status': row.status, 'rowVersion': row.row_version}}, status=201)
