"""Shared premium precision. Claims and cash records retain their existing precision."""
from .jsnum import get, money, js_round, js_to_number, EPSILON

LEGACY = "legacy-cents"

def precision(case_data):
    case_data = case_data if isinstance(case_data, dict) else {}
    return 0 if str(case_data.get("currency") or "").strip().upper() == "TWD" and case_data.get("premiumRounding") != LEGACY else 2

def premium_money(value, case_data):
    return js_round(js_to_number(value) + EPSILON) if precision(case_data) == 0 else money(value)

def premium_fields(payload):
    yield "originalPremium", "100% Premium", payload.get("originalPremium")
    for key, label in (("reinsurers", "Reinsurer"), ("performanceInstallments", "Installment")):
        for index, row in enumerate(payload.get(key) or []):
            if isinstance(row, dict):
                yield f"{key}.{index}.premium", f"{label} {index + 1} Premium", row.get("premium")

def premium_input_errors(payload, existing=None):
    if str(payload.get("currency") or "").strip().upper() != "TWD":
        return []
    old = dict((path, value) for path, _, value in premium_fields(existing or {})) if (existing or {}).get("premiumRounding") == LEGACY else {}
    errors = []
    for path, label, value in premium_fields(payload):
        if value is None or str(value).strip() == "":
            continue
        try:
            number = float(str(value).replace(",", ""))
            if number.is_integer():
                continue
            if path in old and value == old[path]:
                continue  # historical input can be retained, never newly supplied
            errors.append(f"{label} must be a whole number for TWD; decimals are not allowed.")
        except (ValueError, TypeError):
            pass  # normal draft validation reports invalid numbers
    return errors


def premium_source(value, case_data):
    """Start at the displayed 100% premium; retain protected historical math."""
    data = case_data if isinstance(case_data, dict) else {}
    if str(data.get("currency") or "").upper() in ("TWD", "USD") and data.get("premiumRounding") != LEGACY:
        return premium_money(value, data)
    return value
