"""Production Report（lib/production-report.js）差異測試的輸入向量。"""
from .vectors import MISSING, R, case_data, maybe_omit, reinsurer

MONTHS = ["2026-03", "2026-04", "2026-09", "2026-10", "2026-12", "2027-01"]
ODD_MONTHS = ["2026-13", "2026-00", "26-03", "", None, 202603, "2026-3", "2026-03\n", "0050-02", "0099-12", "0100-01", "9999-12", "2024-02", "2100-02"]
TIMES = ["2026-03-31T23:30:00.000000+00:00", "2026-04-01T00:10:00+08:00", "2026-09-30T16:00:00+00:00", "2026-10-01T07:59:00+08:00",
         "2026-12-31T23:59:59Z", "", None, MISSING, "bad", "2027-01-05T01:00:00+08:00", 20260301]
NAMES = ["ZZ Insured", "zz insured", "ÄZ Insured", "Alpha Co", "alpha co", "", None, 5, "中文保戶", "Beta_Co", "beta-co"]


def party():
    p = {}
    maybe_omit(p, "name", R.choice(["A.L", "B.K", "", None, MISSING, "Sandy", "A.L "]))
    maybe_omit(p, "pct", R.choice([50, 50, 33.33, 33.34, 60, 40, 100, 0, "50", "abc", None, MISSING, 12.5]))
    return {k: v for k, v in p.items() if v is not MISSING}


def payload():
    d = case_data(schedule=True)
    d["reinsurers"] = R.choice([[reinsurer() for _ in range(R.choice([0, 1, 2, 3, 4]))]] * 9 + [None, "x"])
    for key, choices in (
        ("originalInsured", NAMES), ("reinsured", ["Cedant A", "", None, MISSING]),
        ("ae", ["A.L", "B.K", "", None, MISSING, 7]), ("classCode", ["PAR", "", None, MISSING]), ("classOfBusiness", ["Property", MISSING]),
        ("newOrRenew", ["New", "Renew", "renew", None, MISSING]), ("reinsuranceStructure", ["QS", "TREATY", "treaty", None, MISSING]),
        ("policyFrom", ["2026-03-01", "2026-04-15", "2026-09-10", "2026-10-01", "2026-12-31", "", None, MISSING, "2026-13-01", "2027-01-01"]),
        ("policyTo", ["2027-03-01", "", None, MISSING]),
        ("parentTwRef", ["TWPAR2603001", "", None, MISSING, MISSING, MISSING]),
        ("postedAt", TIMES), ("announcedAt", TIMES), ("createdAt", TIMES),
        ("installmentEnabled", [True, False, False, None, MISSING, "yes", 0]),
        ("currency", ["USD", "TWD", "usd", "EUR", "JPY", "", None, MISSING, "GBP"]),
        ("splitEnabled", [True, True, False, None, MISSING]),
    ):
        maybe_omit(d, key, R.choice(choices))
    d = {k: v for k, v in d.items() if v is not MISSING}
    if d.get("splitEnabled"):
        d["splitParties"] = R.choice([[party() for _ in range(R.choice([1, 2, 3]))]] * 5 + [[], None, "x"])
    if d.get("installmentEnabled"):
        rows = []
        for i in range(R.choice([0, 1, 2, 3])):
            row = {}
            maybe_omit(row, "id", R.choice([f"I{i + 1}", "", None, MISSING, i, "inst"]))
            maybe_omit(row, "performanceMonth", R.choice(MONTHS + ["", None, MISSING, "2026-13", "2026-03-15"]))
            maybe_omit(row, "premium", R.choice([400000, 250000.5, 0, "1,000", None, MISSING, 333333.33]))
            maybe_omit(row, "ratio", R.choice([50, 25, 33.33, None, MISSING, "50"]))
            rows.append({k: v for k, v in row.items() if v is not MISSING})
        d["performanceInstallments"] = rows if R.random() > 0.05 else R.choice([None, "x"])
    if R.random() < 0.3:
        d["originalPremium"] = R.choice([0, 1_000_000, 987654.32])
    return d


def coherent_payload(month):
    """情境一致的案件：生效月、分期月份與報表月配好，金額都是數字，讓大多數向量真的產生報表列。"""
    y, m = (int(x) for x in month.split("-")) if isinstance(month, str) and len(month) == 7 and month[4] == "-" and month[:4].isdigit() and month[5:].isdigit() else (2026, 9)
    n = R.choice([1, 2, 3])
    shares = R.choice([[100], [60, 40], [50, 30, 20], [33.33, 33.33, 33.34], [70, 30]])[:n] if n > 1 else [100]
    d = {"originalInsured": R.choice(NAMES[:4] + ["Gamma Ltd", "gamma ltd"]), "reinsured": "Cedant A", "ae": R.choice(["A.L", "B.K", "Sandy"]),
         "classCode": R.choice(["PAR", "ENG", ""]), "classOfBusiness": "Property", "newOrRenew": R.choice(["New", "Renew"]),
         "reinsuranceStructure": R.choice(["QS", "TREATY", "XOL"]), "currency": R.choice(["USD", "TWD", "EUR", "JPY", "usd", "GBP"]),
         "originalPremium": R.choice([1_000_000, 2_500_000.5, 987654.32, 4321, 0]), "riCommPct": R.choice([10, 12.5, 7.35, 0]),
         "taxPct": R.choice([0, 3, 0.75]), "policyFrom": f"{y:04d}-{m:02d}-{R.randint(1, 28):02d}" if R.random() < 0.8 else "2025-01-15",
         "policyTo": f"{y + 1:04d}-{m:02d}-01",
         "reinsurers": [{"name": f"Re {chr(65 + i)}" + R.choice(["", " (Facility)", " [facility]", " (FACILITY) "]), "sharePct": sh,
                         "premium": R.choice([900_000, 2_000_000, 750_500.25, 3999.99]), "riCommPct": R.choice([5, 10, 0, 12.5]),
                         "taxPct": R.choice([0, 2]), "foreignBroker": R.choice(["", "", "Aon Re", "  "])} for i, sh in enumerate(shares)]}
    if R.random() < 0.3:
        d["parentTwRef"] = "TWPAR2603001"
    if R.random() < 0.35:
        d["splitEnabled"] = True
        d["splitParties"] = R.choice([[{"name": "A.L", "pct": 50}, {"name": "B.K", "pct": 50}], [{"name": "A.L", "pct": 33.33}, {"name": "B.K", "pct": 33.33}, {"name": "C.C", "pct": 33.34}],
                                      [{"name": "B.K", "pct": 60}, {"name": "A.L", "pct": 40}], [{"name": "", "pct": 70}, {"pct": 30}]])
    if R.random() < 0.4:
        d["installmentEnabled"] = True
        months = [month, f"{y:04d}-{min(m + 1, 12):02d}", "2025-12"]
        d["performanceInstallments"] = [{"id": f"I{i + 1}", "performanceMonth": R.choice(months), "premium": R.choice([400_000, 250_000.5, 333_333.33, 0]),
                                         "ratio": R.choice([50, 25, 33.33])} for i in range(R.choice([1, 2, 3]))]
    return d


def source(i, month=None):
    if month is not None and R.random() < 0.75:
        s = {"id": i + 1, "case_uid": f"00000000-0000-4000-8000-{i:012d}", "row_version": R.choice([1, 2, 5]),
             "status": R.choice(["posted", "closed", "reversed", "posted"]),
             "announced_at": R.choice(TIMES[:5]), "created_at": R.choice(TIMES[:5]), "payload": coherent_payload(month)}
        s["tw_ref"] = R.choice(["TWPAR2603001-E01", "TWPAR2603001-e2", "TWPAR2603001-E1x"]) if s["payload"].get("parentTwRef") else R.choice(["TWPAR2603001", "TWPAR2603002", "TWENG2604001"])
        return {k: v for k, v in s.items() if v is not MISSING}
    s = {"id": i + 1, "case_uid": f"00000000-0000-4000-8000-{i:012d}", "row_version": R.choice([1, 2, 5, "3", None])}
    maybe_omit(s, "status", R.choice(["posted", "closed", "reversed", "draft", "posted", None, MISSING]))
    maybe_omit(s, "tw_ref", R.choice(["TWPAR2603001", "TWPAR2603001-E01", "TWPAR2603001-e2", "TWPAR2603002", "", None, MISSING, "TWX-E1\n"]))
    maybe_omit(s, "announced_at", R.choice(TIMES))
    maybe_omit(s, "created_at", R.choice(TIMES))
    p = payload()
    s["payload"] = p if R.random() > 0.03 else R.choice([None, {}, "x"])
    s = {k: v for k, v in s.items() if v is not MISSING}
    return s


def keys_for(src):
    """這個案件實際會產生的 key（用 Python 版算，只當作輸入）＋一些不存在的 key。"""
    from production.calc import production_keys_for_case
    real = production_keys_for_case(src)
    cid = src["id"]
    rks = real + [f"{cid}:FULL:R9", f"{cid}:I9:R0"]
    ks = sorted({k.rsplit(":", 1)[0] for k in real}) + [f"{cid}:FULL", f"{cid}:I9"]
    return ks, rks


def exclusion(src, month):
    ks, rks = keys_for(src)
    scope = R.choice(["case", "reinsurer", "reinsurer", "other"])
    e = {"id": f"e{R.randint(1, 999)}", "case_id": R.choice([src["id"], src["id"], str(src["id"]), src["id"] + 100]),
         "year_month": R.choice([month, month, "2026-01"]), "scope": scope, "installment_key": R.choice(ks),
         "reinsurer_key": R.choice(rks + [None]) if scope != "case" else None,
         "deferred_to": R.choice([month, "2026-10", "2027-01"]), "reason": "r", "created_at": "2026-09-01T00:00:00+00:00"}
    if R.random() < 0.15:  # 另一種鍵名（camelCase）
        e = {"caseId": e["case_id"], "yearMonth": e["year_month"], "scope": scope, "installmentKey": e["installment_key"],
             "reinsurerKey": e["reinsurer_key"], "deferredTo": e["deferred_to"], "id": e["id"]}
    return e


def build(count_each=1200):
    vectors = []
    for _ in range(count_each):
        month = R.choice(MONTHS * 4 + ODD_MONTHS)
        sources = [source(i, month) for i in range(R.choice([0, 1, 2, 3, 5, 8]))]
        for s in sources:
            if isinstance(s.get("payload"), dict) and R.random() < 0.3:
                pool = keys_for(s)[1]; s["payload"]["confirmedProductionKeys"] = R.sample(pool, min(len(pool), R.choice([1, 2, 4])))
        fx = R.choice([{}, {str(month): {"USD": 31.5, "EUR": 34.123456, "JPY": 0.2}}, {str(month): {"USD": 0}}, {"USD": 30.1}, {str(month): {"USD": "31.5"}}, {str(month): {}},
                       {str(month): {"USD": 31.5, "EUR": 34.5}, "USD": 30.1, "EUR": 33}, {str(month): {"USD": 0}, "USD": 30.1}])
        excl = [exclusion(s, str(month)) for s in sources for _ in range(R.choice([0, 1, 1, 2]))] if sources else []
        vectors.append({"fn": "buildProductionPreview", "args": [sources, month, fx, excl]})
    for _ in range(count_each // 2):
        vectors.append({"fn": "productionKeysForCase", "args": [source(R.randint(0, 20), R.choice(MONTHS))]})
    for _ in range(count_each // 4):
        vectors.append({"fn": "nextProductionMonth", "args": [R.choice(MONTHS + ODD_MONTHS)]})
    vectors.extend(build_close(count_each))
    return vectors


def old_transaction(i):
    t = {"txNo": R.choice([f"TWPAR2603001-R1-TX{i}", f"TX{i}", "", 7, None]), "amount": R.choice([1000, -250.5, 0, "12.5", None, "abc"]),
         "legType": R.choice(["Leg 1", "Leg 2", "Leg 3"]), "settlement": R.choice(["open", "settled"])}
    for key, choices in (("reversed", [True, True, False, "true", None, MISSING]), ("isReversalEntry", [True, False, MISSING, MISSING]),
                         ("reversalOffsetApplied", [True, False, MISSING, MISSING, MISSING]), ("source", ["claim", MISSING, MISSING])):
        maybe_omit(t, key, R.choice(choices))
    return {k: v for k, v in t.items() if v is not MISSING}


def build_close(count):
    vectors = []
    for n in range(count):
        month = R.choice(MONTHS)
        src = source(n, month)
        if not isinstance(src.get("payload"), dict):
            src["payload"] = coherent_payload(month)
        src["status"] = R.choice(["posted", "posted", "reversed", "closed"])
        p = src["payload"]
        if R.random() < 0.6:
            p["transactions"] = [old_transaction(i) for i in range(R.choice([0, 1, 3, 6]))]
        for key, choices in (("pendingReversalOffset", [True, True, False, None, MISSING, 1]), ("reversalCycle", [0, 1, 2, "2", None, MISSING, 3]),
                             ("confirmedProductionKeys", [MISSING, [], ["x"], [5, "5"], None])):
            v = R.choice(choices)
            if v is not MISSING:
                p[key] = v
        keys = keys_for(src)[1][:-2]  # 實際的 key
        pick = R.choice(["all", "all", "some", "none", "extra"])
        chosen = keys if pick == "all" else (R.sample(keys, max(len(keys) - 1, 0)) if pick == "some" else ([] if pick == "none" else keys + ["999:X:R0"]))
        rows = [{"reinsurerKey": k} for k in chosen] + ([{"reinsurerKey": R.choice([5, None])}] if R.random() < 0.1 else [])
        vectors.append({"fn": "productionConfirmCase", "args": [src, rows]})
    return vectors
