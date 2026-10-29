"""Case selection restrictions confirmed by the owner, 2026-10-22.

Selection scope is independent of accounting scope. Existing cases are never
rewritten; invalid combinations must be corrected before a new case write.
"""
from .swiss_cgl import SWISS_NAME

RULES = (("Lloyd's Underwriter Syndicate No. 0609 AUW (Facility)", 'AUW Facility', ('Property',)), ('Allianz Global Corporate & Specialty SE, Hong Kong Branch (Facility)', 'Allianz Facility', ('Property',)), ('Great American Insurance Company, Singapore Branch (Facility)', 'Great American Facility', ('Property',)), ('QBE Hongkong & Shanghai Insurance Limited (Facility)', 'QBE Facility', ('Property',)), ('Swiss Re Asia Pte. Ltd., Hong Kong Branch (Facility)', 'Swiss Re Asia Facility', ('Property', 'Commercial General Liability')))


def selection_issues(payload):
    if not isinstance(payload, dict):
        return []
    rows = payload.get("reinsurers")
    if not isinstance(rows, list):
        return []
    klass = str(payload.get("classOfBusiness") or "").strip().casefold()
    structure = str(payload.get("reinsuranceStructure") or "").strip().upper()
    issues = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        name = " ".join(str(row.get("name") or "").split()).casefold()
        for target, label, allowed in RULES:
            if name == target.casefold() and klass not in [c.casefold() for c in allowed]:
                issues.append({"field": f"reinsurers.{index}.name",
                               "label": f"Reinsurer {index + 1}: {label} is available only for {' or '.join(allowed)}."})
                break
            if name == target.casefold() and target == SWISS_NAME and klass == 'commercial general liability' and structure != 'QS':
                issues.append({"field": "reinsuranceStructure",
                               "label": f"Reinsurer {index + 1}: Swiss Re CGL Facility is available only for Quota Share (QS)."})
                break
    return issues
