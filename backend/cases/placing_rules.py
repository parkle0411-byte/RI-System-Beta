"""Owner-confirmed QS underwriting rules; server-owned new-case version.

Legacy cases are not promoted by editing them. New renewals/endorsements are
promoted explicitly, retaining legacy free text for human confirmation.
"""
import copy
import re
from decimal import Decimal, InvalidOperation

VERSION = 'placing-qs-20261028-v1'
KEY = 'placingRulesVersion'
BUSINESSES = ('Manufacturer', 'Distributor', 'Importer', 'Exporter', 'Other')
REGIONS = ('USA/Canada', 'Rest of World', 'Other')
INTEREST = 'Reinsurance of the Reinsured’s liability under the original policy.'
NONE = 'None - other than as may exist in this document or in the wording that forms part of this contract.'
RETENTION = 'Advice of Reinsured’s retention waived'

def enabled(p):
    return isinstance(p, dict) and p.get(KEY) == VERSION and str(p.get('reinsuranceStructure') or '').upper() == 'QS' and p.get('classOfBusiness') in ('Property', 'Commercial General Liability')

def cgl(p):
    return enabled(p) and p.get('classOfBusiness') == 'Commercial General Liability'

def named(p):
    return [r for r in p.get('reinsurers') or [] if isinstance(r, dict) and str(r.get('name') or '').strip()]

def is_facility(name):
    from .accounting_policy import facility
    return facility(name) or bool(re.search(r'\(Facility\)\s*$',str(name or ''),re.I))

def has_ordinary(p):
    return not named(p) or any(not is_facility(r.get('name')) for r in named(p))

def promote(p, source=None):
    p[KEY] = VERSION
    if p.get('classOfBusiness') != 'Commercial General Liability':
        return p
    info = p.setdefault('cglInformation', {})
    if not isinstance(info, dict):
        return p
    if source and not enabled(source):
        old = str(info.get('insuredBusiness') or '')
        info.update(insuredBusinessSelections=['Other'] if old else [], insuredBusinessOther=old,
                    businessLegacyText=old, businessLegacyConfirmed=not bool(old))
        for row in info.get('estimatedTurnover') or []:
            if isinstance(row, dict):
                old_region = str(row.get('region') or '')
                row.update(region='Other' if old_region else '', regionOther=old_region,
                           legacyRegionText=old_region, legacyRegionConfirmed=not bool(old_region))
    else:
        info.setdefault('insuredBusinessSelections', [])
        info.setdefault('insuredBusinessOther', '')
        if source and info.get('businessLegacyText') and 'Other' in info.get('insuredBusinessSelections', []):
            info['businessLegacyConfirmed'] = False
        if source:
            for row in info.get('estimatedTurnover') or []:
                if isinstance(row, dict) and row.get('legacyRegionText') and row.get('region') == 'Other':
                    row['legacyRegionConfirmed'] = False
    return p

def business_text(info):
    return '\n'.join((str(info.get('insuredBusinessOther') or '').strip() if x == 'Other' else x)
                     for x in info.get('insuredBusinessSelections') or [] if x in BUSINESSES)

def normalize_extra(inp, value):
    if inp.get(KEY) == VERSION:
        value[KEY] = VERSION
    value['coReinsuranceWarranty'] = str(inp.get('coReinsuranceWarranty') or '')[:3000]
    if cgl(value):
        raw = inp.get('cglInformation')
        raw = raw if isinstance(raw,dict) else {}
        info = value.get('cglInformation') or {}
        selected = raw.get('insuredBusinessSelections')
        info['insuredBusinessSelections'] = copy.deepcopy(selected) if isinstance(selected, list) else []
        for k in ('insuredBusinessOther', 'businessLegacyText'):
            info[k] = str(raw.get(k) or '')[:3000]
        info['businessLegacyConfirmed'] = raw.get('businessLegacyConfirmed') is True
        info['insuredBusiness'] = business_text(info)
        raw_rows = raw.get('estimatedTurnover') or []
        for i, row in enumerate(info.get('estimatedTurnover') or []):
            r = raw_rows[i] if i < len(raw_rows) and isinstance(raw_rows[i], dict) else {}
            for k in ('regionOther', 'legacyRegionText'):
                row[k] = str(r.get(k) or '')[:3000]
            row['legacyRegionConfirmed'] = r.get('legacyRegionConfirmed') is True
        value['cglInformation'] = info

def share_issues(p, existing=None):
    """Validate newly entered/changed shares, preserving inherited historical zeroes."""
    issues, total = [], Decimal(0)
    old = (existing or {}).get('reinsurers') or []
    inherited = ((p.get('endorsementSource') or {}).get('reinsurers') or []) if p.get('parentTwRef') else []
    for i, row in enumerate(p.get('reinsurers') or []):
        if not isinstance(row, dict):
            continue
        raw = row.get('sharePct')
        if raw is None or str(raw).strip() == '':
            continue  # Draft blank is checked separately at the workflow boundary.
        try:
            n = Decimal(str(raw))
            if not n.is_finite():
                raise InvalidOperation
            total += n
            prior = inherited[i] if i < len(inherited) else old[i] if i < len(old) else None
            unchanged = (bool(inherited) or not enabled(existing or {})) and isinstance(prior, dict) and prior.get('name') == row.get('name') and prior.get('sharePct') == raw
            if not unchanged and (n <= 0 or n > 100 or n.as_tuple().exponent < -8):
                issues.append({'field': f'reinsurers.{i}.sharePct', 'label': 'Order Hereon must be greater than 0, at most 100%, with at most 8 decimal places.'})
        except (InvalidOperation, ValueError):
            issues.append({'field': f'reinsurers.{i}.sharePct', 'label': 'Order Hereon must be a valid percentage.'})
    if total > 100:
        issues.append({'field': 'reinsurers', 'label': 'Total Order Hereon must not exceed 100%.'})
    return issues

def extra_issues(p):
    if not enabled(p):
        return []
    out = []
    def add(field, label): out.append({'field': field, 'label': label})
    if p.get('classOfBusiness') == 'Property':
        if not str(p.get('basisOfValuation') or '').strip(): add('basisOfValuation', 'Basis of Valuation')
    if cgl(p):
        if not str(p.get('deductibles') or '').strip() and not str(p.get('selfInsuredRetention') or '').strip():
            add('deductibles', 'Complete Deductibles or Self-Insured Retention.')
        info = p.get('cglInformation')
        info = info if isinstance(info,dict) else {}
        choices = info.get('insuredBusinessSelections')
        if not isinstance(choices, list) or not choices or any(x not in BUSINESSES for x in choices):
            add('cglInformation.insuredBusinessSelections', 'Insured’s Business — select at least one available option')
        if 'Other' in (choices or []) and not str(info.get('insuredBusinessOther') or '').strip():
            add('cglInformation.insuredBusinessOther', 'Insured’s Business — Other')
        if info.get('businessLegacyText') and info.get('businessLegacyConfirmed') is not True:
            add('cglInformation.businessLegacyConfirmed', 'Confirm the inherited Insured’s Business text.')
        for i, row in enumerate(info.get('estimatedTurnover') or []):
            if not isinstance(row,dict):
                add(f'cglInformation.estimatedTurnover.{i}', 'Estimated Turnover must contain valid entries.')
                continue
            if row.get('region') not in REGIONS: add(f'cglInformation.estimatedTurnover.{i}.region', 'Turnover Region must use an available option.')
            if row.get('region') == 'Other' and not str(row.get('regionOther') or '').strip(): add(f'cglInformation.estimatedTurnover.{i}.regionOther', 'Turnover Region — Other')
            if row.get('legacyRegionText') and row.get('legacyRegionConfirmed') is not True: add(f'cglInformation.estimatedTurnover.{i}.legacyRegionConfirmed', 'Confirm the inherited Turnover Region text.')
    return out

def adjust_issues(p, issues):
    if not enabled(p):
        return issues
    def keep(x):
        f = x.get('field', '')
        if f == 'aggregateLimit' and p.get('aggregateLimit') == 0: return False
        if f == 'reinsuredRetention': return False
        if cgl(p) and (f in ('interest', 'deductibles', 'situations') or f.startswith('situations.')):
            # An optional address still validates its postcode when supplied.
            if f.endswith('.postcode'):
                i = int(f.split('.')[1]); row = (p.get('situations') or [])[i]
                return bool(str(row.get('postcode') or '').strip())
            return False
        return True
    return [x for x in issues if keep(x)] + extra_issues(p)

def underwriting_issues(p):
    """Risk-only gate used by Placing Slip; finance and placement identity are not required."""
    from .draft_input import input_for
    from .draft import validate_announce_ready, normalize_draft
    p = copy.deepcopy(input_for(p))
    p.pop('draftInput', None)
    for key in ('originalPremium','riCommPct','taxPct','paymentTermsDays'):
        p[key] = None
    p['installmentEnabled'], p['performanceInstallments'] = False, []
    p['splitEnabled'], p['splitParties'] = False, []
    for row in p.get('reinsurers') or []:
        for key in ('premium','sharePct','riCommPct','taxPct','paymentTermsDays'):
            row[key] = None
    if not p.get('newOrRenew'): p['newOrRenew'] = 'Renew' if p.get('renewedFromTwRef') else 'New'
    clean = normalize_draft(p)
    if clean['errors']:
        return [{'field':'riskFormat','label':x} for x in clean['errors']]
    issues = validate_announce_ready(clean['value'], allow_zero_loss_years=True, case_kind='renewal' if p.get('renewedFromTwRef') else 'original')
    financial = ('reinsurers', 'originalPremium', 'riCommPct', 'taxPct', 'paymentTermsDays', 'manualTwRef',
                 'ownerPersonnelId', 'originalInsuredCn', 'newOrRenew', 'performanceInstallments', 'installmentEnabled', 'splitParties', 'renewalPremium')
    return [i for i in issues if not any(i['field'] == k or i['field'].startswith(k + '.') for k in financial)
            and i['field'] not in ('draftInput',)]

def adj_rate(p):
    """Period turnover converted through TWD using the policy inception month."""
    if not cgl(p): return None
    from fxrates.models import FxRate
    month = str(p.get('policyFrom') or '')[:7]
    rates = {r.currency: r.rate for r in FxRate.objects.filter(year_month=month)}
    rates['TWD'] = Decimal(1)
    target = p.get('currency')
    try:
        total = Decimal(0)
        entries = (p.get('cglInformation') or {}).get('estimatedTurnover') or []
        if not entries or p.get('originalPremium') is None: return 'N/A'
        for row in entries:
            amount = Decimal(str(row['amount']))
            source = row.get('currency')
            total += amount if source == target else amount * rates[source] / rates[target]
        if total <= 0: return 'N/A'
        return f'{Decimal(str(p["originalPremium"])) / total * 100:.6f}%'
    except (KeyError, TypeError, ValueError, InvalidOperation, ZeroDivisionError):
        return 'N/A'
