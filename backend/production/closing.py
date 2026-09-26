"""
關帳時「整理一個案件」- 移植自 Alpha api/production-report.js closeReport() 第 241–288 行（純函式，不碰資料庫）。

  - 把報表裡這個案件的 reinsurerKey 加進 payload.confirmedProductionKeys（保留原本順序、去重，同 JavaScript 的 Set）
  - 全部 key 都確認了（而且原本不是 closed）→ 狀態變 closed，並產生保費交易（Leg 1–3）；
    若有待沖銷（pendingReversalOffset），先為「已 Reverse、還沒沖過」的交易加上 -RVS{cycle} 沖銷分錄
  - 否則維持 posted（productionPartiallyConfirmed = true）
與 Alpha 的 JavaScript 逐位一致（差異測試：qa/alpha_js/excerpts/production-excerpts.js）。
"""
from cases.calc.accounting import build_premium_transactions
from cases.calc.jsnum import get, is_array, is_nullish, js_num_str, js_or, js_to_number, js_to_string, js_truthy, json_roundtrip

from .calc import production_keys_for_case


class TransactionsCorrupt(Exception):
    """payload.transactions 裡有 null（Alpha 在這裡會拋 TypeError）。"""


def _same_value_zero(a, b):
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b or (a != a and b != b)
    return type(a) is type(b) and a == b


def _set_add(items, value):
    if not any(_same_value_zero(x, value) for x in items):
        items.append(value)


def _eligible(transaction):
    if is_nullish(transaction):
        raise TransactionsCorrupt()
    return (get(transaction, "reversed") is True and get(transaction, "isReversalEntry") is not True
            and get(transaction, "reversalOffsetApplied") is not True)


def confirm_case(source, report_rows):
    """回傳 {payload, nextStatus, remaining, closedCases}（closedCases 是 0 或 1）。"""
    closed_cases = 0
    payload = json_roundtrip(js_or(get(source, "payload"), {}))
    was_closed = get(source, "status") == "closed"
    confirmed = []
    existing = get(payload, "confirmedProductionKeys")
    for key in (existing if is_array(existing) else []):
        _set_add(confirmed, key)
    for row in report_rows:
        _set_add(confirmed, js_to_string(get(row, "reinsurerKey")))
    payload["confirmedProductionKeys"] = confirmed
    remaining = any(not any(_same_value_zero(c, key) for c in confirmed) for key in production_keys_for_case(source))
    payload["productionPartiallyConfirmed"] = remaining
    next_status = "posted" if remaining else "closed"
    if not was_closed and not remaining:
        cycle = js_to_number(js_or(get(payload, "reversalCycle"), 0))
        appended = []
        base = payload["transactions"] if is_array(payload.get("transactions")) else []
        if js_truthy(get(payload, "pendingReversalOffset")):
            reversal_entries = [{
                **t,
                "txNo": f"{js_to_string(get(t, 'txNo'))}-RVS{js_num_str(cycle)}",
                "amount": -js_to_number(js_or(get(t, "amount"), 0)),
                "label": f"Reversal of {js_to_string(get(t, 'txNo'))}",
                "isReversalEntry": True, "settlement": "open", "reversed": False, "settledAt": None, "settledBy": None,
            } for t in base if _eligible(t)]
            appended = appended + reversal_entries
            base = [{**t, "reversalOffsetApplied": True} if _eligible(t) else t for t in base]
            payload["pendingReversalOffset"] = False
        transaction_case = {**payload, "twRef": js_or(get(source, "tw_ref"), get(payload, "twRef"), "")}
        new_transactions = [
            {**t, "txNo": f"{js_to_string(get(t, 'txNo'))}-C{js_num_str(cycle)}"} if cycle > 0 else t
            for t in build_premium_transactions(transaction_case)
        ]
        payload["transactions"] = base + appended + new_transactions
        closed_cases += 1
    return {"payload": payload, "nextStatus": next_status, "remaining": remaining, "closedCases": closed_cases}
