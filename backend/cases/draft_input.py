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
limitOfLiability aggregateLimit underlyingLimits subLimits deductibles
reinsuredRetention reinstatementProvisions indemnityPeriod originalExclusions
basisOfValuation basisOfValuationOther originalConditions expressWarranties
conditionsPrecedent subjectivities occupation construction lossPayee notices
specialAgreement ae newOrRenew exchRate remark statementNo coverages
coveragesOther selfInsuredRetention cglInformation cglAnnual manualClauses
clauseDetails clauses autoClauses endoEffectiveDate endoTypes endoText coReinsuranceWarranty constructionSelections constructionLegacyText constructionLegacyConfirmed constructionSelectionVersion'''.split())


def scope(p, existing=None):
    if not isinstance(p, dict):
        return False
    if (existing or {}).get('parentTwRef') or p.get('parentTwRef'):
        return str((existing or p).get('reinsuranceStructure') or '').upper() in ('QS', 'XOL')
    prior = existing if isinstance(existing, dict) else {}
    family = (prior.get('draftInputScope') or (prior.get('classOfBusiness') if prior.get('reinsuranceStructure') == 'QS' else '')) if prior else ''
    structure = str(p.get('reinsuranceStructure') or ('QS' if family else '')).upper()
    if structure != 'QS':
        return False
    if str(p.get('classOfBusiness') or family or '').strip().casefold() not in ('property', 'commercial general liability'):
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
    from .facility_selection import selection_issues
    structure_issues = [i['label'] for i in selection_issues(p) if i['field'] == 'reinsuranceStructure']
    if structure_issues:
        return {'errors': structure_issues, 'value': None}
    if not scope(p, existing):
        return normalize_draft(p, existing_premiums=existing)
    # Size/shape limits are storage constraints, not business completeness.
    try:
        encoded = json.dumps(p, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError):
        return {'errors': ['Draft must contain valid JSON.'], 'value': None}
    if len(encoded.encode('utf-16-le', errors='surrogatepass')) // 2 > 250000:
        return {'errors': ['Draft is too large.'], 'value': None}
    for key in ('situations', 'reinsurers', 'sumInsured', 'lossRecord', 'performanceInstallments', 'splitParties'):
        if key in p and (not isinstance(p[key], list) or len(p[key]) > 500):
            return {'errors': [f'{key} must be a list of at most 500 entries.'], 'value': None}
    raw = {k: copy.deepcopy(v) for k, v in p.items() if k in EDITABLE}
    if 'endoTypes' in raw and (not isinstance(raw['endoTypes'], list) or len(raw['endoTypes']) > 20 or any(not isinstance(v, str) for v in raw['endoTypes'])):
        return {'errors': ['Endorsement types must be a list of at most 20 text entries.'], 'value': None}
    # Do not permit a malformed container to reach a calculator or resolver.
    for key in ('situations', 'reinsurers', 'sumInsured', 'lossRecord', 'performanceInstallments', 'splitParties'):
        if any(not isinstance(r, dict) for r in raw.get(key, [])):
            return {'errors': [f'{key} entries must be objects.'], 'value': None}
    result = normalize_draft({**p, **raw}, allow_negative_premiums=bool((existing or p).get("parentTwRef")), existing_premiums=existing)
    value = result['value']
    from .construction import scope as construction_scope
    if construction_scope(value):
        # Keep server-preserved historical text in the raw Draft as well; callers
        # cannot hide it to bypass confirmation at document-generation time.
        for field in ('construction','constructionLegacyText','constructionSelectionVersion'):
            raw[field]=copy.deepcopy(value[field])
    value['draftInputScope'] = p.get('classOfBusiness') or (existing or {}).get('draftInputScope') or (existing or {}).get('classOfBusiness')
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
        dates.append(('cglInformation.retroactiveDate', info.get('retroactiveDate')))
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
