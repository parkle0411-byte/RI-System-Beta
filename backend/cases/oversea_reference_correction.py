"""Preview and correct one explicitly reviewed, unbooked Oversea reference.

Historical snapshots and external broker documents remain unchanged. Cases with
cash, financial reviews or report history require a separate reviewed plan.
"""
import copy
import hashlib
import json
import re

from django.db import transaction
from django.db.models import Q

from audit.services import CLI_ACTOR, record_audit, record_snapshot
from coordination.services import PRODUCTION_SOURCES, serialized
from .manual_reference import reference_in_use
from .models import Case, CaseDocument, FinanceReconciliationBatch, PlacingSlipVersion, ReferenceSequence
from .oversea import enabled
from .workflow import reference_prefix


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _mentions(value, tokens):
    if isinstance(value, dict):
        identities = {'caseUid', 'caseId', 'rootCaseUid', 'rootCaseId', 'policyNo', 'twRef', 'parentTwRef'}
        return any(k in identities and str(v) in tokens or _mentions(v, tokens) for k, v in value.items())
    if isinstance(value, list):
        return any(_mentions(v, tokens) for v in value)
    return False


def _plan(case_uid, old_reference, new_reference=None, *, lock=False):
    from .data_integrity import financial_issues
    from production.models import ProductionExclusion, ProductionReport

    query = Case.objects.select_for_update() if lock else Case.objects
    root = query.get(case_uid=case_uid)
    if (root.case_kind != 'original' or root.parent_case_id or root.status != 'posted'
            or root.is_archived or root.recycled_at or root.reinsurance_structure != 'OVERSEA'
            or not enabled(root.payload) or root.payload.get('parentTwRef')):
        raise ValueError('Select an active Announced Oversea Original.')
    if root.tw_ref != old_reference:
        raise ValueError('The reviewed old reference no longer matches this case.')
    if root.payload.get('twRef') != old_reference:
        raise ValueError('The stored case and payload references are inconsistent.')
    if str(root.effective_date) != root.payload.get('policyFrom'):
        raise ValueError('The stored Effective Date is inconsistent with Policy Period.')
    if root.class_code_snapshot and root.class_code_snapshot != root.payload.get('classCode'):
        raise ValueError('The stored Class code is inconsistent with the case payload.')
    prefix = reference_prefix(root.payload)
    if not prefix or old_reference.startswith(prefix) and re.fullmatch(re.escape(prefix)+r'\d{3,}', old_reference):
        raise ValueError('The case already uses the Effective Date prefix, or its date is invalid.')
    children = list(query.filter(parent_case_id=root.pk).order_by('id'))
    for child in children:
        if (child.case_kind != 'endorsement' or child.status != 'draft' or child.tw_ref
                or child.is_archived or child.recycled_at or not enabled(child.payload)
                or child.payload.get('parentTwRef') != old_reference
                or child.payload.get('twRef') not in ('', None, old_reference)):
            raise ValueError('Only linked, unnumbered Oversea endorsement Drafts are supported.')
    chain = [root, *children]
    ids = [c.pk for c in chain]
    tokens = {old_reference, *(str(c.case_uid) for c in chain), *(str(c.pk) for c in chain)}
    for case in chain:
        payload = case.payload
        if financial_issues(payload):
            raise ValueError('Resolve invalid financial data before correcting the reference.')
        if any(payload.get(k) for k in ('paymentEntries', 'claims', 'confirmedProductionKeys',
                                      'productionExclusions', 'accountingNotifications', 'pendingReversalOffset')):
            raise ValueError('Cash, claims, Production or notification history requires a separate correction plan.')
        transactions = payload.get('transactions') or []
        for tx in transactions:
            if (case.pk != root.pk or tx.get('legType') != 'Leg 3' or tx.get('source') == 'claim'
                    or not isinstance(tx.get('txNo'), str) or not tx['txNo'].startswith(old_reference+'-')
                    or tx.get('reversalOf') or tx.get('reversedBy')):
                raise ValueError('Unexpected transaction or reversal history requires a separate correction plan.')
    if Case.objects.exclude(pk__in=ids).filter(
            Q(payload__parentTwRef=old_reference) | Q(payload__renewedFromTwRef=old_reference)
            | Q(payload__twRef=old_reference)).exists():
        raise ValueError('Additional linked cases require a separate correction plan.')
    if (ProductionExclusion.objects.filter(case_id__in=ids).exists()
            or PlacingSlipVersion.objects.filter(case_id__in=ids).exists()
            or CaseDocument.objects.filter(case_id__in=ids, kind__startswith='generated_').exists()):
        raise ValueError('Production deferrals or saved generated documents require a separate correction plan.')
    for report in ProductionReport.objects.all().iterator():
        if _mentions([report.rows, report.excluded_rows], tokens):
            raise ValueError('Existing Production report snapshots must not be rewritten by this correction.')
    for review in FinanceReconciliationBatch.objects.all().iterator():
        if _mentions(review.members, tokens):
            raise ValueError('Financial review history must not be rewritten by this correction.')
    sequence = ReferenceSequence.objects.filter(prefix=prefix).first()
    number = sequence.last_value+1 if sequence else 1
    while reference_in_use(prefix+str(number).zfill(3)):
        number += 1
    proposed = prefix+str(number).zfill(3)
    if new_reference is not None and new_reference != proposed:
        raise ValueError('The proposed reference changed or is no longer the next available reference.')
    tx_map = {tx['txNo']: proposed+tx['txNo'][len(old_reference):]
              for tx in root.payload.get('transactions', [])}
    if len(tx_map) != len(root.payload.get('transactions', [])):
        raise ValueError('Duplicate transaction numbers require a separate correction plan.')
    replacements = []
    for case in chain:
        payload = copy.deepcopy(case.payload)
        if payload.get('twRef') == old_reference:
            payload['twRef'] = proposed
        if case.pk == root.pk:
            payload['previousTwRefs'] = list(dict.fromkeys([*(payload.get('previousTwRefs') or []), old_reference]))
            for tx in payload.get('transactions', []):
                tx['txNo'] = tx_map[tx['txNo']]
        else:
            payload['parentTwRef'] = proposed
        replacements.append((case, payload))
    manifest = {'caseUid': str(root.case_uid), 'oldReference': old_reference, 'newReference': proposed,
                'effectiveDate': root.payload['policyFrom'], 'sequenceBefore': sequence.last_value if sequence else None,
                'cases': [{'caseUid': str(c.case_uid), 'rowVersion': c.row_version, 'twRef': c.tw_ref,
                           'beforePayloadHash': checksum(c.payload), 'afterPayloadHash': checksum(p)}
                          for c, p in replacements], 'transactionMap': tx_map,
                'historicalSnapshotsPreserved': True, 'documentsPreserved': True,
                'financialValuesAndDatesPreserved': True}
    manifest['signature'] = checksum(manifest)
    return manifest, replacements, prefix, number


def preview_reference_correction(case_uid, old_reference, new_reference=None):
    # Preview is genuinely read-only: no coordination row or sequence is created.
    with transaction.atomic():
        return _plan(case_uid, old_reference, new_reference)[0]


def apply_reference_correction(case_uid, old_reference, new_reference, expected_signature):
    if not expected_signature or not new_reference:
        raise ValueError('Apply requires the reviewed new reference and preview signature.')
    with serialized(PRODUCTION_SOURCES):
        root = Case.objects.select_for_update().get(case_uid=case_uid)
        if (root.tw_ref == new_reference and old_reference in (root.payload.get('previousTwRefs') or [])
                and root.payload.get('twRef') == new_reference
                and all(t.get('txNo', '').startswith(new_reference+'-') for t in root.payload.get('transactions', []))
                and not Case.objects.filter(parent_case=root).filter(
                    Q(payload__parentTwRef=old_reference) | Q(payload__twRef=old_reference)).exists()):
            return {'changedCaseCount': 0, 'status': 'already_corrected', 'newReference': new_reference}
        plan, replacements, prefix, number = _plan(case_uid, old_reference, new_reference, lock=True)
        if plan['signature'] != expected_signature:
            raise ValueError('The case, linked Draft, sequence or financial state changed since preview.')
        sequence, _ = ReferenceSequence.objects.get_or_create(prefix=prefix, defaults={'last_value': number})
        if sequence.last_value < number:
            sequence.last_value = number
            sequence.save(update_fields=['last_value', 'updated_at'])
        for case, payload in replacements:
            before = {'caseUid': str(case.case_uid), 'twRef': case.tw_ref,
                      'rowVersion': case.row_version, 'payload': case.payload}
            if case.parent_case_id is None:
                case.tw_ref = new_reference
            case.payload = payload
            case.row_version += 1
            case.updated_by = CLI_ACTOR['id']
            case.save(update_fields=['tw_ref', 'payload', 'row_version', 'updated_by', 'updated_at'])
            after = {'caseUid': str(case.case_uid), 'twRef': case.tw_ref, 'status': case.status,
                     'rowVersion': case.row_version, 'payload': payload,
                     'referenceCorrection': {'old': old_reference, 'new': new_reference, 'signature': expected_signature}}
            record_snapshot(entity_type='case', entity_id=case.case_uid, version=case.row_version,
                            reason='oversea_reference_corrected', data=after, created_by=CLI_ACTOR['id'])
            record_audit(entity_type='case', entity_id=case.case_uid, action='oversea_reference_corrected',
                         before=before, after=after, actor=CLI_ACTOR, source='cli')
        return {**plan, 'changedCaseCount': len(replacements), 'status': 'corrected'}
