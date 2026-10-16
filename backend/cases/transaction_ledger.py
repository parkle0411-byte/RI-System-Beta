"""Consolidate stored SoA transactions without generating or changing entries."""
from .calc.accounting import reconciliation_ref_for, number_or_zero
from .cash_ledger import transaction_details
from .ledger import _objects
from .manual_reference import manual_tw_ref_fields


def transaction_rows(cases, shared=None):
    """shared：{caseUid: CaseCompute}（見 ledger_rows）。"""
    rows = []
    for case in cases:
        payload = case["payload"]
        memo = (shared or {}).get(case["caseUid"])
        cash = memo.details("override") if memo else transaction_details({**payload, "currency":case["currency"], "reinsured":case["reinsured"]})
        for index, tx in enumerate(_objects(payload.get("transactions"))):
            rows.append({
                **tx,
                "key": f"{case['caseUid']}:{index}",
                "caseUid": case["caseUid"], "rootCaseUid": case.get("rootCaseUid", case["caseUid"]),
                "caseRowVersion": case["rowVersion"],
                "twRef": case["twRef"],
                **manual_tw_ref_fields(payload),
                "caseStatus": case["status"],
                "announcedAt": case["announcedAt"],
                "statementNo": payload.get("statementNo") or "",
                "originalInsured": payload.get("originalInsured") or payload.get("original_insured") or "",
                "originalInsuredCn": payload.get("originalInsuredCn") or "",
                "reinsured": case["reinsured"],
                "currency": case["currency"],
                "source": "claim" if tx.get("source") == "claim" else "premium",
                "reconciliationRef": reconciliation_ref_for(payload, tx),
                **cash.get(tx.get("txNo"), {"settlement":"not_tracked", "canRecord":False}),
                "canRecord": (case["status"] in ("posted", "closed") or (case["status"] == "reversed" and tx.get("source") == "claim")) and cash.get(tx.get("txNo"), {}).get("canRecord", False),
                **({"returnPremium": True} if payload.get("parentTwRef") and tx.get("source") != "claim"
                   and number_or_zero(payload.get("originalPremium")) < 0 else {}),
            })
    return rows
