"""Owner-confirmed Facility presentation and new-draft defaults."""
import copy
from .sum_insured import all_facility

PROPERTY_INTEREST = "The Reinsured's Insurance Interest in the Real and Personal Property of the Insured including Property whilst in their Care, Custody or Control."
CGL_INTEREST = 'Reinsurance of the Reinsured’s liability under the original policy.'


def fixed_interest(payload):
    if not isinstance(payload, dict) or not all_facility(payload):
        return ''
    klass = str(payload.get('classOfBusiness') or '').strip().casefold()
    return PROPERTY_INTEREST if klass == 'property' else CGL_INTEREST if klass == 'commercial general liability' else ''


def property_qs_facility(payload):
    return (isinstance(payload, dict) and all_facility(payload)
            and str(payload.get('classOfBusiness') or '').strip().casefold() == 'property'
            and str(payload.get('reinsuranceStructure') or '').strip().upper() == 'QS')


def prepare_new_draft(payload, previous=None):
    """Set new original/renewal defaults; never apply to inherited endorsements."""
    if not isinstance(payload, dict):
        return payload
    result = copy.deepcopy(payload)
    if result.get('parentTwRef'):
        return result
    from .great_american_accounting import target
    raw = result.get('draftInput') if isinstance(result.get('draftInput'), dict) else None
    for data in (result, raw):
        if not isinstance(data, dict):
            continue
        for row in data.get('reinsurers') or []:
            if isinstance(row, dict) and target(result, row.get('name')):
                row['taxPct'] = 0
        if (property_qs_facility(result) and not property_qs_facility(previous)
                and not str(data.get('basisOfValuation') or '').strip()):
            data['basisOfValuation'] = 'Actual Cash Value'
        interest = fixed_interest(result)
        if interest:
            data['interest'] = interest
    return result


def legacy_ga_tax_error(before, after):
    """Preserve historical rates; reject newly entered nonzero rates on edits.

    2026-11-10: match the original Great American row by reinsurer name, not by
    list position, and compare rates as numbers, so reordering or removing
    another reinsurer (or 5 vs "5") never rejects the preserved original rate.
    """
    from .great_american_accounting import target
    from .calc.jsnum import js_to_number
    prior = before.get('reinsurers') if isinstance(before, dict) else []
    prior = prior if isinstance(prior, list) else []
    originals = [old.get('taxPct') for old in prior
                 if isinstance(old, dict) and target(before, old.get('name')) and old.get('taxPct') is not None]
    kept = {js_to_number(old) for old in originals}
    for row in after.get('reinsurers') or []:
        if not isinstance(row, dict) or not target(after, row.get('name')):
            continue
        value = row.get('taxPct')
        if value is None or js_to_number(value) == 0:
            continue
        if value in originals or js_to_number(value) in kept:
            continue
        return 'Great American Facility Reinsurer Tax must be 0%.'
    return ''
