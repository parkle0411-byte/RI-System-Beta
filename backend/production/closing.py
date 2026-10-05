"""
關帳時「整理一個案件」- 移植自 Alpha api/production-report.js closeReport() 第 241–288 行（純函式，不碰資料庫）。

  - 把報表裡這個案件的 reinsurerKey 加進 payload.confirmedProductionKeys（保留原本順序、去重，同 JavaScript 的 Set）
  - 全部 key 都確認了 → 狀態變 closed；否則維持 posted（productionPartiallyConfirmed = true）
  - 保費交易（Leg 1–3）：沒有分期的案件，全部確認後（而且原本不是 closed）一次產生整個案件全額；
    有分期的案件，每一期的所有 key 都確認就產生「該期」的交易（依該期比例，每期只產生一次）——
    2026-09-29 起（Alpha v63 同步）；以前是全部期別都確認才一次產生，分期案件在最後一期關帳前 SoA 看不到任何交易。
    產生時若有待沖銷（pendingReversalOffset），先為「已 Reverse、還沒沖過」的交易加上 -RVS{cycle} 沖銷分錄
與 Alpha v63 的 JavaScript 逐位一致（差異測試：qa/alpha_js/excerpts/production-excerpts.js）。
"""
from cases.calc.accounting import build_premium_transactions
from cases.calc.payment_terms import premium_installment_plan
from cases.calc.jsnum import get, is_array, is_nullish, js_num_str, js_or, js_to_number, js_to_string, js_truthy, json_roundtrip

from .calc import production_key_groups_for_case, production_keys_for_case


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


def _is_live(transaction):
    """還有效的保費交易：不是理賠、沒被 Reverse、也不是沖銷分錄（JavaScript 的 `t != null` 一併排除 null／undefined）。"""
    return (not is_nullish(transaction) and get(transaction, "source") != "claim"
            and get(transaction, "reversed") is not True and get(transaction, "isReversalEntry") is not True)


def _has_installment_id(transaction):
    return js_truthy(get(transaction, "installmentId"))


def _confirmed_has(confirmed, key):
    return any(_same_value_zero(c, key) for c in confirmed)


def transaction_batches(source, payload, confirmed, remaining, was_closed, base_transactions, transaction_case):
    """這次要產生保費交易的批次：[None] = 整個案件全額（沒有分期，全部確認後才產生，同以前）；
    有分期 = 每一期「所有 Production key 都確認」就產生該期的交易（每期只產生一次），回傳這些期的 plan 項目。"""
    plan = premium_installment_plan(transaction_case)
    if not plan:
        return [None] if (not was_closed and not remaining) else []
    # 舊資料：整個案件全額的交易（沒有 installmentId）已經涵蓋所有期別，不再另外產生
    if any(_is_live(t) and not _has_installment_id(t) for t in base_transactions):
        return []
    groups = production_key_groups_for_case(source)
    batches = []
    for index, entry in enumerate(plan):
        if any(_is_live(t) and get(t, "installmentId") == entry["id"] for t in base_transactions):
            continue
        keys = groups[index]["keys"] if index < len(groups) else []
        ready = all(_confirmed_has(confirmed, key) for key in keys) if keys else not remaining
        if ready:
            batches.append(entry)
    return batches


def confirm_case(source, report_rows):
    """回傳 {payload, nextStatus, remaining, closedCases}（closedCases 是 0 或 1：這次讓案件全部確認（變成 closed））。"""
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
    remaining = any(not _confirmed_has(confirmed, key) for key in production_keys_for_case(source))
    payload["productionPartiallyConfirmed"] = remaining
    next_status = "posted" if remaining else "closed"
    cycle = js_to_number(js_or(get(payload, "reversalCycle"), 0))
    transaction_case = {**payload, "twRef": js_or(get(source, "tw_ref"), get(payload, "twRef"), "")}
    base = payload["transactions"] if is_array(payload.get("transactions")) else []
    batches = transaction_batches(source, payload, confirmed, remaining, was_closed, base, transaction_case)
    if not was_closed and not remaining:
        closed_cases += 1   # 這次讓案件「全部確認」（畫面訊息的 fully Confirmed 件數）；分期案件先前各期已產生的交易不影響
    if batches:
        appended = []
        if js_truthy(get(payload, "pendingReversalOffset")):
            if any(t is None for t in base):
                raise TransactionsCorrupt()
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
        new_transactions = [
            {**t, "txNo": f"{js_to_string(get(t, 'txNo'))}-C{js_num_str(cycle)}"} if cycle > 0 else t
            for entry in batches for t in build_premium_transactions(transaction_case, entry)
        ]
        payload["transactions"] = base + appended + new_transactions
    return {"payload": payload, "nextStatus": next_status, "remaining": remaining, "closedCases": closed_cases}
