"""
記帳帳本的純函式 - 對應 Alpha api/accounting.js 的 ledgerRows（不碰資料庫，差異測試直接呼叫）。

與 Alpha 的差異：paymentEntries／transactions 裡不是物件的項目一律略過；
Alpha 對 transactions 也是略過（transaction?.source），但 paymentEntries 裡有 null 時整個帳本會拋錯。
"""
from .calc.accounting import reconciliation_ref_for
from .calc.jsnum import get, is_array, js_locale_key, js_or, js_to_number, js_to_string
from .calc.payment_terms import build_payment_schedule


def _text(value):
    """String(value || "")"""
    return js_to_string(js_or(value, ""))


def _objects(value):
    return [row for row in value if isinstance(row, dict)] if is_array(value) else []


def ledger_rows(cases, now=None):
    rows, warnings = [], []
    for c in cases:
        payload = c["payload"]
        schedule = build_payment_schedule(payload, now)
        if schedule["reviewRequired"]:
            warnings.append({"caseUid": c["caseUid"], "twRef": c["twRef"], "issues": schedule["issues"]})
        entries = _objects(payload.get("paymentEntries"))
        for item in schedule["items"]:
            cedant = item["partyType"] == "cedant"
            rows.append({
                "key": c["caseUid"] + ":" + item["scheduleKey"],
                "caseUid": c["caseUid"], "caseRowVersion": c["rowVersion"],
                "twRef": c["twRef"], "caseStatus": c["status"], "announcedAt": c["announcedAt"],
                "source": "premium", "scheduleKey": item["scheduleKey"],
                "installmentId": item["installmentId"], "installmentLabel": item["installmentLabel"],
                "partyType": item["partyType"], "partyName": item["partyName"],
                "legType": "Cedant" if cedant else "Reinsurer",
                "reinsured": c["reinsured"],
                "reinsurer": item["partyName"] if item["partyType"] == "reinsurer" else "",
                "label": ("Receivable from " if cedant else "Payable to ") + item["partyName"],
                "amount": item["amount"], "paid": item["paid"], "outstanding": item["outstanding"],
                "currency": item["currency"], "baseDate": item["baseDate"], "termsDays": item["termsDays"],
                "dueDate": item["dueDate"], "dueTime": item["dueTime"], "paymentStatus": item["status"],
                "partial": item["partial"], "settlement": "settled" if item["status"] == "settled" else "open",
                "reviewRequired": item["status"] == "pending_review",
                "entries": [e for e in entries if get(e, "scheduleKey") == item["scheduleKey"]],
            })

        for tx in _objects(payload.get("transactions")):
            if get(tx, "source") != "claim":
                continue
            settled = get(tx, "settlement") == "settled"
            amount = js_to_number(js_or(get(tx, "amount"), 0))
            rows.append({
                "key": c["caseUid"] + ":" + js_to_string(get(tx, "txNo")),
                "caseUid": c["caseUid"], "caseRowVersion": c["rowVersion"],
                "twRef": c["twRef"], "caseStatus": c["status"], "announcedAt": c["announcedAt"],
                "source": "claim", "txNo": _text(get(tx, "txNo")),
                "legType": _text(get(tx, "legType")), "reinsured": c["reinsured"],
                "reinsurer": _text(get(tx, "reinsurer")), "label": _text(get(tx, "label")),
                "amount": amount, "paid": amount if settled else 0, "outstanding": 0 if settled else amount,
                "currency": c["currency"], "reconciliationRef": reconciliation_ref_for(payload, tx),
                "settlement": "settled" if settled else "open",
                "paymentStatus": "settled" if settled else "upcoming",
                "settledAt": js_or(get(tx, "settledAt"), None), "settledBy": js_or(get(tx, "settledBy"), None),
                "reversed": get(tx, "reversed") is True, "isReversalEntry": get(tx, "isReversalEntry") is True,
            })
    # a.twRef.localeCompare(b.twRef) || String(a.dueDate || "").localeCompare(...)（穩定排序，同 JavaScript）
    rows.sort(key=lambda r: (js_locale_key(r["twRef"]), js_locale_key(_text(r.get("dueDate")))))
    return rows, warnings
