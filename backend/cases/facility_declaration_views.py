"""Facility Declaration Draft API.

Posting is intentionally not exposed until the accounting integration is ready.
"""
from copy import deepcopy
from uuid import UUID
from django.db import IntegrityError, transaction

from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from coordination.services import PRODUCTION_SOURCES, serialized
from ri_system.authz import NoStoreMixin, RIPermission, actor_from, has_permission
from .facility_placement import validate_declaration
from .models import Case, FacilityDeclaration
from .views import visible_cases


def error(status, code, message):
    return Response({'error': code, 'message': message}, status=status)


def parsed(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def state(row):
    return {'declarationUid': str(row.declaration_uid), 'facilityUid': str(row.facility.case_uid),
            'status': row.status, 'rowVersion': row.row_version, 'statementNo': row.statement_no,
            'periodFrom': row.period_from.isoformat(), 'periodTo': row.period_to.isoformat(),
            'payload': deepcopy(row.payload), 'announcedAt': row.announced_at,
            'createdAt': row.created_at, 'updatedAt': row.updated_at}


class FacilityDeclarationsView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'GET': 'dashboard.read', 'POST': 'cases.write', 'PUT': 'cases.write'}

    def get(self, request):
        if not (has_permission(request.ri_principal, 'cases.read.all') or has_permission(request.ri_principal, 'cases.read.own')):
            return error(403, 'permission_denied', 'You do not have permission to read cases.')
        uid = parsed(request.query_params.get('facilityUid'))
        facility = visible_cases(request.ri_principal).filter(case_uid=uid, reinsurance_structure='FACILITY').first() if uid else None
        if facility is None:
            return error(404, 'facility_not_found', 'Facility was not found.')
        rows = facility.facility_declarations.select_related('facility').order_by('period_from', 'id')
        return Response({'ok': True, 'declarations': [state(row) for row in rows]})

    def post(self, request):
        return self._save(request, False)

    def put(self, request):
        return self._save(request, True)

    def _save(self, request, editing):
        body = request.data if isinstance(request.data, dict) else {}
        uid = parsed(body.get('facilityUid'))
        declaration_uid = parsed(body.get('declarationUid')) if editing else None
        if not uid or (editing and not declaration_uid):
            return error(400, 'invalid_reference', 'A valid Facility and Declaration reference is required.')
        input_data = body.get('declaration')
        if not isinstance(input_data, dict):
            return error(400, 'invalid_declaration', 'Declaration data is required.')
        actor = actor_from(request.ri_principal)
        with serialized(PRODUCTION_SOURCES):
            facility = visible_cases(request.ri_principal).select_for_update().filter(case_uid=uid, reinsurance_structure='FACILITY').first()
            if facility is None:
                return error(404, 'facility_not_found', 'Facility was not found.')
            if facility.status not in ('posted', 'closed'):
                return error(409, 'facility_not_announced', 'The Facility must be Announced first.')
            queryset = FacilityDeclaration.objects.select_for_update().filter(facility=facility)
            current = queryset.filter(declaration_uid=declaration_uid).select_related('facility').first() if editing else None
            if editing and current is None:
                return error(404, 'declaration_not_found', 'Declaration was not found.')
            if editing and current.status == 'posted':
                return self._correct_open(request, body, actor, facility, current, queryset, input_data)
            if editing and current.status != 'draft':
                return error(409, 'declaration_not_draft', 'This Declaration cannot be edited as a Draft.')
            if editing and (isinstance(body.get('rowVersion'), bool) or body.get('rowVersion') != current.row_version):
                return error(409, 'version_conflict', 'This Declaration changed. Reload before saving.')
            others = [{'id': str(r.declaration_uid), 'periodFrom': r.period_from.isoformat(),
                       'periodTo': r.period_to.isoformat(), 'statementNo': r.statement_no} for r in queryset]
            try:
                checked = validate_declaration(facility.payload, input_data, others,
                                               exclude_id=str(current.declaration_uid) if current else None)
            except (ValueError, TypeError) as exc:
                return error(400, 'validation_failed', str(exc))
            before = state(current) if current else None
            value = {'premium': str(input_data.get('premium') or '0').replace(',', ''),
                     'claim': str(input_data.get('claim') or '0').replace(',', ''), 'dueDate': checked['dueDate']}
            if current is None:
                current = FacilityDeclaration(facility=facility, created_by=actor['id'])
            else:
                current.row_version += 1
            current.statement_no = str(input_data.get('statementNo') or '').strip()
            current.period_from = checked['periodFrom']
            current.period_to = checked['periodTo']
            current.payload = value
            current.updated_by = actor['id']
            try:
                with transaction.atomic():
                    current.save()
            except IntegrityError:
                return error(409, 'statement_conflict', 'This Cedant Statement No. is already used for this Facility.')
            current.refresh_from_db()
            current.facility = facility
            after = state(current)
            record_snapshot(entity_type='facility_declaration', entity_id=current.declaration_uid,
                            version=current.row_version, reason='draft_saved', data=after, created_by=actor['id'])
            record_audit(entity_type='facility_declaration', entity_id=current.declaration_uid,
                         action='update_draft' if editing else 'create_draft', before=before, after=after,
                         actor=actor, request_id=request_id_from(request))
        return Response({'ok': True, 'declaration': after}, status=200 if editing else 201)

    def _correct_open(self, request, body, actor, facility, current, queryset, data):
        from django.utils import timezone
        from production.models import ProductionReport
        from .cash_ledger import transaction_details
        from .finance_workflow import active_reviews
        from .facility_declaration_ledger import transactions, corrected_transactions

        if isinstance(body.get('rowVersion'), bool) or body.get('rowVersion') != current.row_version:
            return error(409, 'version_conflict', 'This Declaration changed. Reload before editing.')
        month = current.payload.get('latestRevenueMonth') or current.payload.get('revenueMonth')
        if not month:
            return error(409, 'revenue_month_missing', 'The Declaration Revenue Month is missing.')
        is_closed = ProductionReport.objects.filter(year_month=month, status='closed').exists()
        prior_numbers = set(current.payload.get('transactionNumbers') or [])
        ledger = facility.payload.get('transactions') or []
        prior = [row for row in ledger if row.get('txNo') in prior_numbers]
        if len(prior) != len(prior_numbers) or not prior:
            return error(409, 'transaction_history_invalid', 'Declaration transactions are incomplete; review before correcting.')
        details = transaction_details(facility.payload)
        reviewed = active_reviews({str(facility.case_uid)})
        if any((str(facility.case_uid), no) in reviewed for no in prior_numbers):
            return error(409, 'finance_review_required', 'Cancel the Finance review before changing the Declaration.')
        if any(abs(details.get(no, {}).get('paid', 0)) > .004 for no in prior_numbers):
            return error(409, 'cash_activity_locked', 'Reverse active receipts or payments before changing the Declaration.')
        others = [{'id': str(row.declaration_uid), 'periodFrom': row.period_from.isoformat(),
                   'periodTo': row.period_to.isoformat(), 'statementNo': row.statement_no} for row in queryset]
        try:
            checked = validate_declaration(facility.payload, data, others, exclude_id=str(current.declaration_uid))
            normalized = {'periodFrom': checked['periodFrom'], 'periodTo': checked['periodTo'],
                          'dueDate': checked['dueDate'], 'statementNo': str(data.get('statementNo') or '').strip(),
                          'premium': str(data.get('premium') or '0').replace(',', ''),
                          'claim': str(data.get('claim') or '0').replace(',', '')}
            source = {**(current.payload.get('facilityTermsSnapshot') or {}), 'twRef': facility.tw_ref}
            now = timezone.now()
            target_month = month
            if is_closed:
                from datetime import timedelta
                from production.calc import is_historical, next_production_month
                from .facility_placement import revenue_month
                local = timezone.localtime(now).date()
                closed = set(ProductionReport.objects.filter(status='closed').values_list('year_month', flat=True))
                prior_month = (local.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
                if is_historical(prior_month): closed.add(prior_month)
                try:
                    target_month = revenue_month(local, closed)
                except ValueError:
                    target_month = local.strftime('%Y-%m')
                    while target_month in closed or is_historical(target_month):
                        target_month = next_production_month(target_month)
            replacement = transactions(source, normalized, str(current.declaration_uid), now.isoformat(), target_month)
            correction_events = deepcopy(current.payload.get('productionCorrections') or [])
            if is_closed:
                revision = len(correction_events) + 1
                corrected = corrected_transactions(prior, replacement, revision, True)
                replacement = [row for row in corrected if row.get('correctionRevision') == revision]
                correction_events.append({'revision': revision, 'month': target_month,
                    'oldRows': deepcopy(current.payload.get('productionRecognition') or []),
                    'transactionNumbers': [row['txNo'] for row in replacement]})
                replacement_ledger = corrected
            else:
                # Keep active account numbers stable when changing an open correction.
                by_leg = {(row.get('reinsurerIdx'), row.get('legType')): row['txNo'] for row in prior}
                replacement = [{**row, 'txNo': by_leg.get((row.get('reinsurerIdx'), row.get('legType')), row['txNo'])} for row in replacement]
                replacement_ledger = replacement
                if correction_events and correction_events[-1].get('month') == month and not correction_events[-1].get('closed'):
                    correction_events[-1]['transactionNumbers'] = [row['txNo'] for row in replacement]
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return error(400, 'validation_failed', str(exc))
        before = state(current)
        old_case = deepcopy(facility.payload)
        current.statement_no = normalized['statementNo']
        current.period_from = normalized['periodFrom']
        current.period_to = normalized['periodTo']
        current.payload = {**current.payload, 'premium': normalized['premium'], 'claim': normalized['claim'],
                           'dueDate': normalized['dueDate'], 'transactionNumbers': [row['txNo'] for row in replacement],
                           'latestRevenueMonth': target_month, 'productionCorrections': correction_events,
                           **({'initialProductionRecognition': deepcopy(current.payload.get('initialProductionRecognition', current.payload.get('productionRecognition') or []))} if is_closed else {})}
        current.row_version += 1
        current.updated_by = actor['id']
        try:
            with transaction.atomic():
                current.save()
        except IntegrityError:
            return error(409, 'statement_conflict', 'This Cedant Statement No. is already used for this Facility.')
        current.refresh_from_db()
        current.facility = facility
        facility.payload = {**facility.payload, 'transactions': [row for row in ledger if row.get('txNo') not in prior_numbers] + replacement_ledger}
        facility.row_version += 1
        facility.updated_by = actor['id']
        facility.save(update_fields=['payload', 'row_version', 'updated_by', 'updated_at'])
        after = state(current)
        record_snapshot(entity_type='facility_declaration', entity_id=current.declaration_uid, version=current.row_version,
                        reason='closed_correction' if is_closed else 'open_correction', data=after, created_by=actor['id'])
        record_audit(entity_type='facility_declaration', entity_id=current.declaration_uid, action='correct_closed' if is_closed else 'correct_open',
                     before=before, after=after, actor=actor, request_id=request_id_from(request))
        record_audit(entity_type='case', entity_id=facility.case_uid, action='declaration_corrected',
                     before={'payload': old_case}, after={'payload': facility.payload}, actor=actor,
                     request_id=request_id_from(request), metadata={'declarationUid': str(current.declaration_uid)})
        return Response({'ok': True, 'declaration': after, 'caseRowVersion': facility.row_version})


class FacilityDeclarationAnnounceView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'POST': 'cases.announce'}

    def post(self, request):
        from django.utils import timezone
        from production.calc import is_historical, next_production_month
        from production.models import ProductionReport
        from . import storage
        from .facility_placement import revenue_month
        from .facility_declaration_ledger import transactions

        body = request.data if isinstance(request.data, dict) else {}
        facility_uid, declaration_uid = parsed(body.get('facilityUid')), parsed(body.get('declarationUid'))
        if not facility_uid or not declaration_uid:
            return error(400, 'invalid_reference', 'Valid Facility and Declaration references are required.')
        if body.get('confirmed') is not True:
            return error(400, 'confirmation_required', 'Review and confirm the Declaration before Announce.')
        actor = actor_from(request.ri_principal)
        with serialized(PRODUCTION_SOURCES):
            facility = visible_cases(request.ri_principal).select_for_update().filter(case_uid=facility_uid, reinsurance_structure='FACILITY').first()
            if not facility:
                return error(404, 'facility_not_found', 'Facility was not found.')
            if facility.status not in ('posted', 'closed') or not facility.tw_ref:
                return error(409, 'facility_not_announced', 'The Facility must be Announced first.')
            current = FacilityDeclaration.objects.select_for_update().select_related('facility').filter(
                facility=facility, declaration_uid=declaration_uid).first()
            if not current:
                return error(404, 'declaration_not_found', 'Declaration was not found.')
            if current.status != 'draft':
                return error(409, 'declaration_not_draft', 'Only a Draft Declaration can be Announced.')
            if isinstance(body.get('rowVersion'), bool) or body.get('rowVersion') != current.row_version:
                return error(409, 'version_conflict', 'This Declaration changed. Reload before Announce.')
            evidence = list(current.documents.all())
            if not evidence or not all(storage.exists(item.storage_key) for item in evidence):
                return error(400, 'evidence_required', 'Upload available evidence before Announce.')
            siblings = [{'id': str(row.declaration_uid), 'periodFrom': row.period_from.isoformat(),
                         'periodTo': row.period_to.isoformat(), 'statementNo': row.statement_no}
                        for row in FacilityDeclaration.objects.filter(facility=facility)]
            data = {'periodFrom': current.period_from.isoformat(), 'periodTo': current.period_to.isoformat(),
                    'statementNo': current.statement_no, 'premium': current.payload.get('premium'),
                    'claim': current.payload.get('claim')}
            try:
                checked = validate_declaration(facility.payload, data, siblings, exclude_id=str(current.declaration_uid))
                now = timezone.now()
                local = timezone.localtime(now).date()
                closed = set(ProductionReport.objects.filter(status='closed').values_list('year_month', flat=True))
                from datetime import timedelta
                prior = (local.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
                if is_historical(prior):
                    closed.add(prior)
                try:
                    month = revenue_month(local, closed)
                except ValueError:
                    month = local.strftime('%Y-%m')
                    while month in closed or is_historical(month):
                        month = next_production_month(month)
                source = {**facility.payload, 'twRef': facility.tw_ref}
                entries = transactions(source, {**data, 'dueDate': checked['dueDate']}, str(current.declaration_uid), now.isoformat(), month)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                return error(400, 'declaration_not_ready', str(exc))
            old = state(current)
            old_case_payload = deepcopy(facility.payload)
            current.payload = {**current.payload, 'dueDate': checked['dueDate'], 'revenueMonth': month,
                               'facilityTermsSnapshot': deepcopy(facility.payload),
                               'documentIds': [str(item.pk) for item in evidence],
                               'transactionNumbers': [item['txNo'] for item in entries]}
            current.status = 'posted'
            current.announced_at = now
            current.announced_by = actor['id']
            current.updated_by = actor['id']
            current.row_version += 1
            current.save()
            facility.payload = {**facility.payload, 'transactions': [*(facility.payload.get('transactions') or []), *entries]}
            facility.row_version += 1
            facility.updated_by = actor['id']
            facility.save(update_fields=['payload', 'row_version', 'updated_by', 'updated_at'])
            after = state(current)
            record_snapshot(entity_type='facility_declaration', entity_id=current.declaration_uid,
                            version=current.row_version, reason='announced', data=after, created_by=actor['id'])
            record_audit(entity_type='facility_declaration', entity_id=current.declaration_uid,
                         action='announce', before=old, after=after, actor=actor, request_id=request_id_from(request),
                         metadata={'revenueMonth': month, 'caseVersion': facility.row_version})
            record_audit(entity_type='case', entity_id=facility.case_uid, action='declaration_announced',
                         before={'payload': old_case_payload}, after={'payload': facility.payload}, actor=actor,
                         request_id=request_id_from(request), metadata={'declarationUid': str(current.declaration_uid)})
        return Response({'ok': True, 'declaration': after, 'caseRowVersion': facility.row_version})
