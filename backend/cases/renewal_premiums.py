"""Full-policy daily average renewal premiums, approved 2026-10-28.

Signed amounts are summed before conversion. Actual source/renewal days and
the existing currency precision apply. Each input has its own failure state.
"""
import copy
import math
from datetime import date
from .calc.premium_money import premium_money


class RenewalPremiumError(ValueError):
    pass


def _day(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise RenewalPremiumError(field + ' is invalid. Review the policy chain before renewal.') from None


def _money(value, field):
    try:
        if value is None or isinstance(value, bool) or isinstance(value, str) and not value.strip():
            raise ValueError()
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError):
        raise RenewalPremiumError(field + ' is missing or invalid. Enter the renewal premium manually.') from None


def _name_key(value):
    return ' '.join(value.split()).casefold() if isinstance(value, str) else ''


def _row_amount(p, name, label):
    rows = p.get('reinsurers')
    if not isinstance(rows, list):
        raise RenewalPremiumError(label + ' has no valid reinsurer schedule.')
    matching = [r for r in rows if isinstance(r, dict) and _name_key(r.get('name')) == name]
    if not name or len(matching) != 1:
        raise RenewalPremiumError(label + ' has a missing or repeated reinsurer. Enter its renewal premium manually.')
    return _money(matching[0].get('premium'), label + ' premium')


def _amount(p, field):
    if field == 'originalPremium':
        return p.get(field)
    try:
        return p['reinsurers'][int(field.split('.')[1])].get('premium')
    except (KeyError, IndexError, TypeError):
        return None


def _assign(p, field, value):
    if field == 'originalPremium':
        p[field] = value
    else:
        index = int(field.split('.')[1])
        if index < len(p.get('reinsurers') or []):
            p['reinsurers'][index]['premium'] = value


def build_renewal_basis(root_payload, endorsements, latest_payload):
    sources = [root_payload, *endorsements]
    basis = {'version': 'full-period-average-v1', 'sourceDays': None, 'totals': {},
             'names': [], 'issues': [], 'auto': {}, 'manual': []}
    try:
        start = _day(latest_payload.get('policyFrom'), 'Latest effective date')
        end = _day(latest_payload.get('policyTo'), 'Latest expiry date')
        if end <= start:
            raise RenewalPremiumError('The latest insurance period has no positive duration.')
        basis['sourceDays'] = (end-start).days
    except RenewalPremiumError as exc:
        basis['issues'].append({'field': 'policyTo', 'label': str(exc)})
    fields = [('originalPremium', None)]
    for index, row in enumerate(latest_payload.get('reinsurers') or []):
        name = _name_key(row.get('name')) if isinstance(row, dict) else ''
        basis['names'].append(name)
        fields.append((f'reinsurers.{index}.premium', name))
    for field, name in fields:
        try:
            total = 0.0
            for i, payload in enumerate(sources):
                label = 'Original' if i == 0 else f'Endorsement {i}'
                total += _money(payload.get('originalPremium'), label + ' 100% Premium') if name is None else _row_amount(payload, name, label)
            if not math.isfinite(total) or total < 0 or field == 'originalPremium' and total == 0:
                raise RenewalPremiumError('Calculated renewal premium is not valid; enter it manually.')
            basis['totals'][field] = total
        except RenewalPremiumError as exc:
            basis['totals'][field] = None
            basis['issues'].append({'field': field, 'label': str(exc)})
    return basis


def projected_amounts(p, basis):
    try:
        days = (_day(p.get('policyTo'), 'Renewal expiry date') - _day(p.get('policyFrom'), 'Renewal effective date')).days
    except RenewalPremiumError:
        days = 0
    result = {}
    for field, total in basis['totals'].items():
        value = None
        if days > 0 and basis.get('sourceDays') and total is not None:
            number = total / basis['sourceDays'] * days
            if math.isfinite(number):
                try:
                    rounded = premium_money(number, p)
                    positive_only = field == 'originalPremium' or (p.get('reinsuranceStructure') == 'QS' and str(p.get('classOfBusiness') or '').strip().casefold() == 'commercial general liability')
                    if math.isfinite(rounded) and (rounded > 0 if positive_only else rounded >= 0):
                        value = rounded
                except (ValueError, OverflowError):
                    pass
        if field != 'originalPremium':
            index = int(field.split('.')[1])
            rows = p.get('reinsurers') or []
            if index >= len(rows) or _name_key(rows[index].get('name')) != basis['names'][index]:
                value = None
        result[field] = value
    return result


def calculation_issues(basis, values):
    issues = copy.deepcopy(basis['issues'])
    existing = {i['field'] for i in issues}
    for field, value in values.items():
        if value is None and field not in existing:
            issues.append({'field': field, 'label': field + ': a valid automatic premium is unavailable; enter this amount manually.'})
    return issues


def seed_renewal_premiums(p, root_payload, endorsements, latest_payload):
    basis = build_renewal_basis(root_payload, endorsements, latest_payload)
    values = projected_amounts(p, basis)
    basis['auto'] = values
    p['renewalPremiumBasis'] = basis
    p['renewalPremiumManual'] = []
    p['renewalPremiumIssues'] = calculation_issues(basis, values)
    for field, value in values.items():
        _assign(p, field, value)
    return p


def refresh_renewal_premiums(p, stored, submitted):
    basis = copy.deepcopy(stored['renewalPremiumBasis'])
    values = projected_amounts(p, basis)
    manual = set(basis.get('manual') or [])
    manual.update(k for k in (submitted.get('renewalPremiumManual') or []) if k in values)
    for field, value in values.items():
        candidate = _amount(submitted, field)
        previous = _amount(stored, field)
        try:
            numeric = _money(candidate, field)
        except RenewalPremiumError:
            numeric = candidate
        if candidate != previous and numeric != previous and numeric != value:
            manual.add(field)
        if field not in manual:
            _assign(p, field, value)
            if isinstance(p.get('draftInput'), dict):
                _assign(p['draftInput'], field, value)
    basis['auto'] = values
    basis['manual'] = sorted(manual)
    p['renewalPremiumBasis'] = basis
    p['renewalPremiumManual'] = sorted(manual)
    p['renewalPremiumIssues'] = calculation_issues(basis, values)


def calculate_renewal_premiums(root_payload, endorsements, latest_payload):
    # Compatibility for callers of the pure calculator: a one-calendar-year renewal.
    from .workflow import shift_year
    p = {**latest_payload, 'policyFrom': latest_payload.get('policyTo'),
         'policyTo': shift_year(latest_payload.get('policyTo')), 'premiumRounding': 'currency-stepwise-v1',
         'reinsurers': copy.deepcopy(latest_payload.get('reinsurers') or [])}
    seed_renewal_premiums(p, root_payload, endorsements, latest_payload)
    if p['originalPremium'] is None or any(r.get('premium') is None for r in p['reinsurers']):
        raise RenewalPremiumError('Some renewal premiums cannot be calculated; enter them manually.')
    return p['originalPremium'], [r['premium'] for r in p['reinsurers']]


def renewal_installment_issues(payload):
    """Keep copied installments editable, but never announce prior-year dates."""
    if payload.get("installmentEnabled") is not True:
        return []
    try:
        start = _day(payload.get("policyFrom"), "Renewal effective date")
        expiry = _day(payload.get("policyTo"), "Renewal expiry date")
    except RenewalPremiumError:
        return [{"field": "performanceInstallments", "label": "Valid renewal coverage dates"}]
    if expiry <= start:
        return [{"field": "performanceInstallments", "label": "Valid renewal coverage dates"}]
    issues = []
    for index, row in enumerate(payload.get("performanceInstallments") or []):
        if not isinstance(row, dict):
            continue  # The standard required-field validation reports malformed rows.
        month = row.get("performanceMonth")
        try:
            if not isinstance(month, str) or len(month) != 7 or month[4] != "-":
                raise ValueError
            year, number = int(month[:4]), int(month[5:])
            month_start = date(year, number, 1)
            next_month = date(year + (number == 12), number % 12 + 1, 1)
            in_period = month_start < expiry and next_month > start
        except ValueError:
            in_period = False
        if not in_period:
            issues.append({"field": f"performanceInstallments.{index}.performanceMonth",
                           "label": f"Installment {index + 1} performance month within renewal coverage"})
        try:
            base_date = _day(row.get("paymentBaseDate"), "Payment base date")
            base_in_period = start <= base_date < expiry
        except RenewalPremiumError:
            base_in_period = False
        if not base_in_period:
            issues.append({"field": f"performanceInstallments.{index}.paymentBaseDate",
                           "label": f"Installment {index + 1} payment base date within renewal coverage"})
    return issues
