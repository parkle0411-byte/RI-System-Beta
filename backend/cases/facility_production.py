"""Production preview and close snapshots for announced Facility declarations."""
import copy
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from .models import FacilityDeclaration


def dashboard_trend(visible_case_ids, fx_rows, current_month):
    """Estimate open-month Facility revenue with the dashboard's latest FX policy."""
    from dashboard.calc import build_rate_lookup
    visible = set(visible_case_ids)
    month_set = set()
    declarations = list(FacilityDeclaration.objects.filter(status='posted', facility_id__in=visible,
        facility__recycled_at__isnull=True, facility__is_archived=False).select_related('facility').order_by('id'))
    for row in declarations:
        payload = row.payload or {}
        if payload.get('revenueMonth'):
            month_set.add(payload['revenueMonth'])
        month_set.update(event.get('month') for event in payload.get('productionCorrections') or [] if event.get('month'))
    lookup = build_rate_lookup(fx_rows, current_month)
    currencies = {row.get('currency') for row in fx_rows if row.get('currency')}
    rates = {currency: rate for currency in currencies if (rate := lookup({'currency': currency})) > 0}
    result = []
    for month in sorted(month_set):
        preview = append_preview({'rows': [], 'missingRateCurrencies': [], 'sourceSignature': ''}, month, {month: rates}, declarations)
        result.extend({'month': month, 'incomeTwd': row['income'], 'caseId': row.get('caseId')} for row in preview['rows']
                      if row.get('caseId') in visible and row.get('income') is not None)
    return result


def append_preview(preview, month, fx_rates, declarations=None, links=None):
    from production.calc import month_end, production_class_code, first_policy_no
    rows = declarations if declarations is not None else FacilityDeclaration.objects.filter(status='posted',
        facility__recycled_at__isnull=True, facility__is_archived=False).select_related('facility').order_by('id')
    result = copy.deepcopy(preview)
    signatures, missing = [], set(result['missingRateCurrencies'])
    for declaration in rows:
        payload, facility = declaration.payload, declaration.facility
        first_ref = first_policy_no(facility.tw_ref, links or {})
        events = [event for event in payload.get('productionCorrections') or [] if event.get('month') == month]
        base_month = payload.get('revenueMonth') == month
        if not base_month and not events:
            continue
        terms = payload.get('facilityTermsSnapshot') or {}
        currency = terms.get('currency') or facility.currency or 'TWD'
        rate = 1 if currency == 'TWD' else fx_rates.get(month, {}).get(currency)
        signatures.append([str(declaration.declaration_uid), declaration.row_version, payload, facility.row_version, rate])
        frozen = payload.get('initialProductionRecognition')
        if base_month and frozen is not None:
            result['rows'].extend(copy.deepcopy(frozen))
        txn_numbers = set(payload.get('transactionNumbers') or []) if base_month and frozen is None else set()
        transactions = [x for x in (facility.payload.get('transactions') or []) if x.get('txNo') in txn_numbers]
        by_reinsurer = {}
        for tx in transactions:
            if tx.get('legType') in ('Leg 1', 'Leg 3'):
                by_reinsurer.setdefault(tx.get('reinsurerIdx'), {})[tx['legType']] = tx
        for index, pair in sorted(by_reinsurer.items()):
            t1, t3 = pair.get('Leg 1'), pair.get('Leg 3')
            if not t1 or not t3:
                raise ValueError('Facility declaration accounting records are incomplete.')
            premium, income = Decimal(str(t1.get('facilityPremium') or 0)), Decimal(str(t3.get('amount') or 0))
            if premium == 0 and income == 0:
                continue
            if rate is None:
                missing.add(currency)
            def converted(amount):
                return None if rate is None else int((amount * Decimal(str(rate))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            uid = str(declaration.declaration_uid)
            key = f'facility:{uid}:R{index}'
            result['rows'].append({'id': key, 'key': key, 'reinsurerKey': key,
                'caseId': facility.pk, 'caseUid': str(facility.case_uid), 'caseRowVersion': facility.row_version,
                'facilityDeclarationUid': uid, 'declarationVersion': declaration.row_version,
                'installmentId': uid, 'month': month, 'originalInsured': terms.get('facilityName') or '',
                'reinsured': terms.get('reinsured') or '', 'reinsurer': t1.get('reinsurer') or '',
                'classCode': production_class_code(terms), 'type': 'R' if terms.get('newOrRenew') == 'Renew' else 'N',
                'currency': currency, 'rate': rate, 'missingRate': rate is None, 'ae': terms.get('ae') or '',
                'aePersonnelId': terms.get('aePersonnelId'), 'effDate': terms.get('policyFrom') or '',
                'expDate': terms.get('policyTo') or '', 'comm': float(income / premium * 100) if premium else 0,
                'premium': converted(premium), 'income': converted(income), 'policyNo': facility.tw_ref,
                'firstPolicyNo': first_ref, 'endorseNo': '', 'remark': 'Facility',
                'tranxDate': month_end(month), 'installment': '', 'exclusion': None})
        for event in events:
            revision = event['revision']
            if event.get('closedRows') is not None:
                result['rows'].extend(copy.deepcopy(event['closedRows']))
                continue
            for index, old in enumerate(event.get('oldRows') or []):
                row = copy.deepcopy(old)
                row.update(id=f'facility:{declaration.declaration_uid}:C{revision}:OLD:{index}',
                           month=month, tranxDate=month_end(month), facilityCorrectionRevision=revision,
                           facilityCorrectionSide='reversal', declarationVersion=declaration.row_version,
                           caseRowVersion=facility.row_version)
                for key in ('premium', 'income'):
                    if row.get(key) is not None: row[key] = -row[key]
                result['rows'].append(row)
            numbers = set(event.get('transactionNumbers') or [])
            pairs = {}
            for tx in facility.payload.get('transactions') or []:
                if tx.get('txNo') in numbers and tx.get('legType') in ('Leg 1', 'Leg 3'):
                    pairs.setdefault(tx.get('reinsurerIdx'), {})[tx['legType']] = tx
            for index, pair in sorted(pairs.items()):
                if 'Leg 1' not in pair or 'Leg 3' not in pair:
                    raise ValueError('Facility correction accounting records are incomplete.')
                t1, t3 = pair['Leg 1'], pair['Leg 3']
                premium, income = Decimal(str(t1.get('facilityPremium') or 0)), Decimal(str(t3.get('amount') or 0))
                if premium == 0 and income == 0: continue
                if rate is None: missing.add(currency)
                def converted(amount):
                    return None if rate is None else int((amount * Decimal(str(rate))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
                key = f'facility:{declaration.declaration_uid}:C{revision}:NEW:{index}'
                result['rows'].append({'id': key, 'key': key, 'reinsurerKey': key,
                    'caseId': facility.pk, 'caseUid': str(facility.case_uid), 'caseRowVersion': facility.row_version,
                    'facilityDeclarationUid': str(declaration.declaration_uid), 'declarationVersion': declaration.row_version,
                    'facilityCorrectionRevision': revision, 'facilityCorrectionSide': 'replacement',
                    'installmentId': str(declaration.declaration_uid), 'month': month,
                    'originalInsured': terms.get('facilityName') or '', 'reinsured': terms.get('reinsured') or '',
                    'reinsurer': t1.get('reinsurer') or '', 'classCode': production_class_code(terms),
                    'type': 'R' if terms.get('newOrRenew') == 'Renew' else 'N', 'currency': currency,
                    'rate': rate, 'missingRate': rate is None, 'ae': terms.get('ae') or '',
                    'aePersonnelId': terms.get('aePersonnelId'), 'effDate': terms.get('policyFrom') or '',
                    'expDate': terms.get('policyTo') or '', 'comm': float(income / premium * 100) if premium else 0,
                    'premium': converted(premium), 'income': converted(income), 'policyNo': facility.tw_ref,
                    'firstPolicyNo': first_ref, 'endorseNo': '', 'remark': 'Facility correction',
                    'tranxDate': month_end(month), 'installment': '', 'exclusion': None})
    result['missingRateCurrencies'] = sorted(missing)
    if signatures:
        result['sourceSignature'] += '|facility:' + hashlib.sha256(json.dumps(signatures, sort_keys=True, default=str).encode()).hexdigest()
    return result


def freeze_report(rows, month, actor, request_id=None):
    from audit.services import record_audit, record_snapshot
    ids = {row['facilityDeclarationUid'] for row in rows if row.get('facilityDeclarationUid')}
    declarations = list(FacilityDeclaration.objects.select_for_update().filter(declaration_uid__in=ids))
    if len(declarations) != len(ids):
        raise ValueError('A Facility declaration is no longer available.')
    for declaration in declarations:
        corrections = copy.deepcopy(declaration.payload.get('productionCorrections') or [])
        if declaration.status != 'posted' or (declaration.payload.get('revenueMonth') != month and not any(e.get('month') == month for e in corrections)):
            raise ValueError('A Facility declaration changed before close.')
        recognition = [row for row in rows if row.get('facilityDeclarationUid') == str(declaration.declaration_uid)]
        before = copy.deepcopy(declaration.payload)
        for event in corrections:
            if event.get('month') == month:
                event['closedRows'] = [row for row in recognition if row.get('facilityCorrectionRevision') == event['revision']]
                event['closed'] = True
        latest = [row for row in recognition if row.get('facilityCorrectionSide') == 'replacement'] if corrections else recognition
        declaration.payload = {**declaration.payload, 'productionRecognition': latest, 'productionCorrections': corrections}
        declaration.row_version += 1
        declaration.updated_by = actor['id']
        declaration.save(update_fields=['payload', 'row_version', 'updated_by', 'updated_at'])
        record_snapshot(entity_type='facility_declaration', entity_id=declaration.declaration_uid,
                        version=declaration.row_version, reason='production_closed', data=declaration.payload, created_by=actor['id'])
        record_audit(entity_type='facility_declaration', entity_id=declaration.declaration_uid, action='production_closed',
                     before=before, after=declaration.payload, actor=actor, request_id=request_id, metadata={'month': month})
