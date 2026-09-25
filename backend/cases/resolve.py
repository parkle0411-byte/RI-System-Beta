"""
案件儲存前的「參照解析」與鎖定判斷。移植自 Hatchable Alpha 的 api/cases.js
（resolveMasterReferences、resolvePersonnelSplits、resolveCaseOwner、paymentTermsSignature）。

主檔名稱比對：Alpha 用 lower(name) = lower(x)（區分重音），MySQL 的 ai_ci 排序規則會把
「Café」與「Cafe」視為相同。所以先讓資料庫用 ai_ci 縮小範圍，再用 Python 的 lower() 做與 Alpha 相同的精確比對。
"""
from django.db.models import Q

from masterdata.models import MasterRecord
from personnel.models import Personnel

from .calc.jsnum import (
    get, is_array, is_nullish, js_is_integer, js_or, js_to_number, js_to_string, js_trim, js_truthy,
)


def _lower(value):
    return js_trim(js_to_string(js_or(value, ""))).lower()


def resolve_master_references(payload):
    """ae / reinsured / class 各取「啟用中、名稱相同、display_order 最小、id 最小」的一筆。"""
    wanted = {
        "ae": payload.get("ae") or "",
        "reinsured": payload.get("reinsured") or "",
        "class": payload.get("classOfBusiness") or "",
    }
    found = {}
    for entity_type, name in wanted.items():
        if not name:
            found[entity_type] = None
            continue
        candidates = (
            MasterRecord.objects.filter(entity_type=entity_type, is_active=True, name__iexact=name)
            .order_by("display_order", "id")
        )
        found[entity_type] = next((r.pk for r in candidates if r.name.lower() == str(name).lower()), None)
    return {
        "aeMasterId": found["ae"],
        "reinsuredMasterId": found["reinsured"],
        "classMasterId": found["class"],
    }


def _supplied_id(party):
    number = js_to_number(get(party, "personnelId"))
    return int(number) if js_is_integer(number) and number > 0 else None


def resolve_personnel_splits(payload, allowed_historical_ids=()):
    """
    檢查並補齊 Performance Split 的人員（personnelId 與名稱以 Personnel 記錄為準）。
    回傳 None 表示通過，否則回傳 {error, message}。會直接修改 payload["splitParties"]。

    與 Alpha 的差別：只給名字（沒有 personnelId）而同名的人不只一位（不同部門可同名）時，
    Alpha 取到哪一位取決於資料庫的回傳順序；VM 改為拒絕並要求以 ID 指定。
    """
    parties = payload.get("splitParties")
    parties = parties if is_array(parties) else []
    if not js_truthy(get(payload, "splitEnabled")) or not parties:
        return None

    ids = [i for i in (_supplied_id(p) for p in parties) if i is not None]
    names = [n for n in (_lower(get(p, "name")) for p in parties if _supplied_id(p) is None) if n]
    people = list(Personnel.objects.filter(Q(pk__in=ids) | Q(name__in=names)).order_by("id"))
    by_id = {p.pk: p for p in people}
    by_name = {}
    for person in people:
        by_name.setdefault(person.name.lower(), []).append(person)
    historical = {int(i) for i in allowed_historical_ids}

    for party in parties:
        supplied = _supplied_id(party)
        if supplied is not None:
            person = by_id.get(supplied)
        else:
            matches = by_name.get(_lower(get(party, "name")), [])
            if len(matches) > 1:
                return {
                    "error": "invalid_personnel_split",
                    "message": "A Performance Split name matches more than one Personnel record. Select the person by ID.",
                }
            person = matches[0] if matches else None
        if person is None:
            return {
                "error": "invalid_personnel_split",
                "message": "Every Performance Split person must reference an existing Personnel record.",
            }
        if (not person.is_active or not person.is_split_eligible) and person.pk not in historical:
            return {
                "error": "invalid_personnel_split",
                "message": "New Performance Split selections must use active, split-eligible Personnel records.",
            }
        party["personnelId"] = person.pk
        party["name"] = person.name

    resolved = [p["personnelId"] for p in parties]
    if len(resolved) != len(set(resolved)):
        return {
            "error": "invalid_personnel_split",
            "message": "Performance Split requires two different Personnel records.",
        }
    return None


def resolve_case_owner(payload, allowed_historical_id=None):
    """回傳 {"id": 負責人 Personnel id 或 None}，或 {"error", "message"}。會直接修改 payload 的負責人欄位。"""
    number = js_to_number(payload.get("ownerPersonnelId"))
    if not js_is_integer(number) or number < 1:
        payload["ownerPersonnelId"] = None
        payload["ownerPersonnelName"] = ""
        return {"id": None}
    owner = Personnel.objects.filter(pk=int(number)).first()
    if owner is None:
        return {"error": "invalid_case_owner", "message": "Case owner must reference an existing Personnel record."}
    if not owner.is_active and allowed_historical_id != owner.pk:
        return {"error": "invalid_case_owner", "message": "New case-owner selections must use active Personnel."}
    payload["ownerPersonnelId"] = owner.pk
    payload["ownerPersonnelName"] = owner.name
    return {"id": owner.pk}


def _nn(value):
    """value ?? null"""
    return None if is_nullish(value) else value


def payment_terms_signature(payload):
    """
    付款條件的「內容」（Announce 之後鎖定）。Alpha 比對的是 JSON.stringify 的結果，
    所以 JSON 物件鍵的順序不同也會被當成有變動（資料庫會重排鍵的順序）；VM 改為比較內容，
    鍵的順序不同不算變動，真正的內容有變都仍然會被擋下。
    """
    installments = get(payload, "performanceInstallments")
    reinsurers = get(payload, "reinsurers")
    return {
        "paymentTermsDays": _nn(get(payload, "paymentTermsDays")),
        "installmentEnabled": get(payload, "installmentEnabled") is True,
        "installments": [
            {
                "id": js_or(get(row, "id"), ""),
                "paymentBaseDate": js_or(get(row, "paymentBaseDate"), ""),
                "paymentTermsDays": _nn(get(row, "paymentTermsDays")),
                "reinsurerPaymentTerms": js_or(get(row, "reinsurerPaymentTerms"), {}),
            }
            for row in (installments if is_array(installments) else [])
        ],
        "reinsurers": [
            {"name": js_or(get(row, "name"), ""), "paymentTermsDays": _nn(get(row, "paymentTermsDays"))}
            for row in (reinsurers if is_array(reinsurers) else [])
        ],
    }


def same_content(a, b):
    """結構相等；布林與數字不互相等（True 不等於 1），物件不看鍵的順序。"""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_content(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_content(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b
