"""
案件草稿（normalizeDraft / validateAnnounceReady）的差異測試輸入。
依欄位類型（文字、數字、日期、月份、列、Clause 代碼…）各自產生：正常值、邊界值、型別錯誤、缺值、Unicode 刁鑽值，
並刻意製造「剛好在長度上限前後」的字串（含會被切在代理對中間的表情符號）與接近 250000 的大型 JSON。
"""
import random

MISSING = object()
R = random.Random(20260926)

# 「剛好在 250000 上下」的大型 JSON 只需要固定的一小批（每個約 250KB）；數量不隨向量總數成長，否則輸入檔會大到無法處理
BIG_LIMIT = 300
_big_used = [0]


def big_allowed():
    if _big_used[0] < BIG_LIMIT:
        _big_used[0] += 1
        return True
    return False

UNICODE_WS = [" ", " ", "﻿", "　", "\t", "\n", "᠎", "​", "\u0085"]
NAMES = ["Fubon Insurance", "  Cathay Life  ", "中國信託產險", "Ålesund Re", "Munich Re (Facility)", "AIG ", "", "x", "😀 Emoji Co", "Ünter Re"]


def maybe(d, key, value):
    if value is not MISSING:
        d[key] = value


def clean(d):
    return {k: v for k, v in d.items() if v is not MISSING}


def gen_text(max_len):
    r = R.random()
    if r < 0.30:
        return R.choice(NAMES)
    if r < 0.42:
        return "x" * R.choice([max_len - 1, max_len, max_len + 1, max_len + 5])
    if r < 0.48:
        return "y" * (max_len - 1) + "😀"                       # 表情符號跨過上限：JavaScript 會切在代理對中間
    if r < 0.52:
        return "  " + "z" * R.choice([max_len - 2, max_len - 1, max_len]) + "  "
    if r < 0.58:
        return R.choice(UNICODE_WS) + R.choice(["abc", "", "中文"]) + R.choice(UNICODE_WS)
    if r < 0.66:
        return None
    if r < 0.72:
        return MISSING
    if r < 0.80:
        return R.choice([5, 1.5, 0, -1, True, False, 1e21, 12345678901234567890])
    if r < 0.86:
        return R.choice([[], [1, 2], ["a", "b"], [None], [[1]]])
    if r < 0.90:
        return R.choice([{}, {"a": 1}])
    return R.choice(["", " ", "Some ordinary text", "Line1\nLine2", "tab\there", "Ω≈ç√∫", "\u0000ctrl", "ﬁ ß ŉ ǆ"])


def gen_num(lo=None, hi=None, integer=False):
    r = R.random()
    if r < 0.45:
        top = hi if hi is not None else 1e8
        base = lo if lo is not None else 0
        x = R.uniform(base, top)
        return int(x) if integer else round(x, R.choice([0, 1, 2, 2, 3, 4]))
    if r < 0.58:
        edge = [lo, hi, (lo - 1) if lo is not None else -1, (hi + 1) if hi is not None else 1e9, 0, 0.5, 1, 15, 14, 100, 101]
        return R.choice([e for e in edge if e is not None])
    if r < 0.66:
        return R.choice(["12", " 12 ", "12.5", "1,000", "abc", "", " ", "0x10", "1e3", "Infinity", "-5", "٣", "１２", " 5 "])
    if r < 0.72:
        return None
    if r < 0.78:
        return MISSING
    if r < 0.82:
        return R.choice([True, False])
    if r < 0.86:
        return R.choice([[], [5], [1, 2], ["7"], [None]])
    if r < 0.88:
        return R.choice([{}, {"a": 1}])
    return R.choice([1e21, -0.0, 1e-7, 123456789012345680000, 9007199254740993, 0.1 + 0.2, -1e-9, 1e308])


DATE_VALID = ["2026-01-01", "2026-03-15", "2026-12-31", "2024-02-29", "2000-02-29", "2026-09-25", "0100-01-01", "9999-12-31", "2100-02-28"]
DATE_ODD = ["2026-02-29", "2026-02-30", "2026-04-31", "2026-13-01", "2026-00-10", "2026-01-32", "2026-01-00", "0050-01-01", "0099-12-31", "0000-01-01",
            "2026-01-01T00:00:00Z", "2026-01-01 extra", " 2026-01-01", "2026-1-1", "2026/01/01", "", None, 20260101, [], "1900-02-29", "2100-02-29", "２０２６-０１-０１"]


def gen_date():
    r = R.random()
    if r < 0.5:
        return R.choice(DATE_VALID)
    if r < 0.85:
        return R.choice(DATE_ODD)
    return MISSING


def gen_month():
    return R.choice(["2026-01", "2026-12", "2026-13", "2026-00", "202601", "2026-1", "", None, MISSING, 202601, "bad", "2026-01-01", " 2026-01", "abcd-ef", "2026-01x"])


def gen_time():
    return R.choice(["12:00", "00:00", "", None, MISSING, "12:00", "00:00", "13:00", "24:00", "0:00", " 12:00 ", "12:00:00", 12, "midnight"])


def gen_rows(row_fn, max_rows, over=True):
    r = R.random()
    if r < 0.05:
        return R.choice([None, MISSING, "x", 5, {}, {"0": {}}, True])
    n = R.choice([0, 1, 1, 2, 2, 3, 4, 6])
    if over and R.random() < 0.05:
        n = max_rows + R.choice([0, 1, 3])
    rows = []
    for _ in range(n):
        rows.append(R.choice([None, "x", 5, []]) if R.random() < 0.04 else row_fn())
    return rows


def situation():
    return clean({"address": gen_text(500), "postcode": R.choice(["100", "10001", "123456", "1234567", "12", "ab123", "", None, MISSING, 10001, " 110 ", "１２３", "12 3"])})


def reinsurer():
    return clean({"name": gen_text(240), "sharePct": gen_num(0, 100), "premium": gen_num(0), "riCommPct": gen_num(0, 100), "taxPct": gen_num(0, 100),
                  "paymentTermsDays": gen_num(15, None, True), "foreignBroker": gen_text(240), "settlementRef": gen_text(160)})


def sum_insured():
    return clean({"category": gen_text(240), "amount": gen_num(0), "locationIndex": gen_num(0, None, True)})


def gen_json_any():
    r = R.random()
    if r < 0.25:
        return R.choice([None, MISSING])
    if r < 0.5:
        return {f"r{i}": R.choice([15, 30, "45", None, 20.5]) for i in range(1, R.choice([1, 3, 5]))}
    if r < 0.6:
        return {"2": "b", "1": "a", "z": [1, {"k": None}], "-0": -0.0}
    if r < 0.7:
        return R.choice([5, "text", True, [1, [2, [3]]], [None, 1.5, "é😀"]])
    if r < 0.75 and big_allowed():
        # {"big":"…"} 的外框是 10 個字元，所以 249_990 剛好 = 250000（允許），249_991 = 250001（太大）
        return {"big": "x" * R.choice([249_980, 249_989, 249_990, 249_991, 249_992, 250_001])}
    if r < 0.8 and big_allowed():
        # 表情符號在 JSON 字串裡佔 2 個 UTF-16 單位；124_995 個 = 249_990 單位，再加 1 個字母 = 249_991
        return {"emoji": R.choice(["😀" * 124_995, "😀" * 124_995 + "x", "😀" * 124_996, "😀" * 100, "😀"])}
    return {"nested": {"a": [1, 2, {"b": "c"}]}, "s": "quote\" back\\ ctl\u0001  "}


def installment():
    return clean({"id": gen_text(100), "performanceMonth": gen_month(), "paymentBaseDate": gen_date(), "paymentTermsDays": gen_num(15, None, True),
                  "reinsurerPaymentTerms": gen_json_any(), "premium": gen_num(0), "ratio": gen_num(0, 100)})


def split_party():
    return clean({"personnelId": gen_num(1, None, True), "name": gen_text(160), "pct": gen_num(0, 100)})


def loss_row():
    return clean({"date": gen_date(), "cause": gen_text(1000), "lossPaid": gen_num(0)})


CLAUSE_CODES = ["LMA3333", "lma 3333", "INTERMEDIARY", "NMA 2918", "nma2918", "LPO_98", "LPO 98", "ALLIANZ SANCTION", "x_1", "X-1", "A.1", "a  b",
                "LMA_5", "LMA5", "LMA10", "LMA2", "É1", "E1", "F1", "中文", "\u0001A", "A\u0001", "AB", "A_B", "A-B", "a1", "A1", "  padded  ", "", None,
                "LMA" + "9" * 80, "ß1", "ǆ", "ﬁ"]


# Clause 代碼排序（ICU）已量測與 Alpha 一致的字元類別；非 ASCII 的符號/貨幣符號是已知限制，不放進向量（見 jsnum.js_locale_key）
SUPPORTED_ALPHABETS = [
    list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.,;:!?'\"()[]{}@*/\\&#%`^+<=>|~$ "),
    list("ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝŒŠŽÐÞĐŁĲŊàáâãäåæçèéêëìíîïñòóôõöøùúûüýœšžðþđłĳŋ"),
    list("ＡＢＣ１２３ﬁﬂǄǇǊ㎏№"), list("ΑΒΓΔΕΖΗΘΛΜΠΣΩ"), list("АБВГДЕЖЗИКЛМНОПРСТ"), list("中文字條款保險日本語한국어"),
]


def random_clause_code():
    alphabet = R.choice(SUPPORTED_ALPHABETS) + list("ABC123_")
    return "".join(R.choice(alphabet) for _ in range(R.choice([1, 2, 3, 4, 6])))


def clause_row():
    r = R.random()
    if r < 0.05:
        return R.choice([None, "x", 5])
    return clean({"code": R.choice(CLAUSE_CODES + [random_clause_code()] * 8 + [MISSING]), "title": R.choice(["Title", " Padded title ", "", None, MISSING, "T" * 300, "T" * 301, "中文標題", 5])})


def draft_input():
    d = {}
    maybe(d, "ownerPersonnelId", gen_num(1, None, True))
    maybe(d, "ownerPersonnelName", gen_text(160))
    maybe(d, "parentTwRef", gen_text(120))
    maybe(d, "endorsementSeq", gen_num(0, None, True))
    maybe(d, "renewedFromTwRef", gen_text(120))
    maybe(d, "endoEffectiveDate", gen_date())
    maybe(d, "endoTypes", R.choice([["Change of address", "Extension"], [], None, MISSING, "x", ["a"] * 21, ["", "  ", "b", 5, None, {"a": 1}], [{"a": 1}]]))
    maybe(d, "endoText", gen_text(5000))
    maybe(d, "type", R.choice(["Property Facultative Reinsurance", "Marine Excess of Loss Facultative Reinsurance", "Something", "Facultative Reinsurance", " Property  Reinsurance Treaty ", "", None, MISSING, gen_text(200), "X" * 250 + "Facultative Reinsurance"]))
    maybe(d, "typePrefix", R.choice([gen_text(120), "", MISSING, "Property", "Marine "]))
    for key, n in (("originalInsured", 240), ("originalInsuredCn", 240), ("reinsured", 240), ("classOfBusiness", 160), ("classCode", 80)):
        maybe(d, key, gen_text(n))
    maybe(d, "situations", gen_rows(situation, 50))
    maybe(d, "reinsuranceStructure", R.choice(["QS", "qs", "XOL", "TREATY", "FACULTATIVE", "Facultative", " treaty ", "", None, MISSING, "bad", "ｑｓ", "QS" + "x" * 30, 5]))
    maybe(d, "policyFrom", gen_date())
    maybe(d, "policyTo", gen_date())
    maybe(d, "policyFromTime", gen_time())
    maybe(d, "policyToTime", gen_time())
    maybe(d, "currency", R.choice(["USD", "usd", "Eur", "TWD", "US", "USDX", "us1", "", None, MISSING, "ßß", "ǆǆ", "us d", 5, "u s", " USD"]))
    maybe(d, "originalPremium", gen_num(0))
    maybe(d, "riCommPct", gen_num(0, 100))
    maybe(d, "taxPct", gen_num(0, 100))
    maybe(d, "paymentTermsDays", gen_num(15, None, True))
    maybe(d, "installmentEnabled", R.choice([True, True, False, None, MISSING, "true", 1]))
    maybe(d, "performanceInstallments", gen_rows(installment, 50))
    maybe(d, "splitEnabled", R.choice([True, False, None, MISSING, "true", 1]))
    maybe(d, "splitParties", gen_rows(split_party, 50))
    maybe(d, "reinsurers", gen_rows(reinsurer, 50))
    maybe(d, "sumInsured", gen_rows(sum_insured, 50))
    maybe(d, "lossAdvisedDate", gen_date())
    maybe(d, "lossRecordYears", gen_num(0, None, True))
    maybe(d, "lossRecord", gen_rows(loss_row, 50))
    maybe(d, "lossRecordText", gen_text(5000))
    maybe(d, "manualClauses", R.choice([MISSING, None, "x", [], [clause_row() for _ in range(R.choice([1, 2, 3, 5]))], [clause_row() for _ in range(101)]]))
    maybe(d, "clauseDetails", R.choice([MISSING, None, 5, [], [clause_row() for _ in range(R.choice([1, 2, 4, 8]))]]))
    for key, n in (("interest", 3000), ("underlyingLimits", 3000), ("subLimits", 3000), ("deductibles", 3000), ("reinsuredRetention", 3000),
                   ("reinstatementProvisions", 3000), ("indemnityPeriod", 1000), ("originalExclusions", 5000), ("originalConditions", 5000),
                   ("expressWarranties", 3000), ("conditionsPrecedent", 3000), ("subjectivities", 3000), ("occupation", 3000),
                   ("construction", 3000), ("lossPayee", 3000), ("notices", 5000), ("specialAgreement", 5000), ("ae", 160), ("newOrRenew", 20),
                   ("remark", 5000), ("postedAt", 80), ("statementNo", 160)):
        maybe(d, key, gen_text(n))
    maybe(d, "limitOfLiability", gen_num(0))
    maybe(d, "aggregateLimit", gen_num(0))
    maybe(d, "basisOfValuation", R.choice(["Replacement Cost", "Other", "other", "Market Value", "", None, MISSING, " Other "]))
    maybe(d, "basisOfValuationOther", gen_text(1000))
    maybe(d, "exchRate", gen_num(0))
    maybe(d, "confirmedProductionKeys", R.choice([MISSING, None, "x", ["a", "b"], [], ["x"] * 201, ["", " ", "k", 5, None]]))
    maybe(d, "productionExclusions", gen_json_any())
    for key in ("endorsements", "transactions", "claims", "accountingNotifications", "paymentEntries"):
        maybe(d, key, R.choice([MISSING, None, "x", [], [{"a": 1}, {"b": [1, 2]}], [{"k": "v"}] * 501, {"a": 1}, [None, 5, "s"],
                                [{"k": "x" * R.choice([249_989, 249_990, 249_991])}] if big_allowed() else [{"k": "small"}]]))   # 陣列外框同樣是 10 個字元
    maybe(d, "reversalCycle", gen_num(0, None, True))
    maybe(d, "pendingReversalOffset", R.choice([True, False, 1, 0, "1", None, MISSING, 2, [1], "abc"]))
    maybe(d, "paymentScheduleReviewRequired", R.choice([True, False, None, MISSING, "true", 1]))
    # 一些不在白名單內的欄位（應該被丟棄）
    if R.random() < 0.3:
        d["status"] = R.choice(["posted", "closed"])
        d["unknownField"] = "should be dropped"
    return clean(d)


def complete_payload():
    """一份「所有 Announce 必填欄位都齊全」的已整理過的案件，供 validateAnnounceReady 隨機弄壞。"""
    return {
        "ownerPersonnelId": 29, "reinsuranceStructure": "QS", "ae": "S.K", "currency": "USD", "classOfBusiness": "Property", "newOrRenew": "New",
        "type": "Property Facultative Reinsurance", "reinsured": "Fubon", "originalInsured": "Acme Corp", "policyFrom": "2026-01-01", "policyTo": "2027-01-01",
        "interest": "Buildings", "situations": [{"address": "1 Main St", "postcode": "100"}],
        "reinsurers": [{"name": "Munich Re", "sharePct": 60, "premium": 100000, "riCommPct": 10, "taxPct": 2},
                       {"name": "Swiss Re", "sharePct": 40, "premium": 80000, "riCommPct": 8, "taxPct": 0}],
        "limitOfLiability": 5000000, "deductibles": "USD 10,000", "originalConditions": "As original", "basisOfValuation": "Replacement Cost",
        "occupation": "Office", "construction": "Concrete", "sumInsured": [{"category": "Building", "amount": 5000000, "locationIndex": 0}],
        "lossAdvisedDate": "2026-01-01", "lossRecordYears": 5, "lossRecord": [{"date": "2025-05-05", "cause": "Fire", "lossPaid": 1000}],
        "originalPremium": 200000, "paymentTermsDays": 30, "riCommPct": 12.5, "taxPct": 3, "installmentEnabled": False, "performanceInstallments": [],
        "splitEnabled": False, "splitParties": [], "parentTwRef": "", "endoEffectiveDate": "", "endoTypes": [], "endoText": "",
    }


def mutate_payload():
    p = complete_payload()
    for _ in range(R.choice([0, 0, 1, 1, 2, 3, 5])):
        key = R.choice(list(p))
        p[key] = R.choice([MISSING, None, "", "  ", 0, "x", [], {}, gen_text(20), gen_num(0), False, "Other", 5])
    if R.random() < 0.3:
        p["installmentEnabled"] = R.choice([True, 1, "yes"])
        p["performanceInstallments"] = gen_rows(lambda: clean({"performanceMonth": gen_month(), "paymentBaseDate": gen_date(), "premium": gen_num(0), "ratio": gen_num(0, 100)}), 6, over=False)
        if R.random() < 0.5:
            p["originalPremium"] = R.choice([0, "0", None, 100000, 200000])
    if R.random() < 0.3:
        p["splitEnabled"] = R.choice([True, 1, "yes"])
        p["splitParties"] = R.choice([[split_party(), split_party()], [split_party()], [], [split_party() for _ in range(3)],
                                      [{"name": "A", "personnelId": 1, "pct": 60}, {"name": "b", "personnelId": 2, "pct": 40}],
                                      [{"name": "A", "personnelId": 1, "pct": 50}, {"name": " a ", "personnelId": 1, "pct": 50}]])
    if R.random() < 0.2:
        p["parentTwRef"] = "TW-1"
        for k in R.sample(["endoEffectiveDate", "endoTypes", "endoText"], R.choice([0, 1, 2, 3])):
            p[k] = R.choice(["2026-01-01", ["x"], "text", "", [], None])
    if R.random() < 0.15:
        p["basisOfValuation"] = "Other"
        p["basisOfValuationOther"] = R.choice(["", "Something", None, MISSING])
    if R.random() < 0.15:
        p["reinsurers"] = gen_rows(lambda: clean({"name": R.choice(["A", "", None, MISSING]), "sharePct": gen_num(0, 100), "premium": gen_num(0),
                                                  "riCommPct": gen_num(0, 100), "taxPct": gen_num(0, 100)}), 6, over=False)
    if R.random() < 0.1:
        p["situations"] = gen_rows(situation, 6, over=False)
    return clean(p)


def valid_draft():
    """大致合法的案件草稿（前端正常送出的樣子），再隨機混入 0–2 個缺陷。"""
    n_re = R.choice([1, 2, 3, 4])
    d = {
        "ownerPersonnelId": R.choice([1, 29, 35]), "ownerPersonnelName": "Parkle Law", "type": R.choice(["", "Property"]),
        "typePrefix": R.choice(["Property", "Marine Cargo", ""]), "originalInsured": "Acme Corporation", "originalInsuredCn": "亞克美股份有限公司",
        "reinsured": "Fubon Insurance", "classOfBusiness": "Property", "classCode": "PF", "reinsuranceStructure": R.choice(["QS", "XOL", "TREATY", "FACULTATIVE"]),
        "situations": [{"address": f"{i + 1} Main Street, Taipei", "postcode": R.choice(["100", "10001", "110"])} for i in range(R.choice([1, 2, 3]))],
        "policyFrom": "2026-01-01", "policyTo": "2026-12-31", "policyFromTime": R.choice(["12:00", "00:00"]), "policyToTime": "12:00", "currency": "USD",
        "originalPremium": round(R.uniform(10000, 9_000_000), 2), "riCommPct": R.choice([10, 12.5, 7.35]), "taxPct": R.choice([0, 3, 0.75]),
        "paymentTermsDays": R.choice([30, 45, 60]), "installmentEnabled": R.choice([True, False]),
        "performanceInstallments": [{"id": f"I{i + 1}", "performanceMonth": f"2026-0{i + 1}", "paymentBaseDate": f"2026-0{i + 1}-15",
                                     "paymentTermsDays": 30, "reinsurerPaymentTerms": {"r1": 30}, "premium": 1000.5, "ratio": 50} for i in range(R.choice([0, 2]))],
        "splitEnabled": R.choice([True, False]),
        "splitParties": [{"personnelId": 1, "name": "A", "pct": 60}, {"personnelId": 2, "name": "B", "pct": 40}],
        "reinsurers": [{"name": f"Reinsurer {i + 1}" + R.choice(["", " (Facility)"]), "sharePct": round(100 / n_re, 2), "premium": round(R.uniform(1e4, 1e6), 2),
                        "riCommPct": R.choice([5, 10]), "taxPct": R.choice([0, 2]), "paymentTermsDays": R.choice([30, 45]),
                        "foreignBroker": R.choice(["", "Aon Re"]), "settlementRef": "SR-1"} for i in range(n_re)],
        "sumInsured": [{"category": "Building", "amount": 5_000_000, "locationIndex": 0}, {"category": "Stock", "amount": 1_250_000.5, "locationIndex": 1}],
        "lossAdvisedDate": "2026-01-01", "lossRecordYears": 5, "lossRecord": [{"date": "2025-05-05", "cause": "Fire", "lossPaid": 1000}],
        "lossRecordText": "No losses", "interest": "Buildings and contents", "limitOfLiability": 5_000_000, "aggregateLimit": 10_000_000,
        "underlyingLimits": "USD 1m xs 1m", "deductibles": "USD 10,000", "originalConditions": "As original", "basisOfValuation": R.choice(["Replacement Cost", "Other"]),
        "basisOfValuationOther": "Agreed value", "occupation": "Office", "construction": "Concrete", "ae": "S.K", "newOrRenew": "New", "exchRate": 32.5,
        "manualClauses": [{"code": R.choice(["NMA 2918", "lpo 98", "LMA 5001"]), "title": "Some clause"}] if R.random() < 0.7 else [],
        "clauseDetails": [{"code": "NMA2918", "title": "War"}, {"code": "LMA3333", "title": "Reinsurers Liability Clause"}] if R.random() < 0.5 else [],
        "statementNo": "ST-001", "remark": "note", "reversalCycle": R.choice([0, 1, 2]), "pendingReversalOffset": R.choice([True, False, 1, 0]),
        "endorsements": [{"n": 1}], "transactions": [], "claims": [{"id": 1}], "paymentEntries": [{"scheduleKey": "I1:cedant", "amount": 10}],
    }
    if R.random() < 0.4:
        d.update({"parentTwRef": "TW-2026-0001", "endorsementSeq": 1, "endoEffectiveDate": "2026-06-01", "endoTypes": ["Change of limit"], "endoText": "Limit increased"})
    noisy = draft_input()
    for key in R.sample(sorted(d), R.choice([0, 0, 1, 1, 2, 2, 3])):
        if key in noisy:
            d[key] = noisy[key]
        else:
            d.pop(key, None)
    return d


def collation_vectors():
    """專門針對 Clause 代碼排序的輸入（固定數量）：每個已支持的字元類別各一批，拉丁字母（重音、連字、帶橫線）加重。"""
    latin = list("ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝŒŠŽÐÞĐŁĲŊ")
    groups = SUPPORTED_ALPHABETS + [latin, latin, latin, list("AEOÆŒÀÈÒÓÁÉØ")]
    vectors = []
    for alphabet in groups:
        for _ in range(60):
            rows = []
            for _ in range(R.choice([3, 4, 5, 6])):
                code = "".join(R.choice(alphabet + list("ABC123_")) for _ in range(R.choice([1, 2, 3, 4])))
                rows.append({"code": code, "title": "t"})
            vectors.append({"fn": "normalizeDraft", "args": [{"manualClauses": rows}]})
    # 「主要層級相同、只在次要/第三層級不同」的對照組：連字、帶橫線字母、各種重音、大小寫要放在一起排才分得出先後
    families = [
        ["OE", "Œ", "ÒE", "OÈ", "ÒÈ", "ÓE", "ŒA", "OEA", "œ", "oe", "ÖE"],
        ["AE", "Æ", "ÀE", "AÈ", "ÁE", "ÆA", "AEA", "æ", "ae", "ÄE", "ÅE"],
        ["O", "Ø", "Ó", "Ò", "Ö", "Ô", "Õ", "Ő", "ø", "o", "Ǫ"],
        ["D", "Ð", "Đ", "Ď", "ð", "đ", "d"],
        ["L", "Ł", "Ĺ", "Ľ", "ł", "l", "Ļ"],
        ["A", "À", "Á", "Â", "Ã", "Ä", "Å", "Ā", "Ă", "Ą", "a", "à"],
        ["E1", "É1", "È1", "Ê1", "Ë1", "e1", "É2", "E2", "È2"],
        ["N", "Ŋ", "Ñ", "Ń", "Ň", "n", "ŋ", "O"],
    ]
    for _ in range(200):
        family = R.choice(families)
        picks = R.sample(family, R.choice([3, 4, 5, min(6, len(family))]))
        vectors.append({"fn": "normalizeDraft", "args": [{"manualClauses": [{"code": c, "title": "t"} for c in picks]}]})
    return vectors


def build(count_each):
    _big_used[0] = 0
    vectors = collation_vectors()
    for _ in range(count_each * 2):
        vectors.append({"fn": "normalizeDraft", "args": [R.choice([draft_input()] * 30 + [None, "x", 5, [], [1], True, {}])]})
    for _ in range(count_each * 2):
        vectors.append({"fn": "normalizeDraft", "args": [valid_draft()]})
    for _ in range(count_each * 2):
        vectors.append({"fn": "validateAnnounceReady", "args": [mutate_payload()]})
    for _ in range(count_each // 3):
        vectors.append({"fn": "validateAnnounceReady", "args": [R.choice([draft_input(), None, "x", 5, [], {}, {"situations": "x"}])]})
    return vectors
