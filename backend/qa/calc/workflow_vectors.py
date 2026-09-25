"""案件流程（Announce / Endorsement / Renewal / Reverse / 通知會計）純函式的差異測試輸入向量。"""
from .vectors import BROKERS, DATES_ODD, DATES_VALID, MISSING, NAMES, R, TRICKY_STRINGS, maybe_omit

CLASS_CODES = ["PAR", " par ", "p-a.r", "abcdefghijklmnop", "  ", "", None, MISSING, 12, "中文", "ß", "ǆ", "ﬁ", "A B\tC", "ｐａｒ", "x" * 30, "PAR\n", "İ", "ı"]
WS_VARIANTS = [" ", "  ", "\t", " ", " ", "　", "﻿", "​", "᠎", "\n"]


def dates(n=1):
    """各種日期字串：格式合法的（含閏日、月／日溢位）與不合法的。"""
    r = R.random()
    if r < 0.30:
        return R.choice(DATES_VALID + DATES_ODD)
    if r < 0.85:
        year = R.choice([R.randint(0, 9999), R.randint(1990, 2100), R.choice([0, 1, 98, 99, 100, 101, 1999, 2000, 2024, 2027, 2028, 2100, 9998, 9999])])
        month = R.choice([R.randint(1, 12), R.randint(1, 12), 0, 13, 99, 2])
        day = R.choice([R.randint(1, 28), R.randint(29, 31), 0, 32, 99, 29, 30])
        return f"{year:04d}-{month:02d}-{day:02d}"
    return R.choice(["2026-01-01\n", " 2026-01-01", "2026-01-01x", "١٢٣٤-٠١-٠١", None, 20260101, True, [], {}, "0000-00-00"])


def name_value():
    r = R.random()
    if r < 0.65:
        base = R.choice(NAMES + BROKERS)
        if isinstance(base, str) and R.random() < 0.4:
            base = base.replace(" ", R.choice(WS_VARIANTS))
        return base
    return R.choice([None, 0, 5, True, [], {}, "a" * 30 + " (Facility)", "Facility", "(facility)", "X (FACILITY) ", "X (Facility) ", "Y (Facility)"])


def reinsurer_rows():
    r = R.random()
    if r < 0.08:
        return R.choice([None, "x", {}, 5])
    rows = []
    for _ in range(R.randint(0, 5)):
        rows.append(R.choice([{"name": name_value()}, {"name": name_value(), "sharePct": 50, "premium": 1000}, {}, None, "row", {"nome": "x"}]))
    return rows


def payload_for_prefix():
    d = {}
    maybe_omit(d, "classCode", R.choice(CLASS_CODES))
    maybe_omit(d, "policyFrom", R.choice([dates(), dates(), MISSING]))
    return {k: v for k, v in d.items() if v is not MISSING}


def file_rows(names):
    files = []
    for i in range(R.randint(0, 6)):
        reinsurers = R.choice([[R.choice(names) for _ in range(R.randint(0, 3))], [], None, "x", {}, [None, 5, "z"]])
        files.append({"id": f"id-{R.randint(1, 4)}-{i}", "kind": R.choice(["offer", "signed", "confirmation", "other", "Offer"]),
                      "reinsurers": reinsurers, "is_selected": R.random() < 0.8})
    return files


def coverage_args():
    rows = reinsurer_rows()
    payload = R.choice([{"reinsurers": rows}, {}, None, {"reinsurers": rows}])
    names = ["Munich Re", "swiss  re", "Swiss Re (Facility)", " AIG ", "aig", "Lloyd's", "中再"] + [n for n in NAMES if isinstance(n, str)]
    if isinstance(payload, dict) and isinstance(payload.get("reinsurers"), list):
        for row in payload["reinsurers"]:
            if isinstance(row, dict) and isinstance(row.get("name"), str) and R.random() < 0.7:
                names.append(row["name"])
    return [payload, file_rows(names)]


def ids_args():
    def ids():
        return R.choice([["b", "a", "c"], ["a", "b", "c"], ["a", "b"], ["a", "a"], [], [1, 2, 10], ["1", "2", "10"], ["10", "9"], [None, True], None, "abc", {}, 5, MISSING, ["é", "e"], ["a b", "a  b"]])
    a = ids()
    b = R.choice([a, a, ids()]) if a is not MISSING else ids()
    return [x for x in (a, b) if x is not MISSING] + ([None] * (2 - len([x for x in (a, b) if x is not MISSING])))


def transactions():
    return R.choice([[], [{"legType": "Leg 1"}, {"legType": "Leg 1", "isReversalEntry": True}],
                     [{"isReversalEntry": True, "amount": 5}, {"isReversalEntry": False}, {"isReversalEntry": "true"}, {"reversed": False}],
                     [None, 5, "x", [], {}], None, "not-a-list", {"a": 1}, [{"legType": "Leg 2", "reversed": True, "amount": 1.5}]])


def source_payload():
    d = {}
    maybe_omit(d, "reinsurers", R.choice([reinsurer_rows(), [{"name": "A", "premium": 5, "sharePct": 60, "settlementRef": "S1"}, {"name": "B"}]]))
    maybe_omit(d, "transactions", R.choice([transactions(), MISSING]))
    maybe_omit(d, "claims", R.choice([[{"id": 1}], [], MISSING, None]))
    maybe_omit(d, "paymentEntries", R.choice([[{"k": 1}], MISSING]))
    maybe_omit(d, "accountingNotifications", R.choice([[{"id": "n"}], [], None, "x", MISSING, {}]))
    maybe_omit(d, "reversalCycle", R.choice([0, 1, 2, 99, None, "3", "x", -1, 1.5, MISSING, True, "", [], "0x10", 1e21]))
    maybe_omit(d, "policyFrom", R.choice([dates(), MISSING]))
    maybe_omit(d, "policyTo", R.choice([dates(), MISSING]))
    maybe_omit(d, "status", R.choice(["posted", "closed", MISSING]))
    maybe_omit(d, "originalPremium", R.choice([1000, None, MISSING, "5"]))
    maybe_omit(d, "exchRate", R.choice([30.5, None, MISSING]))
    maybe_omit(d, "statementNo", R.choice(["S-1", "", MISSING]))
    maybe_omit(d, "endoTypes", R.choice([["A"], [], MISSING]))
    maybe_omit(d, "confirmedProductionKeys", R.choice([["k"], [], MISSING]))
    maybe_omit(d, "productionPartiallyConfirmed", R.choice([True, False, MISSING]))
    maybe_omit(d, "pendingReversalOffset", R.choice([True, None, MISSING]))
    maybe_omit(d, "unrelated", R.choice([{"deep": [1, {"x": None}]}, "keep", MISSING]))
    return {k: v for k, v in d.items() if v is not MISSING}


def build(count_each):
    n = max(count_each // 2, 1)
    out = []
    add = out.append
    for _ in range(n):
        add({"fn": "reinsurerKey", "args": [name_value()]})
    for _ in range(n):
        add({"fn": "requiredReinsurers", "args": [R.choice([{"reinsurers": reinsurer_rows()}, {}, None])]})
    for _ in range(n * 2):
        add({"fn": "coverageFor", "args": coverage_args()})
    for _ in range(n):
        add({"fn": "sameIds", "args": ids_args()})
    for _ in range(n):
        add({"fn": "referencePrefix", "args": [payload_for_prefix()]})
    for _ in range(n * 3):
        add({"fn": "shiftYear", "args": [dates()]})
    for _ in range(n):
        add({"fn": "resetSharedPayload", "args": [source_payload()]})
    for _ in range(n):
        add({"fn": "buildEndorsementPayload", "args": [source_payload(), R.choice(["TWPAR2603001", "", None, "X-1"]), R.choice([0, 1, 2, 7, 99])]})
    for _ in range(n):
        add({"fn": "buildRenewalPayload", "args": [source_payload(), R.choice(["TWPAR2603001", "", None, "X-1"])]})
    for _ in range(n * 2):
        add({"fn": "buildReversedPayload", "args": [source_payload()]})
    for _ in range(n):
        add({"fn": "appendNotification", "args": [source_payload(), {"id": "u", "accountingPersonnelId": 3, "note": "n", "notifiedAt": "2026-09-25T00:00:00.000Z"}]})
    return out
