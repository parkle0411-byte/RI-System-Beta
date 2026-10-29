"""Shared premium precision. Claims and cash records retain their existing precision."""
from .jsnum import get, money, js_round, js_to_number, EPSILON

LEGACY = "legacy-cents"

def precision(case_data):
    case_data = case_data if isinstance(case_data, dict) else {}
    return 0 if str(case_data.get("currency") or "").strip().upper() == "TWD" and case_data.get("premiumRounding") != LEGACY else 2

def _symmetric(value, scale):
    """四捨五入、正負對稱（-50.5 → -51，與 50.5 → 51 對稱）。正數結果與 Math.round 相同。
    2026-10-21 使用者決定：全額退保的負數保費必須與原保費正好抵銷，不留 1 元／1 分差額。"""
    x = js_to_number(value)
    if x != x or x in (float("inf"), float("-inf")):
        return x
    rounded = js_round(abs(x) * scale + EPSILON * scale) / scale if scale != 1 else js_round(abs(x) + EPSILON)
    return -rounded if x < 0 and rounded else rounded + 0.0


def premium_money(value, case_data):
    data = case_data if isinstance(case_data, dict) else {}
    if data.get("premiumRounding") == LEGACY:
        return money(value)            # 受保護的歷史算法維持原樣
    return _symmetric(value, 1 if precision(data) == 0 else 100)

def premium_fields(payload):
    yield "originalPremium", "100% Premium", payload.get("originalPremium")
    for key, label in (("reinsurers", "Reinsurer"), ("performanceInstallments", "Installment")):
        for index, row in enumerate(payload.get(key) or []):
            if isinstance(row, dict):
                yield f"{key}.{index}.premium", f"{label} {index + 1} Premium", row.get("premium")

def premium_input_errors(payload, existing=None):
    from ..property_original import enabled
    if enabled(payload) and str(payload.get("currency") or "").strip().upper()!="TWD":
        from decimal import Decimal, InvalidOperation
        from ..accounting_policy import legacy_math
        old=dict((path,value) for path,_,value in premium_fields(existing or {})) if legacy_math(existing) else {}
        errors=[]
        for path,label,value in premium_fields(payload):
            if value is None or str(value).strip()=="":continue
            if path in old and value==old[path]:continue
            try:
                n=Decimal(str(value).replace(",",""))
                if n.is_finite() and n != n.quantize(Decimal(".01")):
                    errors.append(f"{label} must have at most two decimal places for {payload.get('currency')}.")
            except InvalidOperation:pass
        return errors
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
