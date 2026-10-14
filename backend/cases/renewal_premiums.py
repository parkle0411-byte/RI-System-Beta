"""Calculate a renewal's annual premiums from its current policy chain.

An endorsement premium is the price for [effective date, original expiry),
not an annual price. Each signed change is annualized and rounded separately.
"""

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math


CENT = Decimal("0.01")
YEAR_DAYS = Decimal(365)


class RenewalPremiumError(ValueError):
    """The existing policy chain cannot safely seed a renewal premium."""


def _money(value, field):
    if value is None or isinstance(value, bool):
        raise RenewalPremiumError(f"{field} is missing or invalid. Review the policy chain before renewal.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise RenewalPremiumError(f"{field} is missing or invalid. Review the policy chain before renewal.") from None
    if not amount.is_finite():
        raise RenewalPremiumError(f"{field} is missing or invalid. Review the policy chain before renewal.")
    return amount


def _cents(amount):
    try:
        return amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise RenewalPremiumError("A policy premium is too large to calculate safely.") from None


def _number(amount):
    try:
        result = float(amount)
    except (OverflowError, ValueError):
        raise RenewalPremiumError("A renewal premium is too large to store safely.") from None
    if not math.isfinite(result) or _cents(Decimal(str(result))) != amount:
        raise RenewalPremiumError("A renewal premium is too large to store safely.")
    return result


def _day(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise RenewalPremiumError(f"{field} is invalid. Review the policy chain before renewal.") from None


def _name_key(value):
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).casefold()


def _reinsurer_amounts(payload, label):
    rows = payload.get("reinsurers")
    if not isinstance(rows, list):
        raise RenewalPremiumError(f"{label} has no valid reinsurer schedule.")
    amounts = {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise RenewalPremiumError(f"{label} reinsurer {index} is invalid.")
        key = _name_key(row.get("name"))
        if not key or key in amounts:
            raise RenewalPremiumError(f"{label} has a missing or repeated reinsurer name; enter a new policy manually.")
        amounts[key] = _money(row.get("premium"), f"{label} reinsurer {index} premium")
    return amounts


def calculate_renewal_premiums(root_payload, endorsements, latest_payload):
    """Return (100% annual premium, per-row annual reinsurer premiums).

    ``endorsements`` is an ordered iterable of announced, active endorsement
    payloads from the same policy root, ending at the renewal source. The
    caller handles status, chain locks, and selection of the latest case.
    """
    start = _day(root_payload.get("policyFrom"), "Original effective date")
    expiry = _day(root_payload.get("policyTo"), "Original expiry date")
    if expiry <= start:
        raise RenewalPremiumError("Original policy dates are invalid for renewal.")

    latest_rows = latest_payload.get("reinsurers")
    if not isinstance(latest_rows, list) or not latest_rows:
        raise RenewalPremiumError("The latest case has no reinsurer schedule.")
    latest_names = list(_reinsurer_amounts(latest_payload, "Latest case"))
    root_amounts = _reinsurer_amounts(root_payload, "Original policy")
    annual = _cents(_money(root_payload.get("originalPremium"), "Original premium"))
    by_reinsurer = {name: _cents(root_amounts.get(name, Decimal(0))) for name in latest_names}

    for sequence, payload in enumerate(endorsements, 1):
        effective = _day(payload.get("endoEffectiveDate"), f"Endorsement {sequence} effective date")
        if not start <= effective < expiry:
            raise RenewalPremiumError(f"Endorsement {sequence} effective date is outside the original policy period.")
        days = Decimal((expiry - effective).days)
        annual += _cents(_money(payload.get("originalPremium"), f"Endorsement {sequence} premium") * YEAR_DAYS / days)
        amounts = _reinsurer_amounts(payload, f"Endorsement {sequence}")
        for name in latest_names:
            if name in amounts:
                by_reinsurer[name] += _cents(amounts[name] * YEAR_DAYS / days)

    annual = _cents(annual)
    result = [_cents(by_reinsurer[name]) for name in latest_names]
    if annual <= 0 or any(amount < 0 for amount in result):
        raise RenewalPremiumError("Calculated renewal premiums are not valid for a new policy; review the chain manually.")
    return _number(annual), [_number(amount) for amount in result]


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
