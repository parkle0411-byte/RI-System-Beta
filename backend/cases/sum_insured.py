"""Location coverage, unique item names and Facility conversion for Sum Insured."""
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext

from .calc.jsnum import UNDEFINED, WS_CLASS, get, is_array, is_nullish, js_is_finite, js_is_integer, js_to_number, js_to_string, js_trim


def item_name(value):
    return js_trim("" if is_nullish(value) else js_to_string(value))


def item_key(value):
    return re.sub(WS_CLASS + "+", " ", item_name(value)).lower()


def all_facility(payload):
    rows = get(payload, "reinsurers")
    named = [row for row in rows if item_name(get(row, "name"))] if is_array(rows) else []
    return bool(named) and all(re.search(r"\(Facility\)\s*$", item_name(get(row, "name")), re.I) for row in named)


def location_index(row, count):
    raw = get(row, "locationIndex")
    # Old Cases without this field used Location 1; explicit null is unassigned.
    if raw is UNDEFINED:
        raw = 0
    if is_nullish(raw) or item_name(raw) == "":
        return None
    value = js_to_number(raw)
    return int(value) if js_is_integer(value) and 0 <= value < count else None


def placement_issues(payload):
    rows, situations = get(payload, "sumInsured"), get(payload, "situations")
    rows = rows if is_array(rows) else []
    situations = situations if is_array(situations) else []
    facility = all_facility(payload)
    seen, covered, issues = set(), set(), []
    for index, row in enumerate(rows):
        location = 0 if facility else location_index(row, len(situations))
        if not facility:
            if location is None:
                issues.append({"field": f"sumInsured.{index}.locationIndex", "label": f"Sum insured {index + 1} must be assigned to a valid Location", "kind": "location"})
            else:
                covered.add(location)
        name = item_key(get(row, "category"))
        key = (location, name)
        if name and location is not None:
            if key in seen:
                group = "Facility items" if facility else f"Location {location + 1}"
                issues.append({"field": f"sumInsured.{index}.category", "label": f"Sum insured {index + 1} Interest insured must be unique within {group}", "kind": "duplicate"})
            seen.add(key)
    if not facility:
        for index in range(len(situations)):
            if index not in covered:
                issues.append({"field": f"sumInsuredLocation.{index}", "label": f"Location {index + 1} requires at least one Sum Insured entry", "kind": "location"})
    return issues


def merge_facility_items(rows):
    result, groups = [], {}
    for row in rows:
        if not isinstance(row, dict):
            result.append(row)
            continue
        name = item_key(row.get("category"))
        if not name or name not in groups:
            item = {**row, "category": item_name(row.get("category")), "locationIndex": None}
            result.append(item)
            if name:
                groups[name] = item
            continue
        item = groups[name]
        raw_a, raw_b = item.get("amount"), row.get("amount")
        a, b = js_to_number(raw_a), js_to_number(raw_b)
        # Incomplete amounts remain incomplete instead of silently becoming zero.
        valid = not is_nullish(raw_a) and not is_nullish(raw_b) and item_name(raw_a) and item_name(raw_b) and js_is_finite(a) and js_is_finite(b)
        item["amount"] = a + b if valid else None
    return result


def prepare_transition(previous, incoming):
    """Also handle API edits that change security but leave original rows intact.

    An already distributed/merged UI payload is kept as submitted.
    """
    if not isinstance(incoming, dict) or not isinstance(previous, dict):
        return incoming
    old_rows, new_rows = previous.get("sumInsured"), incoming.get("sumInsured")
    if all_facility(previous) == all_facility(incoming) or not isinstance(new_rows, list) or new_rows != old_rows:
        return incoming
    if all_facility(incoming):
        rows = merge_facility_items(new_rows)
    else:
        # 2026-10-14：全 Facility 改成混合時，只清空沒有有效 Location 的項目；已指到存在的 Location 就保留
        # （舊資料預設記在 Location 1，若一律清空，使用者重新選回 Location 1 會被視為「沒變」而再次清空，永遠無法 Announce）
        count = len(get(incoming, "situations")) if is_array(get(incoming, "situations")) else 0
        rows = [row if not isinstance(row, dict) or location_index(row, count) is not None else {**row, "locationIndex": None}
                for row in new_rows]
    return {**incoming, "sumInsured": rows}


def limit_warning(payload):
    """Compare Word-displayed totals; this is never an Announce readiness issue."""
    from .cgl_information import is_standard_cgl
    if is_standard_cgl(payload):
        return None
    rows, raw_limit = get(payload, "sumInsured"), get(payload, "limitOfLiability")
    if not is_array(rows) or not rows or is_nullish(raw_limit) or not item_name(raw_limit):
        return None
    limit = js_to_number(raw_limit)
    if not js_is_finite(limit) or limit < 0:
        return None
    if any(is_nullish(get(row, "amount")) or not item_name(get(row, "amount")) or not js_is_finite(js_to_number(get(row, "amount"))) or js_to_number(get(row, "amount")) <= 0 for row in rows):
        return None
    def index(row):
        value = js_to_number(get(row, "locationIndex"))
        return value if js_is_integer(value) and value >= 0 else 0
    def word_number(value):
        match = re.match(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", item_name(value))
        number = float(match.group()) if match else 0.0
        return number if js_is_finite(number) else 0.0
    ordered = rows if all_facility(payload) else sorted(rows, key=index)
    total = 0.0
    for row in ordered:
        total += word_number(get(row, "amount"))
    if not js_is_finite(total):
        return None
    currency = item_name(get(payload, "currency")).upper() or "TWD"
    digits = 2 if currency == "USD" else 0
    def format_money(value):
        decimal = Decimal(js_to_string(word_number(value)))
        with localcontext() as context:
            context.prec = max(32, decimal.adjusted() + digits + 4)
            rounded = decimal.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
        return format(rounded, f",.{digits}f")
    total_text, limit_text = format_money(total), format_money(raw_limit)
    if total_text == limit_text:
        return None
    return {"code": "sum_insured_limit_mismatch", "currency": currency, "total": total_text, "limit": limit_text,
            "message": f"Total Sum Insured ({currency} {total_text}) differs from Limit of Liability ({currency} {limit_text}). You can continue."}
