"""記帳帳本（api/accounting.js 的 ledgerRows）差異測試的輸入向量。"""
from .vectors import MISSING, NOW_POINTS, R, case_data, coherent_case, maybe_omit

# TW Reference：排序用 localeCompare（符號 < 數字 < 字母、不分大小寫），刻意混入大小寫、符號、長短不同的編號
TW_REFS = ["TW-2026-0001", "TW-2026-0002", "tw-2026-0002", "TW-2026-0010", "TW-2026-0002-END1", "TW_2026_0003",
           "TW2026-0004", "TW-2025-0999", "TW-2026-1000", "", "TW-2026-0001 ", "TW-2026-000a", "TW-2026-000A", "Tw-2026-0005"]


def claim_transaction(i):
    t = {}
    maybe_omit(t, "source", R.choice(["claim"] * 6 + ["premium", None, MISSING, "Claim"]))
    maybe_omit(t, "txNo", R.choice([f"CL-{i}", f"CL-{i}-1", i, "", None, MISSING, 0]))
    maybe_omit(t, "legType", R.choice(["Claim Leg 1", "Claim Leg 2", "Leg 1", "", None, MISSING, 7]))
    maybe_omit(t, "reinsurer", R.choice(["Munich Re", "", None, MISSING, 5]))
    maybe_omit(t, "reinsurerIdx", R.choice([0, 1, 2, -1, None, MISSING, "1"]))
    maybe_omit(t, "label", R.choice(["Claim payment", "", None, MISSING]))
    maybe_omit(t, "amount", R.choice([1000, 250.5, -300, 0, "1,000", "12.5", None, MISSING, "abc", 1e15]))
    maybe_omit(t, "settlement", R.choice(["settled", "open", None, MISSING, "SETTLED"]))
    maybe_omit(t, "settledAt", R.choice(["2026-09-01T00:00:00.000Z", "", None, MISSING, 0]))
    maybe_omit(t, "settledBy", R.choice(["P.L", "", None, MISSING]))
    maybe_omit(t, "reversed", R.choice([True, False, "true", 1, None, MISSING]))
    maybe_omit(t, "isReversalEntry", R.choice([True, False, "true", MISSING]))
    return {k: v for k, v in t.items() if v is not MISSING}


def ledger_case(now, index):
    payload = coherent_case(now) if R.random() < 0.5 else case_data(schedule=True)
    if R.random() < 0.7:
        tx = [claim_transaction(i) for i in range(R.choice([0, 1, 2, 4]))]
        if R.random() < 0.15:
            tx.append(R.choice([None, "claim", 5, [], {"source": "claim"}]))  # transaction?.source：非物件一律略過
        payload["transactions"] = tx if R.random() > 0.05 else R.choice([None, "x", {}, 5])
    c = {
        "caseUid": f"00000000-0000-4000-8000-{index:012d}", "rowVersion": R.choice([1, 2, 3, 7]),
        "twRef": R.choice(TW_REFS), "status": R.choice(["posted", "closed"]),
        "announcedAt": R.choice(["2026-09-01T02:03:04.000Z", None, "2026-01-15T00:00:00.000Z"]),
        "reinsured": R.choice(["ZZ Cedant", "", "ZZ Cédant", 5]),
        "currency": R.choice(["USD", "TWD", "EUR", "", "usd"]),
        "payload": payload,
    }
    return c


def build(count_each=1200):
    vectors = []
    for _ in range(count_each):
        now = R.choice(NOW_POINTS)
        cases = [ledger_case(now, i) for i in range(R.choice([0, 1, 2, 3, 5, 8]))]
        vectors.append({"fn": "accountingLedgerRows", "args": [cases], "now": now})
    return vectors
