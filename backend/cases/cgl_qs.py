"""Confirmed ordinary CGL QS input rules (2026-10-23).

Required-field timing follows the latest PD decision. Positive premiums apply
to originals/renewals; endorsement amounts retain their existing signs.
"""
import math
import re
from .cgl_information import is_standard_cgl


def scope(p):
    return is_standard_cgl(p) and str(p.get('reinsuranceStructure') or '').upper() in ('QS', 'FACULTATIVE')


def filled(v):
    return v is not None and str(v).strip() != ''


def number(v):
    try:
        value = float(v)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def issues(p):
    if not scope(p) or p.get('parentTwRef'):
        return []
    result = []
    def add(field, label):
        result.append({'field': field, 'label': label})
    for key, label in [('originalInsuredCn', 'Original Insured (CN)'), ('reinsuredRetention', 'Reinsured’s Retention'),
                       ('riCommPct', 'Cedant Commission'), ('taxPct', 'Cedant Tax'), ('paymentTermsDays', 'Cedant Collection Days')]:
        if not filled(p.get(key)):
            add(key, label)
    if p.get('currency') not in ('TWD', 'USD'):
        add('currency', 'CGL QS Currency must be TWD or USD')
    if filled(p.get('policyFrom')) and filled(p.get('policyTo')) and p['policyTo'] <= p['policyFrom']:
        add('policyTo', 'Expiration date must be later than Effective date')
    if filled(p.get('limitOfLiability')) and (number(p.get('limitOfLiability')) is None or number(p.get('limitOfLiability')) <= 0):
        add('limitOfLiability', 'Limit of Indemnity must be greater than 0')
    entries = p.get('reinsurers') or []
    if sum(number(r.get('sharePct')) or 0 for r in entries) > 100:
        add('reinsurers', 'Total Order Hereon must not exceed 100%')
    for i, row in enumerate(entries):
        days = number(row.get('paymentTermsDays'))
        if days is None or days < 15 or days != int(days):
            add(f'reinsurers.{i}.paymentTermsDays', f'Reinsurer {i+1} Payment Terms Days must be an integer of at least 15')
    if not p.get('parentTwRef'):
        for key, label, value in [('originalPremium', '100% Premium', p.get('originalPremium')),
                                  *[(f'reinsurers.{i}.premium', f'Reinsurer {i+1} Premium', r.get('premium')) for i, r in enumerate(entries)]]:
            if filled(value) and (number(value) is None or number(value) <= 0):
                add(key, label + ' must be greater than 0')
    for i, row in enumerate(p.get('lossRecord') or []):
        if filled(row.get('lossPaid')) and (number(row.get('lossPaid')) is None or number(row.get('lossPaid')) <= 0):
            add(f'lossRecord.{i}.lossPaid', f'Loss {i+1} Loss Amount must be greater than 0')
    if p.get('installmentEnabled'):
        for i, row in enumerate(p.get('performanceInstallments') or []):
            if number(row.get('premium')) is None or number(row.get('premium')) <= 0:
                add(f'performanceInstallments.{i}.premium', f'Installment {i+1} Premium must be greater than 0')
            for key, value, label in [('paymentTermsDays', row.get('paymentTermsDays'), 'Cedant Collection Days'),
                    *[(f'reinsurerPaymentTerms.r{j+1}', (row.get('reinsurerPaymentTerms') or {}).get(f'r{j+1}'), f'Reinsurer {j+1} Payment Terms Days') for j in range(len(entries))]]:
                days = number(value)
                if days is None or days < 15 or days != int(days):
                    add(f'performanceInstallments.{i}.{key}', f'Installment {i+1} {label} must be an integer of at least 15')
    if p.get('splitEnabled'):
        parties = p.get('splitParties') or []
        if len(parties) != 2 or tuple(number(r.get('pct')) for r in parties) not in ((40, 60), (70, 30)):
            add('splitParties', 'Reinsurance Staff / Other Staff split must be 40% / 60% or 70% / 30%')
    return result
