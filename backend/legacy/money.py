"""Use the existing signed premium rounding, with explicit input validation."""
import math
from cases.calc.premium_money import premium_money

MONEY_FIELDS = ('premium', 'commission', 'tax', 'claim', 'brokerage', 'cedantNet', 'reinsurerNet')


def number(value, label):
    if value is None or isinstance(value, bool) or str(value).strip() == '':
        raise ValueError(f'{label} is required.')
    try:
        result = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        raise ValueError(f'{label} must be a finite number.')
    if not math.isfinite(result) or abs(result) > 999999999999:
        raise ValueError(f'{label} must be a finite amount within the supported range.')
    return result


def rounded(value, currency):
    return premium_money(value, {'currency': currency})


def calculate(data):
    currency = str(data.get('currency') or 'TWD').upper()
    if data.get('kind') == 'claim':
        from cases.cash_ledger import cents, amount
        claim = amount(cents(number(data.get('claim'), 'Claim amount')))
        if not claim:
            raise ValueError('Claim amount must not be zero.')
        if claim < 0 and not str(data.get('claimReason') or '').strip():
            raise ValueError('A reason is required for a negative claim.')
        for key in ('gross', 'commissionRate', 'taxRate', 'brokerage'):
            if number(data.get(key, 0), key) != 0:
                raise ValueError('Claims cannot include premium, commission, tax or brokerage.')
        return dict(gross=0, premium=0, commission=0, tax=0, brokerage=0,
                    brokeragePct=None, claim=claim, cedantNet=-claim, reinsurerNet=-claim)
    if number(data.get('claim', 0), 'Claim amount') != 0:
        raise ValueError('Endorsements and claims must be separate transactions.')
    gross = rounded(number(data.get('gross'), '100% Premium'), currency)
    share = number(data.get('share'), 'Share')
    commission_rate = number(data.get('commissionRate'), 'Commission rate')
    tax_rate = number(data.get('taxRate'), 'Tax rate')
    if not 0 < share <= 100:
        raise ValueError('Share must be greater than zero and at most 100%.')
    if not 0 <= commission_rate <= 100 or not 0 <= tax_rate <= 100:
        raise ValueError('Commission and tax rates must be between 0 and 100%.')
    premium = rounded(gross * share / 100, currency)
    commission = rounded(premium * commission_rate / 100, currency)
    tax = rounded(premium * tax_rate / 100, currency)
    brokerage = rounded(number(data.get('brokerage'), 'Brokerage amount'), currency)
    claim = rounded(number(data.get('claim', 0), 'Claim amount'), currency)
    pct = brokerage / premium * 100 if premium else (100 if brokerage > 0 else -100 if brokerage < 0 else None)
    if ((pct is not None and pct < 0) or (premium == 0 and brokerage != 0)) and not str(data.get('brokerageNote') or '').strip():
        raise ValueError('Note for Bkg. is required for negative brokerage rates or zero-premium brokerage.')
    cedant = rounded(premium - commission - tax - claim, currency)
    return dict(gross=gross, premium=premium, commission=commission, tax=tax, claim=claim,
                brokerage=brokerage, brokeragePct=pct, cedantNet=cedant,
                reinsurerNet=rounded(cedant - brokerage, currency))


def split_performance(data, amounts, rate):
    if rate is None:
        return dict(rate=None, awaitingFx=True, premiumTwd=None, incomeTwd=None, people=[])
    rate = number(rate, 'Exchange rate')
    if rate <= 0:
        raise ValueError('Exchange rate must be positive.')
    currency = data.get('currency', 'TWD')
    pct = number(data.get('aePct', 100) if data.get('subAe') else 100, 'AE share')
    if data.get('subAe') and pct not in (40, 70):
        raise ValueError('AE / Sub AE split must be 40/60 or 70/30.')
    income = rounded(amounts['brokerage'] * rate, 'TWD')
    premium = rounded(amounts['premium'] * rate, 'TWD')
    people = []
    ae_income_orig = rounded(amounts['brokerage'] * pct / 100, currency)
    ae_premium_orig = rounded(amounts['premium'] * pct / 100, currency)
    first_income = rounded(ae_income_orig * rate, 'TWD')
    first_premium = rounded(ae_premium_orig * rate, 'TWD')
    people.append(dict(name=data.get('ae', ''), pct=pct, income=first_income, premium=first_premium,
                       incomeOriginal=ae_income_orig))
    if data.get('subAe'):
        people.append(dict(name=data['subAe'], pct=100-pct, income=income-first_income,
                           premium=premium-first_premium, incomeOriginal=amounts['brokerage']-ae_income_orig))
    return dict(rate=rate, awaitingFx=False, incomeTwd=income, premiumTwd=premium, people=people)
