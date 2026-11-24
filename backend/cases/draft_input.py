"""Incomplete QS drafts: retain input separately from safe calculated values.

Only editable form fields are retained. Workflow, cash and accounting state
remain server-owned. Formal validation always reads the retained input again.
"""
import copy
import json
import re
from datetime import date

KEY = 'draftInput'
CLAUSE = 'pendingClause'
EDITABLE = frozenset('''ownerPersonnelId ownerPersonnelName type typePrefix
originalInsured originalInsuredCn reinsured situations classOfBusiness classCode
reinsuranceStructure policyFrom policyFromTime policyTo policyToTime currency
originalPremium riCommPct taxPct paymentTermsDays installmentEnabled
performanceInstallments splitEnabled splitParties reinsurers sumInsured
lossAdvisedDate lossRecordYears lossRecord lossRecordText interest
limitOfLiability aggregateLimit cglAggregateMode underlyingLimits subLimits deductibles
reinsuredRetention reinstatementProvisions indemnityPeriod originalExclusions
basisOfValuation basisOfValuationOther originalConditions expressWarranties
conditionsPrecedent subjectivities occupation construction lossPayee notices
specialAgreement ae newOrRenew exchRate remark statementNo coverages
coveragesOther coveragesOtherItems selfInsuredRetention cglInformation cglAnnual manualClauses
clauseDetails clauses autoClauses endoEffectiveDate endoTypes endoText coReinsuranceWarranty constructionSelections constructionLegacyText constructionLegacyConfirmed constructionSelectionVersion conveyance voyage attachmentTermination geographicalScope storage stpPremiumRate stpWebsite stpTurnoverMode stpTurnover stpHubs'''.split())
EDITABLE = EDITABLE | frozenset(('productRecall', 'aePersonnelId', 'aeEmail'))


def scope(p, existing=None):
    if not isinstance(p, dict):
        return False
    if (existing or {}).get('parentTwRef') or p.get('parentTwRef'):
        return str((existing or p).get('reinsuranceStructure') or '').upper() in ('QS', 'XOL')
    from .cgl_information import is_standard_cgl
    if str(p.get('reinsuranceStructure') or '').upper() == 'XOL' and is_standard_cgl(p): return True
    prior = existing if isinstance(existing, dict) else {}
    family = (prior.get('draftInputScope') or (prior.get('classOfBusiness') if prior.get('reinsuranceStructure') == 'QS' else '')) if prior else ''
    structure = str(p.get('reinsuranceStructure') or ('QS' if family else '')).upper()
    if structure != 'QS':
        return False
    if str(p.get('classOfBusiness') or family or '').strip().casefold() not in ('property', 'commercial general liability', 'stock throughput', 'product recall'):
        return False
    entries = p.get('reinsurers') if isinstance(p.get('reinsurers'), list) else []
    from .swiss_cgl import target as swiss_cgl
    candidate = {**p, "classOfBusiness": p.get("classOfBusiness") or family, "reinsuranceStructure": structure}
    if swiss_cgl(candidate):
        return True
    return not any(isinstance(r, dict) and ('facility' in str(r.get('name') or '').casefold()
                   or 'swiss re asia' in str(r.get('name') or '').casefold())
                   for r in entries)


def input_for(p):
    raw = p.get(KEY) if isinstance(p, dict) else None
    return {**p, **{k: copy.deepcopy(v) for k, v in raw.items() if k in EDITABLE}} if isinstance(raw, dict) else p


def normalize(p, *, existing=None):
    from .draft import normalize_draft
    from .property_qs_currency import invalid as invalid_property_qs_currency, MESSAGE as PROPERTY_QS_CURRENCY_MESSAGE
    from .facility_selection import selection_issues
    if invalid_property_qs_currency(p, existing):
        return {'errors': [PROPERTY_QS_CURRENCY_MESSAGE], 'value': None}
    structure_issues = [i['label'] for i in selection_issues(p) if i['field'] == 'reinsuranceStructure']
    if structure_issues:
        return {'errors': structure_issues, 'value': None}
    if not scope(p, existing):
        return normalize_draft(p, existing_premiums=existing)
    from .product_recall import scope as recall_scope, issues as recall_issues
    if recall_scope(p) and existing is None and not p.get('parentTwRef') and not p.get('renewedFromTwRef') and p.get('newOrRenew') != 'Renew':
        info = p.get('cglInformation')
        if info is None or isinstance(info, dict) and 'policyForm' not in info:
            p = copy.deepcopy(p)
            p['cglInformation'] = {**(info or {}), 'policyForm': 'Occurrence Form'}
    # Size/shape limits are storage constraints, not business completeness.
    try:
        encoded = json.dumps(p, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError):
        return {'errors': ['Draft must contain valid JSON.'], 'value': None}
    if len(encoded.encode('utf-16-le', errors='surrogatepass')) // 2 > 250000:
        return {'errors': ['Draft is too large.'], 'value': None}
    for key in ('situations', 'reinsurers', 'sumInsured', 'lossRecord', 'performanceInstallments', 'splitParties', 'stpTurnover', 'stpHubs'):
        if key in p and (not isinstance(p[key], list) or len(p[key]) > 500):
            return {'errors': [f'{key} must be a list of at most 500 entries.'], 'value': None}
    raw = {k: copy.deepcopy(v) for k, v in p.items() if k in EDITABLE}
    if isinstance(raw.get('coveragesOtherItems'), list):
        raw['coveragesOtherItems'] = [x.strip() if isinstance(x, str) else x for x in raw['coveragesOtherItems']]
    risk = raw.get('productRecall')
    if isinstance(risk, dict):
        risk.pop('additionalSublimits', None)
        for group, flag in (('events', 'eventsOtherSelected'), ('losses', 'lossesOtherSelected')):
            rows = risk.get(group)
            if not isinstance(rows, list):
                continue
            enabled = risk.get(flag, any(isinstance(r, dict) and not r.get('fixed') and r.get('selected') for r in rows))
            for row in rows:
                if isinstance(row, dict):
                    if isinstance(row.get('name'), str): row['name'] = row['name'].strip()
                    if not row.get('fixed'): row['selected'] = bool(enabled)
                    if group == 'losses' and isinstance(row.get('currency'), str) and row['currency'].strip():
                        row['currency'] = row['currency'].strip().upper()
                    if group == 'losses' and not row.get('currency') and (row.get('selected') or row.get('amount') not in (None, '')) and p.get('currency'):
                        row['currency'] = str(p['currency']).strip().upper()
                        row['currencyAuto'] = True
    from .cgl_risk_details import other_draft_issues
    problems = other_draft_issues(p)
    if problems:
        return {'errors': [issue['label'] for issue in problems], 'value': None}
    if recall_scope(p):
        problems = recall_issues(p, ready=False)
        if problems:
            return {'errors': [issue['label'] for issue in problems], 'value': None}
    if 'endoTypes' in raw and (not isinstance(raw['endoTypes'], list) or len(raw['endoTypes']) > 20 or any(not isinstance(v, str) for v in raw['endoTypes'])):
        return {'errors': ['Endorsement types must be a list of at most 20 text entries.'], 'value': None}
    # Do not permit a malformed container to reach a calculator or resolver.
    for key in ('situations', 'reinsurers', 'sumInsured', 'lossRecord', 'performanceInstallments', 'splitParties', 'stpTurnover', 'stpHubs'):
        if any(not isinstance(r, dict) for r in raw.get(key, [])):
            return {'errors': [f'{key} entries must be objects.'], 'value': None}
    # Missing history is allowed in a draft, but entered values must be valid.
    from .cgl_qs import scope as cgl_qs_scope
    if cgl_qs_scope(p) or recall_scope(p):
        from .draft import nullable_number
        from .calc.jsnum import js_to_number
        history_errors = []
        years = p.get('lossRecordYears')
        if years not in (None, ''):
            nullable_number(years, 'Loss history years', history_errors, min=0, integer=True)
        dates = [('Loss record advised date', p.get('lossAdvisedDate'))]
        for i, row in enumerate(p.get('lossRecord') or []):
            dates.append((f'Loss {i + 1} Date of Loss', row.get('date')))
            amount = row.get('lossPaid')
            if amount not in (None, ''):
                before = len(history_errors)
                nullable_number(amount, f'Loss {i + 1} Loss Amount', history_errors)
                if len(history_errors) == before and js_to_number(amount) <= 0:
                    history_errors.append(f'Loss {i + 1} Loss Amount must be greater than 0.')
        for label, value in dates:
            if value in (None, ''):
                continue
            try:
                valid = isinstance(value, str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and date.fromisoformat(value).year >= 100
            except ValueError:
                valid = False
            if not valid:
                history_errors.append(f'{label} must use YYYY-MM-DD.')
        if history_errors:
            return {'errors': history_errors, 'value': None}
    result = normalize_draft({**p, **raw}, allow_negative_premiums=bool((existing or p).get("parentTwRef")), existing_premiums=existing)
    value = result['value']
    if recall_scope(value):
        if 'productRecall' in raw: value['productRecall'] = copy.deepcopy(raw['productRecall'])
        for key in ('clauses', 'clauseDetails', 'autoClauses', 'manualClauses'):
            raw[key] = copy.deepcopy(value[key])
    # 2026-11-12：未完成草稿保留使用者輸入的原文（draftInput），但超過金額上限的數字不放進計算用欄位
    #（與無效數字相同，改為空值）；送審時由正式檢查提示「must not exceed」。
    from .data_integrity import AMOUNT_MAX, AMOUNTS
    def _cap(row):
        for key in AMOUNTS:
            number = row.get(key)
            if isinstance(number, (int, float)) and not isinstance(number, bool) and abs(number) > AMOUNT_MAX:
                row[key] = None
    _cap(value)
    for key in ('reinsurers', 'performanceInstallments'):
        for row in value.get(key) or []:
            if isinstance(row, dict):
                _cap(row)
    from .construction import scope as construction_scope
    if construction_scope(value):
        # Keep server-preserved historical text in the raw Draft as well; callers
        # cannot hide it to bypass confirmation at document-generation time.
        for field in ('construction','constructionLegacyText','constructionSelectionVersion'):
            raw[field]=copy.deepcopy(value[field])
    value['draftInputScope'] = p.get('classOfBusiness') or (existing or {}).get('draftInputScope') or (existing or {}).get('classOfBusiness')
    if 'cglAggregateMode' in value:
        raw['cglAggregateMode'] = value['cglAggregateMode']
        if value['cglAggregateMode'] == 'auto': raw['aggregateLimit'] = value['aggregateLimit']
    value[KEY] = raw
    pending = p.get(CLAUSE) if isinstance(p.get(CLAUSE), dict) else {}
    value[CLAUSE] = {'code': str(pending.get('code') or '')[:80], 'title': str(pending.get('title') or '')[:300]}
    # Numeric/date validators already replace invalid values with safe nulls.
    # Invalid optional text and range values remain visible via draftInput.
    result['errors'] = []
    currency = value.get('currency') or ''
    if len(currency) != 3 or not currency.isalpha():
        value['currency'] = ''
        result['columns']['currency'] = None
    return result


def validate(p):
    if not isinstance(p, dict) or not isinstance(p.get(KEY), dict):
        return p, []
    from .draft import normalize_draft
    candidate = input_for(p)
    dates = [(key, candidate.get(key)) for key in ('policyFrom', 'policyTo', 'lossAdvisedDate', 'endoEffectiveDate')]
    dates += [(f'lossRecord.{i}.date', row.get('date')) for i, row in enumerate(candidate.get('lossRecord') or [])]
    dates += [(f'performanceInstallments.{i}.paymentBaseDate', row.get('paymentBaseDate')) for i, row in enumerate(candidate.get('performanceInstallments') or [])]
    info = candidate.get('cglInformation') or {}
    if isinstance(info, dict) and info.get('policyForm') == 'Claims-Made Form':
        from .cgl_information import retroactive_rows
        entries = retroactive_rows(info)
        if isinstance(entries, list):
            dates += [(f'cglInformation.retroactiveDates.{i}.date', row.get('date')) for i, row in enumerate(entries) if isinstance(row, dict)]
    date_errors = []
    for field, value in dates:
        if value is None or value == '':
            continue
        try:
            valid = isinstance(value, str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and date.fromisoformat(value).year >= 100
        except ValueError:
            valid = False
        if not valid:
            date_errors.append({'field': field, 'label': field + ' must use YYYY-MM-DD'})
    if date_errors:
        return p, date_errors
    normalized = normalize_draft(candidate, allow_negative_premiums=bool(p.get("parentTwRef")), existing_premiums=p)
    errors = normalized['errors']
    if errors:
        return p, [{'field': KEY, 'label': message} for message in errors]
    clean = copy.deepcopy(p)
    clean.update({k: v for k, v in normalized['value'].items() if k in EDITABLE})
    from .placing_rules import normalize_extra
    normalize_extra(candidate, clean)
    from .construction import normalize as normalize_construction
    normalize_construction(candidate,clean,[],p)
    clean.pop(KEY, None)
    clean.pop(CLAUSE, None)
    clean.pop('draftInputScope', None)
    return clean, []
