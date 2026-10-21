"""Standard CGL Coverages and optional Self-Insured Retention."""
from .cgl_information import is_standard_cgl
from .calc.jsnum import WS_CLASS, js_or, js_to_string, js_trim

COVERAGES = (
    'Premises-Operations Liability',
    'Products & Completed-Operation Liability',
    'Personal & Advertising Injury Liability',
    'Medical Payment',
    'Other',
)
RISK_KEYS = ('coverages', 'coveragesOther', 'selfInsuredRetention')


def normalize_risk_details(payload, errors, *, text):
    raw = payload.get('coverages')
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        errors.append('Coverages must be a list of available options.')
        raw = []
    if len(raw) > len(COVERAGES) or any(not isinstance(item, str) or item not in COVERAGES for item in raw):
        errors.append('Coverages must use the available options.')
    return {
        'coverages': [item for item in COVERAGES if item in raw],
        # Retain the description if Other is unchecked; only active selections
        # are shown in Review and Word. Re-selecting Other can restore the text.
        'coveragesOther': text(payload.get('coveragesOther'), 3000),
        'selfInsuredRetention': text(payload.get('selfInsuredRetention'), 3000),
    }


def risk_details_issues(payload):
    if not is_standard_cgl(payload):
        return []
    selected = payload.get('coverages')
    if not isinstance(selected, list) or not selected or any(item not in COVERAGES for item in selected):
        return [{'field': 'coverages', 'label': 'Coverages — select at least one available option'}]
    if 'Other' in selected and not js_trim(js_to_string(js_or(payload.get('coveragesOther'), ''))):
        return [{'field': 'coveragesOther', 'label': 'Coverages — Other'}]
    return []


TYPE_PREFIXES = ('Products Liability', 'Commercial General Liability')
_TYPE_SUFFIXES = {'QS': 'Facultative Reinsurance', 'FACULTATIVE': 'Facultative Reinsurance', 'XOL': 'Excess of Loss Facultative Reinsurance'}


def cgl_type_prefix(payload):
    import re
    explicit = js_trim(js_to_string(js_or(payload.get('typePrefix'), '')))
    if explicit:
        return explicit
    stored = re.sub(WS_CLASS + r'+as original$', '', js_trim(js_to_string(js_or(payload.get('type'), ''))), flags=re.I | re.A)
    for suffix in (_TYPE_SUFFIXES['XOL'], _TYPE_SUFFIXES['QS']):
        if stored.endswith(suffix):
            return js_trim(stored[:-len(suffix)])
    return stored


def cgl_type(payload):
    prefix = cgl_type_prefix(payload)
    structure = js_trim(js_to_string(js_or(payload.get('reinsuranceStructure'), ''))).upper()
    suffix = _TYPE_SUFFIXES.get(structure, _TYPE_SUFFIXES['QS'])
    return f'{prefix} {suffix} as original' if prefix else ''


def type_issues(payload):
    if is_standard_cgl(payload) and cgl_type_prefix(payload) not in TYPE_PREFIXES:
        return [{'field': 'typePrefix', 'label': 'Type — select Products Liability or Commercial General Liability'}]
    return []


def liability_limit_label(payload):
    return 'Limit of Indemnity' if is_standard_cgl(payload) else 'Limit of Liability'



def underlying_issues(payload):
    if (is_standard_cgl(payload)
            and js_trim(js_to_string(js_or(payload.get('reinsuranceStructure'), ''))).upper() == 'XOL'
            and not js_trim(js_to_string(payload.get('underlyingLimits') if payload.get('underlyingLimits') is not None else ''))):
        return [{'field': 'underlyingLimits', 'label': 'Underlying Limits'}]
    return []
