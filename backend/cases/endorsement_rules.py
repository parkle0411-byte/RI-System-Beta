"""Owner-approved facultative endorsement rules (2026-10-28).

Source identity and fixed terms are server-owned. Draft input is preserved
separately; period/completeness checks apply at Review/Announce.
"""
import calendar
import copy
from datetime import date

VERSION = 'facultative-v1'
CONTEXT = 'endorsementSource'
FIXED = ('currency', 'reinsuranceStructure', 'classOfBusiness', 'classCode', 'reinsured',
         'riCommPct', 'taxPct', 'paymentTermsDays', 'splitEnabled', 'splitParties')
RI_FIXED = ('name', 'sharePct', 'riCommPct', 'taxPct', 'paymentTermsDays', 'foreignBroker')
DATES = ('policyFrom', 'policyTo', 'policyFromTime', 'policyToTime')


def day(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def add_months(value, months):
    index = value.year * 12 + value.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def period_issues(p):
    if p.get('reinsuranceStructure') not in ('QS', 'XOL'):
        return []
    start, end = day(p.get('policyFrom')), day(p.get('policyTo'))
    if not start or not end:
        return []  # Existing required/format validators report these.
    if end <= start:
        return [{'field': 'policyTo', 'label': 'Expiration date must be later than Effective date.'}]
    try:
        limit = add_months(start, 18)
    except ValueError:
        limit = date.max
    if end > limit:
        return [{'field': 'policyTo', 'label': 'The complete insurance period must not exceed 18 calendar months.'}]
    return []


def attach_source(p, source):
    prior = source.payload or {}
    p['endorsementRules'] = VERSION
    p[CONTEXT] = {'caseUid': str(source.case_uid), 'rowVersion': source.row_version,
                  'fixed': {k: copy.deepcopy(prior.get(k)) for k in FIXED},
                  'reinsurers': [{k: copy.deepcopy(r.get(k)) for k in RI_FIXED}
                                 for r in prior.get('reinsurers', [])],
                  **{k: prior.get(k) for k in DATES},
                  'previousEffectiveDate': prior.get('endoEffectiveDate') if source.parent_case_id else ''}
    return p[CONTEXT]


def previous_case(case):
    from .models import Case
    return (Case.objects.filter(parent_case_id=case.parent_case_id, id__lt=case.pk,
                                recycled_at__isnull=True,
                                is_archived=False).order_by('-id').first() or case.parent_case)


def context_for(case):
    stored = case.payload or {}
    context = copy.deepcopy(stored.get(CONTEXT))
    source = previous_case(case)
    from .data_integrity import financial_issues
    from rest_framework.exceptions import APIException
    if source.status not in ('posted', 'closed'):
        error = APIException({'error': 'endorsement_source_status', 'message': 'The preceding source must remain Announced or Confirmed before continuing the endorsement.'})
        error.status_code = 409
        raise error
    source_issues = financial_issues(source.payload)
    if source_issues:
        error = APIException({'error': 'case_data_invalid', 'message': 'The source case contains invalid financial data. Its original data is retained.', 'issues': source_issues})
        error.status_code = 409
        raise error
    if not isinstance(context, dict) or not isinstance(context.get('fixed'), dict):
        temporary = {}
        context = attach_source(temporary, source)
    # Date validation follows the latest completed source even after a correction.
    context.update(policyFrom=source.payload.get('policyFrom'), policyTo=source.payload.get('policyTo'),
                   policyFromTime=source.payload.get('policyFromTime'), policyToTime=source.payload.get('policyToTime'),
                   previousEffectiveDate=source.payload.get('endoEffectiveDate') if source.parent_case_id else '')
    return context


def apply_fixed(p, context):
    p['endorsementRules'] = VERSION
    p[CONTEXT] = copy.deepcopy(context)
    for key in FIXED:
        p[key] = copy.deepcopy(context['fixed'].get(key))
    def fixed_rows(submitted):
        submitted = submitted if isinstance(submitted, list) else []
        return [{**(submitted[i] if i < len(submitted) and isinstance(submitted[i], dict) else {}),
                 **copy.deepcopy(row)} for i, row in enumerate(context['reinsurers'])]
    p['reinsurers'] = fixed_rows(p.get('reinsurers'))
    p['installmentEnabled'], p['performanceInstallments'] = False, []
    if isinstance(p.get('draftInput'), dict):
        raw = p['draftInput']
        for key in FIXED:
            raw[key] = copy.deepcopy(p[key])
        raw['reinsurers'] = fixed_rows(raw.get('reinsurers'))
        raw['installmentEnabled'], raw['performanceInstallments'] = False, []


def endorsement_issues(p, context=None):
    issues = period_issues(p)
    if not p.get('parentTwRef'):
        return issues
    context = context or p.get(CONTEXT) or {}
    if context and 'Period' not in (p.get('endoTypes') or []):
        if any(p.get(k) != context.get(k) for k in ('policyFrom', 'policyTo')) or any((p.get(k) or '12:00') != (context.get(k) or '12:00') for k in ('policyFromTime', 'policyToTime')):
            issues.append({'field': 'endoTypes', 'label': 'Select Period for an endorsement that changes the insurance period.'})
    effective = day(p.get('endoEffectiveDate'))
    if effective:
        start, end = day(context.get('policyFrom')), day(context.get('policyTo'))
        if 'Period' not in (p.get('endoTypes') or []) and start and end and not start <= effective <= end:
            issues.append({'field': 'endoEffectiveDate', 'label': 'Endorsement effective date must be within the latest insurance period, including both boundary dates.'})
        previous = day(context.get('previousEffectiveDate'))
        if previous and effective < previous:
            issues.append({'field': 'endoEffectiveDate', 'label': 'Endorsement effective date cannot be earlier than the preceding endorsement.'})
    return issues


def date_edit_error(candidate, stored, *, unlocked=False):
    def value(p, key):
        return (p.get(key) or '12:00') if key.endswith('Time') else p.get(key)
    if any(value(candidate, k) != value(stored, k) for k in DATES):
        if 'Period' not in (candidate.get('endoTypes') or []):
            return 'Select Period before changing the insurance period.'
        if not unlocked:
            return 'Unlock risk fields before changing the insurance period.'
    return ''


def all_zero(p):
    rows = p.get('reinsurers')
    return (bool(p.get('parentTwRef')) and p.get('originalPremium') == 0
            and isinstance(rows, list) and bool(rows)
            and all(isinstance(r, dict) and r.get('premium') == 0 for r in rows))
