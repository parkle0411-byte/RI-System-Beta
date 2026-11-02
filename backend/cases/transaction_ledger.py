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
        # 2026-11-02 效能：每件案件共用的欄位只算一次（每列的內容與欄位順序不變）
        root_uid = case.get("rootCaseUid", case["caseUid"])
        manual = manual_tw_ref_fields(payload)
        statement_no = payload.get("statementNo") or ""
        original_insured = payload.get("originalInsured") or payload.get("original_insured") or ""
        original_insured_cn = payload.get("originalInsuredCn") or ""
        for index, tx in enumerate(_objects(payload.get("transactions"))):
            rows.append({
                **tx,
                "key": f"{case['caseUid']}:{index}",
                "caseUid": case["caseUid"], "rootCaseUid": root_uid,
                "caseRowVersion": case["rowVersion"],
                "twRef": case["twRef"],
                **manual,
                "caseStatus": case["status"],
                "announcedAt": case["announcedAt"],
                "statementNo": statement_no,
                "originalInsured": original_insured,
                "originalInsuredCn": original_insured_cn,
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
