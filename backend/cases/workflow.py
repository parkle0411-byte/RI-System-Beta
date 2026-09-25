"""
案件流程（Announce、Endorsement、Renewal、Reverse、通知會計）中「不碰資料庫」的純邏輯。
移植自 Hatchable Alpha 的 api/case-announce.js 與 api/case-workflow.js，
並與 Alpha 的原始 JavaScript 做差異測試（backend/qa/alpha_js/excerpts/api-excerpts.js）。

JavaScript 語意（空白的定義、Number()、展開運算子、Date.UTC 的溢位與 0–99 年）都沿用 jsnum.py。
"""
import copy
import re

from .calc.jsnum import (
    UNDEFINED, civil_from_days, days_from_civil, get, is_array, js_is_integer, js_number_out,
    js_or, js_spread, js_to_number, js_to_string, js_trim, js_upper, strip_ws_regex,
)

_FACILITY_SUFFIX = strip_ws_regex(r"\s*\(Facility\)\s*\Z", re.IGNORECASE | re.ASCII)
_WS_RUN = strip_ws_regex(r"\s+")
_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-[0-9]{2}")
_FULL_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")


# ---------- Announce ----------

def reinsurer_key(value):
    """String(value || '').replace(/\\s*\\(Facility\\)\\s*$/i, '').trim().toLowerCase().replace(/\\s+/g, ' ')"""
    text = js_to_string(js_or(value, ""))
    text = js_trim(_FACILITY_SUFFIX.sub("", text, count=1)).lower()
    return _WS_RUN.sub(" ", text)


def required_reinsurers(payload):
    rows = get(payload, "reinsurers")
    keys = [reinsurer_key(get(row, "name")) for row in (rows if is_array(rows) else [])]
    return list(dict.fromkeys(k for k in keys if k))  # new Set(...) 保留第一次出現的順序


def coverage_for(payload, files):
    """files：[{id, kind, reinsurers, is_selected}]，回傳與 Alpha 相同的 coverage 物件。"""
    selected = [f for f in files if f["is_selected"]]
    required = required_reinsurers(payload)
    offer = any(f["kind"] == "offer" for f in selected)
    evidence = set()
    for f in selected:
        if f["kind"] in ("signed", "confirmation"):
            names = f["reinsurers"] if is_array(f["reinsurers"]) else []
            for name in names:
                evidence.add(reinsurer_key(name))
    missing = [name for name in required if name not in evidence]
    return {
        "offer": offer, "required": required, "missing": missing,
        "ready": offer and len(required) > 0 and len(missing) == 0,
        "selected": sorted(str(f["id"]) for f in selected),
    }


def same_ids(left, right):
    a = sorted(js_to_string(x) for x in (left if is_array(left) else []))
    b = sorted(js_to_string(x) for x in (right if is_array(right) else []))
    return a == b


def reference_prefix(payload):
    """TW + Class 代碼（最多 12 個英數字，沒有則 XX）+ 生效年（2 位）+ 月。生效日不合格式回傳 None。"""
    class_code = js_upper(js_trim(js_to_string(js_or(get(payload, "classCode"), ""))))
    class_code = re.sub(r"[^A-Z0-9]", "", class_code)[:12] or "XX"
    match = _DATE.fullmatch(js_to_string(js_or(get(payload, "policyFrom"), "")))
    if not match:
        return None
    return f"TW{class_code}{match.group(1)[-2:]}{match.group(2)}"


# ---------- Endorsement / Renewal / Reverse / 通知會計 ----------

def _js_date_utc_iso(year, month_index, day, set_day_zero_if_month_differs, expected_month_index):
    """Date.UTC(year, monthIndex, day)（含 0–99 年與月／日溢位）→ 必要時 setUTCDate(0) → toISOString().slice(0, 10)"""
    if 0 <= year <= 99:
        year += 1900
    year += month_index // 12
    month_index = month_index % 12
    days = days_from_civil(year, month_index + 1, 1) + (day - 1)
    y, m, d = civil_from_days(days)
    if set_day_zero_if_month_differs and m - 1 != expected_month_index:
        y, m, d = civil_from_days(days_from_civil(y, m, 1) - 1)  # setUTCDate(0)：前一個月的最後一天
    if 0 <= y <= 9999:
        head = f"{y:04d}"
    else:
        head = ("+" if y > 0 else "-") + f"{abs(y):06d}"
    return f"{head}-{m:02d}-{d:02d}"[:10]


def shift_year(value):
    """把日期往後推一年（2/29 → 2/28）；格式不合回傳 ''。"""
    match = _FULL_DATE.fullmatch(js_to_string(js_or(value, "")))
    if not match:
        return ""
    year, month, day = (int(g) for g in match.groups())
    return _js_date_utc_iso(year + 1, month - 1, day, True, month - 1)


def reset_shared_payload(payload):
    """Endorsement / Renewal 的新 Draft：清掉屬於「舊案件實際發生過的事」的欄位。"""
    return {
        **payload,
        "status": "draft", "postedAt": "", "confirmedProductionKeys": [], "productionExclusions": {},
        "productionPartiallyConfirmed": False, "endorsements": [], "transactions": [], "claims": [],
        "statementNo": "", "reversalCycle": 0, "pendingReversalOffset": None, "accountingNotifications": [],
        # 收付款帳本（誰實際付了／收了哪一期）不能沿用舊案件的，否則新草稿會像已經有付款紀錄
        "paymentEntries": [], "paymentScheduleReviewRequired": False,
    }


def _rows(value):
    return value if is_array(value) else []


def build_endorsement_payload(source_payload, root_tw_ref, existing_count):
    payload = reset_shared_payload(copy.deepcopy(source_payload))
    payload["parentTwRef"] = root_tw_ref
    payload["endorsementSeq"] = existing_count + 1
    payload["endoEffectiveDate"] = ""
    payload["endoTypes"] = []
    payload["endoText"] = ""
    payload["originalPremium"] = None
    payload["exchRate"] = None
    payload["statementNo"] = ""
    payload["claims"] = []
    payload["reinsurers"] = [{**js_spread(row), "premium": None, "settlementRef": ""} for row in _rows(payload.get("reinsurers"))]
    return payload


def build_renewal_payload(source_payload, source_tw_ref):
    payload = reset_shared_payload(copy.deepcopy(source_payload))
    payload["parentTwRef"] = ""
    payload["endorsementSeq"] = None
    payload["renewedFromTwRef"] = js_or(source_tw_ref, "")
    payload["newOrRenew"] = "Renew"
    payload["policyFrom"] = shift_year(payload.get("policyFrom", UNDEFINED))
    payload["policyTo"] = shift_year(payload.get("policyTo", UNDEFINED))
    payload["endoEffectiveDate"] = ""
    payload["endoTypes"] = []
    payload["endoText"] = ""
    payload["statementNo"] = ""
    payload["claims"] = []
    payload["reinsurers"] = [{**js_spread(row), "settlementRef": ""} for row in _rows(payload.get("reinsurers"))]
    return payload


class TransactionsCorrupt(Exception):
    """transactions 裡有 null 的項目。Alpha 的 JavaScript 會在這裡拋出 TypeError（讀 null 的屬性），Reverse 直接失敗；
    VM 維持「不能 Reverse」，但以明確的錯誤回覆（409），而不是未處理的伺服器錯誤。"""


def build_reversed_payload(source_payload):
    payload = copy.deepcopy(source_payload)
    if any(t is None for t in _rows(payload.get("transactions"))):
        raise TransactionsCorrupt()
    payload["reversalCycle"] = js_number_out(js_to_number(js_or(payload.get("reversalCycle", UNDEFINED), 0)) + 1)
    payload["transactions"] = [
        t if get(t, "isReversalEntry") is True else {**js_spread(t), "reversed": True}
        for t in _rows(payload.get("transactions"))
    ]
    payload["pendingReversalOffset"] = True
    payload["confirmedProductionKeys"] = []
    payload["productionPartiallyConfirmed"] = False
    return payload


def append_notification(source_payload, notification):
    payload = copy.deepcopy(source_payload)
    payload["accountingNotifications"] = [*_rows(payload.get("accountingNotifications")), notification]
    return payload


def is_integer_number(value):
    number = js_to_number(value)
    return js_is_integer(number)
