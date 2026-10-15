"""
記帳帳本的純函式 - 對應 Alpha api/accounting.js 的 ledgerRows（不碰資料庫，差異測試直接呼叫）。

paymentEntries／transactions 裡不是物件的項目一律略過（Alpha v56 起相同；v53 遇到 paymentEntries 裡的 null 會整個帳本拋錯）。
"""
from .calc.accounting import reconciliation_ref_for
from .manual_reference import manual_tw_ref_fields
from .calc.jsnum import get, is_array, js_locale_key_cached, js_or, js_to_number, js_to_string
from .calc.payment_terms import build_payment_schedule


def _text(value):
    """String(value || "")"""
    return js_to_string(js_or(value, ""))


def _objects(value):
    return [row for row in value if isinstance(row, dict)] if is_array(value) else []


def ledger_rows(cases, now=None, shared=None):
    """shared：{caseUid: CaseCompute}（Accounting 列表共用已算好的付款排程與交易明細；沒給就各自計算）。"""
    rows, warnings = [], []
    for c in cases:
        payload = c["payload"]
        memo = (shared or {}).get(c["caseUid"])
        schedule = memo.schedule("raw") if memo else build_payment_schedule(payload, now)
        if schedule["reviewRequired"]:
            warnings.append({"caseUid": c["caseUid"], "twRef": c["twRef"], "issues": schedule["issues"]})
        entries = _objects(payload.get("paymentEntries"))
        for item in schedule["items"]:
            cedant = item["partyType"] == "cedant"
            rows.append({
                "key": c["caseUid"] + ":" + item["scheduleKey"],
                "caseUid": c["caseUid"], "caseRowVersion": c["rowVersion"],
                **manual_tw_ref_fields(payload),
                "twRef": c["twRef"], "caseStatus": c["status"], "announcedAt": c["announcedAt"],
                "source": "premium", "scheduleKey": item["scheduleKey"],
                "installmentId": item["installmentId"], "installmentLabel": item["installmentLabel"],
                "partyType": item["partyType"], "partyName": item["partyName"],
                "legType": "Cedant" if cedant else "Reinsurer",
                "reinsured": c["reinsured"],
                "reinsurer": item["partyName"] if item["partyType"] == "reinsurer" else "",
                "label": (("Payable to " if cedant else "Receivable from ") if item.get("returnPremium")
                          else ("Receivable from " if cedant else "Payable to ")) + item["partyName"],
                "amount": item["amount"], "paid": item["paid"], "outstanding": item["outstanding"],
                "currency": item["currency"], "baseDate": item["baseDate"], "termsDays": item["termsDays"],
                "dueDate": item["dueDate"], "dueTime": item["dueTime"], "paymentStatus": item["status"],
                **({field: item[field] for field in ["paymentRule", "sourceBaseDate", "contractDueDate", "accountingLeadDays"]}
                   if item.get("paymentRule") == "auw_month_end_120" else {}),
                "partial": item["partial"], "settlement": item.get("settlement", "settled" if item["status"] == "settled" else "open"),
                **({field: item[field] for field in ("manualSettlementRequired", "manualSettlementConfirmed", "canConfirmSettlement") if field in item}),
                "reviewRequired": item["status"] == "pending_review",
                "entries": [e for e in entries if get(e, "scheduleKey") == item["scheduleKey"]],
                **({"returnPremium": True, "paymentDirection": item["paymentDirection"]} if item.get("returnPremium") else {}),
            })

        cash_claims = {}
        if any(e.get("transactionNo") for e in entries):
            from .cash_ledger import transaction_details
            cash_claims = memo.details("raw") if memo else transaction_details(payload, now)
        for tx in _objects(payload.get("transactions")):
            if get(tx, "source") != "claim":
                continue
            settled = get(tx, "settlement") == "settled"
            amount = js_to_number(js_or(get(tx, "amount"), 0))
            rows.append({
                "key": c["caseUid"] + ":" + js_to_string(get(tx, "txNo")),
                "caseUid": c["caseUid"], "caseRowVersion": c["rowVersion"],
                **manual_tw_ref_fields(payload),
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
                **{field: cash_claims.get(tx.get("txNo"), {})[field]
                   for field in ("paid","outstanding","settlement","paymentStatus","partyName","partyType","paymentDirection","entries")
                   if field in cash_claims.get(tx.get("txNo"), {})},
            })
    # a.twRef.localeCompare(b.twRef) || String(a.dueDate || "").localeCompare(...)（穩定排序，同 JavaScript）
    rows.sort(key=lambda r: (js_locale_key_cached(r["twRef"]), js_locale_key_cached(_text(r.get("dueDate")))))
    return rows, warnings
