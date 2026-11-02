"""Information for the standard CGL placement (2026-10-16 owner decisions)."""
import re
from datetime import date
from .calc.jsnum import js_is_finite, js_to_number

POLICY_FORMS = ('Occurrence Form', 'Claims-Made Form')
APPLICABILITY = ('notApplicable', 'applicable')
TERRITORIES = ('Worldwide including USA/Canada', 'Worldwide excluding USA/Canada', 'USA/Canada Only', 'Other')
CURRENCIES = ('TWD', 'USD', 'EUR', 'JPY', 'GBP', 'HKD', 'MYR')


def is_standard_cgl(payload):
    if not isinstance(payload, dict):
        return False
    if str(payload.get('classOfBusiness') or '').strip().casefold() != 'commercial general liability':
        return False
    if str(payload.get('reinsuranceStructure') or '').strip().upper() not in ('', 'QS', 'XOL', 'FACULTATIVE'):
        return False
    from .swiss_cgl import target as swiss_cgl
    if swiss_cgl(payload):
        return True
    for row in payload.get('reinsurers') or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get('name') or '').strip()
        broker = str(row.get('foreignBroker') or '').strip()
        if re.search(r'\(Facility\)\s*$', name, re.I) or 'swiss re asia' in name.casefold() or ('pws' in broker.casefold() and str(payload.get('reinsuranceStructure') or '').upper() not in ('QS', 'FACULTATIVE')):
            return False
    return True


def normalize_information(payload, errors, *, text, number, date_value, rows):
    raw = payload.get('cglInformation')
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        errors.append('CGL Information must be an object.')
        raw = {}
    def choice(key, label, choices):
        value = text(raw.get(key), 160)
        if value and value not in choices:
            errors.append(f'{label} must use an available option.')
        return value
    form = choice('policyForm', 'Policy Form', POLICY_FORMS)
    claims = form == 'Claims-Made Form'
    erp = choice('extendedReportingApplies', 'Extended Reporting Period applicability', APPLICABILITY) if claims else ''
    territory = choice('territorialLimits', 'Territorial / Jurisdiction Limits', TERRITORIES)
    special = choice('specialAgreementApplies', 'Special Agreement applicability', APPLICABILITY)
    # Existing agreement text is retained when opening/saving a legacy CGL case.
    if 'cglInformation' not in payload and text(payload.get('specialAgreement')):
        special = 'applicable'
    turnover = []
    for index, row in enumerate(rows(raw.get('estimatedTurnover'), 'Estimated Turnover', errors)):
        if not isinstance(row, dict):
            errors.append(f'Estimated Turnover {index + 1} must be an object.')
            continue
        currency = text(row.get('currency'), 3).upper()
        if currency and currency not in CURRENCIES:
            errors.append(f'Estimated Turnover {index + 1} Currency must use an available option.')
        turnover.append({'region': text(row.get('region'), 240), 'currency': currency,
                         'amount': number(row.get('amount'), f'Estimated Turnover {index + 1} Amount', errors, min=0)})
    result = {
        'policyForm': form,
        'retroactiveDate': '',
        'retroactiveDates': [],
        'extendedReportingApplies': erp,
        'extendedReportingPeriod': text(raw.get('extendedReportingPeriod'), 3000) if erp == 'applicable' else '',
        'territorialLimits': territory,
        'territorialOther': text(raw.get('territorialOther'), 3000) if territory == 'Other' else '',
        'insuredBusiness': text(raw.get('insuredBusiness'), 3000),
        'insuredProducts': text(raw.get('insuredProducts'), 3000),
        'estimatedTurnover': turnover,
        'insuredWebsite': text(raw.get('insuredWebsite'), 1000),
        'specialAgreementApplies': special,
    }

    if claims:
        for index, row in enumerate(rows(retroactive_rows(raw), 'Retroactive Dates', errors)):
            if not isinstance(row, dict):
                errors.append(f'Retroactive Date {index + 1} must be an object.')
                continue
            result['retroactiveDates'].append({'date': date_value(row.get('date'), f'Retroactive Date {index + 1}', errors) or '',
                                              'description': text(row.get('description'), 3000)})
        result['retroactiveDates'] = sorted_retroactive(result)
        result['retroactiveDate'] = next((r['date'] for r in result['retroactiveDates'] if r['date']), '')

    from .placing_rules import cgl, normalize_extra
    if cgl(payload):
        temp = {**payload, 'cglInformation': result}
        normalize_extra(payload, temp)
        result = temp['cglInformation']
    return result


def information_issues(payload):
    if not is_standard_cgl(payload):
        return []
    info = payload.get('cglInformation')
    info = info if isinstance(info, dict) else {}
    issues = []
    def add(key, label):
        issues.append({'field': 'cglInformation.' + key, 'label': label})
    def filled(value):
        return value is not None and str(value).strip() != ''
    form = info.get('policyForm')
    if form not in POLICY_FORMS:
        add('policyForm', 'Policy Form')
    if form == 'Claims-Made Form':
        issues.extend(retroactive_issues(info))
        if info.get('extendedReportingApplies') not in APPLICABILITY:
            add('extendedReportingApplies', 'Extended Reporting Period applicability')
        if info.get('extendedReportingApplies') == 'applicable' and not filled(info.get('extendedReportingPeriod')):
            add('extendedReportingPeriod', 'Extended Reporting Period — period and description')
    if info.get('territorialLimits') not in TERRITORIES:
        add('territorialLimits', 'Territorial / Jurisdiction Limits')
    elif info.get('territorialLimits') == 'Other' and not filled(info.get('territorialOther')):
        add('territorialOther', 'Territorial / Jurisdiction Limits — Other')
    for key, label in [('insuredBusiness', "Insured’s Business"), ('insuredProducts', "Insured’s Products")]:
        if not filled(info.get(key)):
            add(key, label)
    turnover = info.get('estimatedTurnover')
    if not isinstance(turnover, list) or not turnover:
        add('estimatedTurnover', 'Estimated Turnover — at least one entry')
    else:
        for index, row in enumerate(turnover):
            row = row if isinstance(row, dict) else {}
            prefix = f'estimatedTurnover.{index}.'
            if not filled(row.get('region')):
                add(prefix + 'region', f'Estimated Turnover {index + 1} Region')
            if row.get('currency') not in CURRENCIES:
                add(prefix + 'currency', f'Estimated Turnover {index + 1} Currency')
            amount = row.get('amount')
            if not filled(amount) or not js_is_finite(js_to_number(amount)) or js_to_number(amount) < 0:
                add(prefix + 'amount', f'Estimated Turnover {index + 1} Amount')
    if info.get('specialAgreementApplies') not in APPLICABILITY:
        add('specialAgreementApplies', 'Special Agreement applicability')
    elif info.get('specialAgreementApplies') == 'applicable' and not filled(payload.get('specialAgreement')):
        issues.append({'field': 'specialAgreement', 'label': 'Special Agreement'})
    return issues


def retroactive_rows(info):
    if 'retroactiveDates' in info:
        return info['retroactiveDates']
    return [{'date': info['retroactiveDate'], 'description': ''}] if info.get('retroactiveDate') else []


def valid_retroactive(value):
    try:
        return isinstance(value, str) and bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and date.fromisoformat(value).year >= 100
    except ValueError:
        return False


def sorted_retroactive(info):
    return sorted(retroactive_rows(info), key=lambda r: r.get('date') if valid_retroactive(r.get('date')) else '~~~~')


def retroactive_issues(info):
    rows = retroactive_rows(info)
    if not isinstance(rows, list) or not rows:
        return [{'field': 'cglInformation.retroactiveDates', 'label': 'Retroactive Date — at least one entry'}]
    issues, seen = [], set()
    for i, row in enumerate(rows):
        row = row if isinstance(row, dict) else {}
        value = row.get('date')
        field = f'cglInformation.retroactiveDates.{i}.'
        if not valid_retroactive(value):
            issues.append({'field': field+'date', 'label': f'Retroactive Date {i+1} must use a valid YYYY-MM-DD date'})
        elif value in seen:
            issues.append({'field': field+'date', 'label': 'Duplicate Retroactive Date — combine the descriptions for the same date.'})
        if isinstance(value,str): seen.add(value)
        if len(rows) > 1 and not str(row.get('description') or '').strip():
            issues.append({'field':field+'description', 'label':f'Retroactive Date {i+1} description is required when there are multiple dates'})
    return issues


def retroactive_text(info):
    if info.get('policyForm') != 'Claims-Made Form': return ''
    result = []
    for row in sorted_retroactive(info):
        value = row.get('date') or ''
        formatted = date.fromisoformat(value).strftime('%B %d, %Y') if valid_retroactive(value) else str(value)
        description = str(row.get('description') or '').strip()
        result.append(f'({formatted} in respect of {description})' if description else formatted)
    return '\n'.join(result)


def normalize_aggregate(inp, value):
    if not is_standard_cgl(value): return
    mode = inp.get('cglAggregateMode')
    if mode not in ('auto', 'manual'):
        raw = inp.get('aggregateLimit')
        mode = 'auto' if raw is None or str(raw).strip() == '' or (js_is_finite(js_to_number(raw)) and js_to_number(raw) == 0) else 'manual'
    value['cglAggregateMode'] = mode
    if mode == 'auto': value['aggregateLimit'] = value.get('limitOfLiability')


def aggregate_issues(p):
    if not is_standard_cgl(p): return []
    value = p.get('aggregateLimit')
    if value is None or str(value).strip() == '' or not js_is_finite(js_to_number(value)) or js_to_number(value) <= 0:
        return [{'field':'aggregateLimit', 'label':'Aggregate Limit must be greater than 0'}]
    return []


def inherit_aggregate(payload):
    if not is_standard_cgl(payload): return
    raw = payload.get('aggregateLimit')
    if raw is None or str(raw).strip() == '' or (js_is_finite(js_to_number(raw)) and js_to_number(raw) == 0):
        payload['cglAggregateMode'] = 'auto'
        payload['aggregateLimit'] = payload.get('limitOfLiability')
    elif 'cglAggregateMode' not in payload:
        payload['cglAggregateMode'] = 'manual'
