"""
差異測試的輸入向量（固定亂數種子，所以每次都一樣、失敗時可重現）。

輸出 JSON：[{"fn": 函數名, "args": [...], "now": ISO 時間(選填)}, ...]
只用 JSON 能表示的值（JavaScript 收到的與 Python 收到的必須是同一份）。
"undefined" 用「省略該欄位」表示，null 用 None。
"""
import json
import random
import sys

SEED = 20260925
R = random.Random(SEED)

PCT_COMMON = [0, 100, 50, 33.33, 33.34, 12.5, 7.35, 0.75, 17.77, 10, 5, 2.5, 0.1, 1, 25, 66.67, 20.5, 3, 15]
TRICKY_STRINGS = ["", " ", "abc", "12abc", "1,234,567.89", " 12.5 ", "0x1f", "0b11", "0o7", "1e3", "1E-2", "Infinity", "-Infinity",
                  "infinity", "nan", "1_000", "+5", ".5", "5.", "--5", "١٢٣", "１２３", " 12 ", "﻿7", "᠎5", "1,0,0,0", "-", "+", "1e", "0x", "12 34"]
NAMES = ["Munich Re", "Swiss Re (Facility)", "Hannover Rück [facility]", " AIG  (FACILITY) ", "中再 (Facility)", "Lloyd's (Facility) ",
         "X﻿(Facility)", "Y(Facility)Z", "Sirius International", "Everest Re  ", "  Tokio Marine  [Facility]  ", "(Facility)", "[Facility]", "General Re (facility) (Facility)",
         "SCOR SE", "Allianz\t(Facility)", "Trans\nRe(Facility)\n", "Fac ility", "ſ (Facility)"]
BROKERS = ["", None, "  ", "Aon Re", " Guy Carpenter ", "Howden (Facility)", " ", "TW Insurance Brokers"]
DATES_VALID = ["2026-01-01", "2026-03-15", "2026-06-30", "2026-09-24", "2026-09-25", "2026-12-31", "2027-02-28", "2028-02-29", "2026-02-28"]
DATES_ODD = ["2026-02-30", "2026-02-29", "2026-04-31", "2026-13-01", "2026-00-10", "2026-01-32", "2026-01-00", "2026-1-5", "0000-01-01",
             "9999-12-31", "9999-12-30", " 2026-01-01", "2026-01-01 ", "2026-01-01\n", "", None, 20260101, "2026/01/01", "abcd-ef-gh", "２０２６-０１-０１"]
NOW_POINTS = ["2026-09-24T15:59:59Z", "2026-09-24T16:00:00Z", "2026-09-24T16:00:01Z", "2026-09-25T03:59:59Z", "2026-09-25T04:00:00Z",
              "2026-09-25T04:00:01Z", "2026-12-31T15:59:59Z", "2026-12-31T16:00:00Z", "2026-06-30T20:30:00Z", "2027-02-27T16:00:00Z", "2026-03-15T05:00:00Z", "2026-01-01T00:00:00Z"]

MISSING = object()


def maybe_omit(d, key, value):
    if value is not MISSING:
        d[key] = value


def num_value(pct=False):
    """一個數值欄位可能出現的各種輸入（含各種不合規的）。"""
    r = R.random()
    if r < 0.42:
        return R.choice(PCT_COMMON) if pct else round(R.uniform(1000, 5_000_000), R.choice([0, 1, 2, 2, 2, 3, 4]))
    if r < 0.58:
        return round(R.uniform(0, 100 if pct else 1e9), R.choice([0, 1, 2, 3, 4, 6]))
    if r < 0.64:
        return R.choice([0, 0.0, -1, -0.5, -33.33, 1e-7, 1e21, 1e15, 123456789012345678, 0.005, 0.015, 1.005, 2.675, 0.285, 1.255])
    if r < 0.72:
        return None
    if r < 0.78:
        return MISSING
    if r < 0.90:
        return R.choice(TRICKY_STRINGS)
    if r < 0.93:
        return str(round(R.uniform(0, 100 if pct else 1e7), 2))
    if r < 0.95:
        return R.choice([True, False])
    if r < 0.98:
        return R.choice([[], [1], [1, 2], ["1", "2"], [None, 5]])
    return R.choice([{}, {"a": 1}])


def reinsurer():
    r = R.random()
    if r < 0.03:
        return None
    if r < 0.06:
        return R.choice(["Munich Re", 5, True, [], ["x"]])
    d = {}
    maybe_omit(d, "name", R.choice(NAMES + [None, "", MISSING, 42]))
    for key, pct in (("sharePct", True), ("premium", False), ("riCommPct", True), ("taxPct", True)):
        maybe_omit(d, key, num_value(pct))
    maybe_omit(d, "foreignBroker", R.choice(BROKERS + [MISSING, 7]))
    maybe_omit(d, "settlementRef", R.choice(["", "SR-001", None, MISSING, 12, "  x "]))
    maybe_omit(d, "paymentTermsDays", R.choice([None, MISSING, 15, 30, 45, 60, 90, 14, 15.5, "30", "abc", 0, -5, 120, "", " 30 ", 1e9]))
    return d


def split_parties():
    n = R.choice([0, 1, 2, 2, 2, 2, 3])
    rows = []
    for _ in range(n):
        if R.random() < 0.05:
            rows.append(R.choice([None, "x", 5]))
            continue
        d = {}
        maybe_omit(d, "name", R.choice(["P.L", "S.C", "Sandy Kao", "", None, MISSING, "  ", 7, "中文"]))
        maybe_omit(d, "pct", R.choice([50, 30, 70, 33.33, 66.67, 100, 0, None, MISSING, "40", "abc", 12.5, 87.5, -10, "1,0"]))
        maybe_omit(d, "personnelId", R.choice([1, 2, 30, None, MISSING]))
        rows.append(d)
    return rows


def case_data(schedule=False):
    d = {}
    maybe_omit(d, "twRef", R.choice(["TW-2026-0001", "TW-2026-0002-END1", "", None, MISSING, 12345, "TW 2026/9"]))
    for key, pct in (("originalPremium", False), ("riCommPct", True), ("taxPct", True)):
        maybe_omit(d, key, num_value(pct))
    d["reinsurers"] = R.choice([[reinsurer() for _ in range(R.choice([0, 1, 2, 3, 3, 4, 5, 6]))]] * 9 + [MISSING, None, "x", {}, {"0": {"name": "Zed"}}])
    if d["reinsurers"] is MISSING:
        del d["reinsurers"]
    maybe_omit(d, "splitEnabled", R.choice([True, True, False, False, MISSING, None, "true", 1]))
    maybe_omit(d, "splitParties", R.choice([split_parties(), split_parties(), split_parties(), MISSING, None, "ab", {}]))
    maybe_omit(d, "statementNo", R.choice(["ST-001", "", None, MISSING, 88]))
    maybe_omit(d, "reinsuredName", R.choice(["Fubon Insurance", "", None, MISSING, "  "]))
    maybe_omit(d, "cedantName", R.choice(["Cathay Life", "", None, MISSING]))
    maybe_omit(d, "currency", R.choice(["USD", "TWD", "", None, MISSING, "EUR", 5]))
    maybe_omit(d, "policyFrom", R.choice(DATES_VALID * 3 + DATES_ODD + [MISSING]))
    maybe_omit(d, "paymentTermsDays", R.choice([15, 30, 45, 60, 90, 120, 14, 0, None, MISSING, "30", "abc", 15.5, "", 1e9, -1]))
    if schedule:
        d["installmentEnabled"] = R.choice([True, True, True, False, None, "yes", MISSING])
        if d["installmentEnabled"] is MISSING:
            del d["installmentEnabled"]
        rows = []
        for i in range(R.choice([0, 1, 2, 3, 4, 6])):
            if R.random() < 0.04:
                rows.append(R.choice([None, "x", 5, []]))
                continue
            row = {}
            maybe_omit(row, "id", R.choice([f"I{i + 1}", f"inst-{i}", "", None, MISSING, i, 0, "  "]))
            maybe_omit(row, "performanceMonth", R.choice(["2026-01", "2026-02", "2026-12", "", None, MISSING, "bad", 202601]))
            maybe_omit(row, "paymentBaseDate", R.choice(DATES_VALID * 3 + DATES_ODD + [MISSING]))
            maybe_omit(row, "paymentTermsDays", R.choice([15, 30, 60, None, MISSING, "45", 14, "x", 30.5]))
            maybe_omit(row, "premium", R.choice([num_value(False)] * 3 + [None, MISSING, 0, "", 100000, 250000.5]))
            maybe_omit(row, "ratio", R.choice([25, 50, 33.33, 100, None, MISSING, "", 0, "25"]))
            terms = {}
            for n in range(1, 5):
                if R.random() < 0.4:
                    terms[f"r{n}"] = R.choice([15, 30, 60, 14, None, "45", "x", 20.5])
            maybe_omit(row, "reinsurerPaymentTerms", R.choice([terms, terms, {}, None, MISSING, [], "x", [30]]))
            rows.append(row)
        d["performanceInstallments"] = rows if R.random() > 0.05 else R.choice([None, "x", {}, 5])
        entries = []
        for _ in range(R.choice([0, 0, 1, 2, 3, 5, 8])):
            ids = ["case-effective-date"] + [f"I{i + 1}" for i in range(4)] + ["installment-1", "installment-2", "inst-0", "5", ""]
            kind = R.choice([":cedant"] + [f":reinsurer:r{n}" for n in range(1, 5)] + [":other", ""])
            key = R.choice(ids) + kind if R.random() > 0.08 else R.choice(["", None, 5, "zzz"])
            e = {}
            maybe_omit(e, "scheduleKey", key)
            maybe_omit(e, "amount", R.choice([num_value(False)] * 4 + [1000, 500.25, "1,000", -300, 0, None, "abc", 1e15]))
            maybe_omit(e, "entryType", R.choice(["payment", "payment", "reversal", "adjustment", None, MISSING, "REVERSAL"]))
            entries.append(e)
        d["paymentEntries"] = entries if R.random() > 0.05 else R.choice([None, "x", {}, 5])
    return {k: v for k, v in d.items() if v is not MISSING}


def coherent_case(now_iso):
    """
    情境一致的案件：付款基準日、付款天數與「現在（台北時間）」是配好的，
    讓排程真的走到「今日到期、未到期、逾期、部分付款、已結清、待審」各種狀態。
    """
    from datetime import datetime, timedelta

    today = (datetime.fromisoformat(now_iso.replace("Z", "+00:00")) + timedelta(hours=8)).date()

    def day(offset):
        return (today + timedelta(days=offset)).isoformat()

    terms = R.choice([15, 30, 45, 60, 90])
    d = {"twRef": "TW-2026-0100", "originalPremium": R.choice([1_000_000, 2_500_000.5, 987654.32, 4_321_000]),
         "riCommPct": R.choice([10, 12.5, 7.35, 0]), "taxPct": R.choice([0, 3, 0.75]), "currency": "USD", "paymentTermsDays": terms}
    n = R.choice([1, 2, 3])
    shares = R.choice([[100], [60, 40], [50, 30, 20], [33.33, 33.33, 33.34]])[:n] if n > 1 else [100]
    d["reinsurers"] = [{"name": f"Reinsurer {i + 1}" + R.choice(["", " (Facility)"]), "sharePct": sh,
                        "premium": R.choice([900_000, 2_000_000, 750_500.25]), "riCommPct": R.choice([5, 10, 0]),
                        "taxPct": R.choice([0, 2]), "foreignBroker": R.choice(["", "Aon Re"]),
                        "paymentTermsDays": R.choice([None, 30, 45, 60])} for i, sh in enumerate(shares)]
    d["installmentEnabled"] = R.random() < 0.6
    keys = []
    if d["installmentEnabled"]:
        rows = []
        for i in range(R.choice([1, 2, 3])):
            # 讓 Cedant 的到期日剛好是今天 / 昨天 / 一週後 / 隨機
            offset_target = R.choice([0, 0, 1, -1, 7, -7, -14, 3, -30, 20])
            base = day(offset_target - (terms - 15))
            rows.append({"id": f"I{i + 1}", "performanceMonth": f"2026-0{i + 1}", "paymentBaseDate": R.choice([base, base, base, "", None, "2026-02-30"]),
                         "paymentTermsDays": R.choice([None, terms]), "premium": R.choice([400_000, 250_000.5, None]),
                         "ratio": R.choice([50, 25, None]), "reinsurerPaymentTerms": R.choice([{}, {"r1": terms}, {"r2": 45}])})
            keys.append(f"I{i + 1}")
        d["performanceInstallments"] = rows
    else:
        d["policyFrom"] = day(R.choice([0, 0, 1, -1, 7, -7, -14, 3, -30, 20]) - (terms - 15))
        keys.append("case-effective-date")
    entries = []
    for key in keys:
        for party in [":cedant"] + [f":reinsurer:r{i + 1}" for i in range(n)]:
            r = R.random()
            if r < 0.30:
                entries.append({"scheduleKey": key + party, "amount": R.choice([10, 100.5, 1234.56, "5,000"]), "entryType": "payment"})
            elif r < 0.50:
                entries.append({"scheduleKey": key + party, "amount": R.choice([1e12, 999999999]), "entryType": "payment"})
            elif r < 0.58:
                entries.append({"scheduleKey": key + party, "amount": 50, "entryType": "reversal"})
    d["paymentEntries"] = entries
    return d


def transaction():
    d = {}
    maybe_omit(d, "legType", R.choice(["Leg 1", "Leg 2", "Leg 3", "Leg 1a", "Leg 1b", "Leg 2a", "Leg 2b", "Leg 3a", "Claim Leg 1", "Claim Leg 2", "", None, MISSING, 5, "leg 1", "Claim"]))
    maybe_omit(d, "reinsurerIdx", R.choice([0, 1, 2, 3, 5, -1, None, MISSING, 1.5, "1", 2.0, 99]))
    maybe_omit(d, "source", R.choice(["claim", "claim", None, MISSING, "premium", "Claim"]))
    maybe_omit(d, "settlement", R.choice(["settled", "open", None, MISSING, "SETTLED"]))
    return {k: v for k, v in d.items() if v is not MISSING}


def claim_and_payment():
    claim, payment = {}, {}
    maybe_omit(claim, "id", R.choice([1, 2, 77, "C-9", None, MISSING, 0, 1.5]))
    maybe_omit(claim, "lossNo", R.choice(["LOSS-2026-01", "", None, MISSING, 12, "  "]))
    maybe_omit(payment, "id", R.choice([1, 2, 9, "P-1", None, MISSING, 0]))
    maybe_omit(payment, "amount", num_value(False))
    return {k: v for k, v in claim.items() if v is not MISSING}, {k: v for k, v in payment.items() if v is not MISSING}


def build(count_each=1200):
    vectors = []
    add = vectors.append
    for _ in range(count_each):
        add({"fn": "stripFacilityTag", "args": [R.choice(NAMES + BROKERS + [None, 0, 5, True, [], ["a (Facility)"], {}, "a" * 40 + "(Facility)"])]})
    for _ in range(count_each * 2):
        add({"fn": "calcLegsForReinsurer", "args": [case_data(), reinsurer()]})
    for _ in range(count_each * 2):
        add({"fn": "buildPremiumTransactions", "args": [R.choice([case_data()] * 12 + [None, {}, "x", []])]})
    for _ in range(count_each):
        root = case_data()
        split = R.choice([root, case_data(), root, None, {}])
        claim, payment = claim_and_payment()
        add({"fn": "buildClaimPaymentTransactions", "args": [root, split, claim, payment]})
    for _ in range(count_each):
        add({"fn": "reconciliationRefFor", "args": [case_data(), transaction()]})
    for _ in range(count_each):
        add({"fn": "addCalendarDays", "args": [R.choice(DATES_VALID + DATES_ODD), R.choice([0, 1, 5, 15, 30, 45, 60, 90, -5, -15, 100, 365, 1.5, -1.5, 0.5, "10", None, "abc", "", 1e9, 1e10, -1e9])]})
    for _ in range(count_each // 2):
        add({"fn": "taipeiDate", "args": [], "now": R.choice(NOW_POINTS)})
    for _ in range(count_each):
        add({"fn": "daysBetweenDates", "args": [R.choice(DATES_VALID + DATES_ODD), R.choice(DATES_VALID + DATES_ODD)]})
    for _ in range(count_each):
        add({"fn": "paymentInstallments", "args": [case_data(schedule=True)]})
    for _ in range(count_each * 4):
        now = R.choice(NOW_POINTS)
        add({"fn": "buildPaymentSchedule", "args": [coherent_case(now) if R.random() < 0.5 else case_data(schedule=True)], "now": now})
    for _ in range(count_each * 3):
        now = R.choice(NOW_POINTS)
        add({"fn": "deriveLedgerSettlement", "args": [coherent_case(now) if R.random() < 0.5 else case_data(schedule=True), transaction()], "now": now})
    from datetime import date, timedelta
    for _ in range(count_each):   # 提醒：到期日與「今天」相差 7、0、-7、-14、-3… 天
        today = date(2026, 9, 25) + timedelta(days=R.randint(-40, 40))
        due = today + timedelta(days=R.choice([7, 0, -7, -14, -21, -3, 1, 6, 8, -1, -28]))
        add({"fn": "reminderKind", "args": [{"dueDate": due.isoformat(), "outstanding": R.choice([100, 1234.56, 0, 0.004, 0.005])}, today.isoformat()]})
    for _ in range(count_each):
        item = {}
        maybe_omit(item, "dueDate", R.choice(DATES_VALID + DATES_ODD + [MISSING]))
        maybe_omit(item, "outstanding", R.choice([0, 0.004, 0.005, 100, 1234.56, -5, None, MISSING, "50", "abc", 1e9]))
        add({"fn": "reminderKind", "args": [R.choice([{k: v for k, v in item.items() if v is not MISSING}] * 10 + [None, "x", {}]),
                                             R.choice(DATES_VALID + ["2026-09-18", "2026-09-25", "2026-10-02", "2026-10-09", "2026-09-04", "2026-08-28"])]})
    return vectors


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1200
    json.dump(build(count), sys.stdout, ensure_ascii=False, allow_nan=False)
