"""Renewal Claim snapshots and field-level source synchronization."""
import copy
import uuid
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from audit.services import record_audit, record_snapshot, request_id_from
from coordination.services import PRODUCTION_SOURCES, serialized
from ri_system.authz import NoStoreMixin, RIPermission, actor_from
from .claim_currency import CURRENCIES, valid_amount
from .claim_loss_record import plan_snapshot_sync, retry_snapshot_sync
from .claims_views import _real_date
from .models import Case


def error(status, code, message):
    return Response({'error': code, 'message': message}, status=status)


class ClaimLossSnapshotView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {'POST': 'cases.write'}

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        try:
            uid = uuid.UUID(str(body.get('caseUid') or ''))
            version = int(body.get('rowVersion'))
            index = int(body.get('index'))
        except (ValueError, TypeError, AttributeError):
            return error(400, 'invalid_snapshot_request', 'Enter a valid case, version and snapshot index.')
        action = body.get('action')
        if action not in ('edit', 'retry') or index < 0:
            return error(400, 'invalid_snapshot_request', 'Select a valid snapshot action.')
        actor = actor_from(request.ri_principal)
        with serialized(PRODUCTION_SOURCES):
            renewal = Case.objects.select_for_update().filter(case_uid=uid, recycled_at__isnull=True, is_archived=False).first()
            if not renewal or renewal.case_kind != 'renewal':
                return error(404, 'snapshot_not_found', 'The renewal snapshot is unavailable.')
            if renewal.row_version != version:
                return error(409, 'version_conflict', 'The renewal changed. Reload before retrying.')
            if action == 'edit' and renewal.status != 'draft':
                return error(409, 'snapshot_not_editable', 'Edit renewal loss details while the renewal is a Draft.')
            payload = copy.deepcopy(renewal.payload or {})
            snapshots = payload.get('claimLossSnapshots')
            if not isinstance(snapshots, list) or index >= len(snapshots) or not isinstance(snapshots[index], dict):
                return error(404, 'snapshot_not_found', 'The renewal snapshot is unavailable.')
            before = copy.deepcopy(snapshots[index])
            try:
                source_uid = uuid.UUID(str(before.get('sourceCaseUid') or ''))
            except (ValueError, TypeError, AttributeError):
                source_uid = None
            source = Case.objects.select_for_update().filter(case_uid=source_uid, recycled_at__isnull=True, is_archived=False).first() if source_uid else None
            source_payload = copy.deepcopy(source.payload or {}) if source else {}
            source_claim = next((row for row in source_payload.get('claims') or [] if isinstance(row, dict) and str(row.get('id')) == str(before.get('claimId'))), None)
            source_before = copy.deepcopy(source_payload)
            updates = body.get('updates') if isinstance(body.get('updates'), dict) else {}
            reason = str(body.get('reason') or '').strip()[:1000]
            if action == 'edit':
                if any(key not in ('date', 'cause', 'currency', 'lossPaid') for key in updates):
                    return error(400, 'invalid_snapshot_fields', 'Select valid loss detail fields.')
                if 'date' in updates and not _real_date(updates['date']):
                    return error(400, 'invalid_date_of_loss', 'Enter a valid Date of Loss.')
                if 'cause' in updates and (not isinstance(updates['cause'], str) or len(updates['cause']) > 1000):
                    return error(400, 'invalid_cause', 'Enter a valid loss cause.')
                currency = str(updates.get('currency', before.get('currency')) or '').upper()
                if currency not in CURRENCIES:
                    return error(400, 'invalid_currency', 'Select an available currency.')
                if 'currency' in updates:
                    updates['currency'] = currency
                if 'lossPaid' in updates:
                    from .claims_views import _parse_amount
                    amount = _parse_amount(updates['lossPaid'])
                    if amount is None or amount < 0 or not valid_amount(updates['lossPaid'], currency):
                        return error(400, 'invalid_loss_amount', 'Enter a valid non-negative loss amount for the currency.')
                    updates['lossPaid'] = amount
                elif 'currency' in updates and not valid_amount(before.get('lossPaid'), currency):
                    return error(400, 'invalid_loss_amount', 'The current loss amount has too many decimal places for the selected currency.')
                try:
                    after, source_patch = plan_snapshot_sync(before, updates, source_claim, reason=reason)
                except ValueError as exc:
                    return error(400, 'correction_reason_required', str(exc))
            else:
                after, source_patch = retry_snapshot_sync(before, source_claim, decisions=body.get('decisions'))
            now = timezone.now().isoformat()
            if source_patch and source and source_claim:
                try:
                    with transaction.atomic():
                        if 'dateOfLoss' in source_patch:
                            date_reason = reason if action == 'edit' else str((before.get('sync') or {}).get('date', {}).get('reason') or '')
                            if not date_reason:
                                raise ValueError('The Date of Loss correction reason is missing.')
                            source_claim.setdefault('lossDateHistory', []).append({'before': source_claim.get('dateOfLoss') or '', 'after': source_patch['dateOfLoss'],
                                'reason': date_reason, 'changedAt': now, 'changedBy': actor['id'], 'changedByName': actor['name']})
                        if 'causeOfLoss' in source_patch:
                            source_claim.setdefault('causeHistory', []).append({'before': source_claim.get('causeOfLoss') or '', 'after': source_patch['causeOfLoss'],
                                'changedAt': now, 'changedBy': actor['id'], 'changedByName': actor['name'], 'renewalCaseUid': str(renewal.case_uid)})
                        source_claim.update(source_patch)
                        source.payload = source_payload
                        source.row_version += 1
                        source.updated_by = actor['id']
                        source.save(update_fields=['payload', 'row_version', 'updated_by', 'updated_at'])
                        record_snapshot(entity_type='case', entity_id=source.case_uid, version=source.row_version,
                                        reason='claim_renewal_sync', data={'caseUid': str(source.case_uid), 'payload': source_payload}, created_by=actor['id'])
                        record_audit(entity_type='case', entity_id=source.case_uid, action='claim_renewal_sync', before=source_before,
                                     after=source_payload, actor=actor, request_id=request_id_from(request), metadata={'renewalCaseUid': str(renewal.case_uid), 'claimId': before.get('claimId')})
                except (DatabaseError, ValueError):
                    for field, target in (('date', 'dateOfLoss'), ('cause', 'causeOfLoss')):
                        if target in source_patch:
                            base = (before.get('sourceBaseline') or {}).get(field, before.get(field) or '')
                            after.setdefault('sourceBaseline', {})[field] = base
                            after.setdefault('sync', {})[field] = {'state': 'pending', 'base': base, 'desired': after.get(field) or '',
                                'message': 'The source Claim could not be updated. Retry the synchronization.',
                                'reason': reason if field == 'date' and action == 'edit' else str((before.get('sync') or {}).get(field, {}).get('reason') or '')}
            prior_fields = {key: value for key, value in before.items() if key != 'history'}
            next_fields = {key: value for key, value in after.items() if key != 'history'}
            after.setdefault('history', []).append({'action': action, 'before': prior_fields, 'after': copy.deepcopy(next_fields), 'changedAt': now, 'changedBy': actor['id'], 'changedByName': actor['name']})
            snapshots[index] = after
            renewal.payload = payload
            renewal.row_version += 1
            renewal.updated_by = actor['id']
            renewal.save(update_fields=['payload', 'row_version', 'updated_by', 'updated_at'])
            record_snapshot(entity_type='case', entity_id=renewal.case_uid, version=renewal.row_version,
                            reason='claim_loss_snapshot_updated', data={'caseUid': str(renewal.case_uid), 'snapshot': after}, created_by=actor['id'])
            record_audit(entity_type='case', entity_id=renewal.case_uid, action='claim_loss_snapshot_updated', before=before,
                         after=after, actor=actor, request_id=request_id_from(request), metadata={'index': index, 'action': action})
        return Response({'ok': True, 'rowVersion': renewal.row_version, 'snapshot': after})
