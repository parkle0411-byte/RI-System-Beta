"""
案件合計（VM 統一成「逐步進位」的記帳算法）的性質檢查，並量化與 Alpha「未進位」算法的差距。
不需要資料庫。用法：manage.py shell < 這個檔案（scripts/run_qa.sh suites 會自動執行）。
"""
import random

from cases.calc.accounting import build_premium_transactions, calc_legs_for_reinsurer
from cases.calc.jsnum import money
from cases.calc.totals import case_totals, for_reinsurer, list_financials

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


R = random.Random(20260925)


def pct():
    return R.choice([0, 100, 50, 33.33, 33.34, 12.5, 7.35, 0.75, 17.77, 10, 5, 2.5, 1, 25, 66.67, round(R.uniform(0, 100), R.choice([1, 2, 3, 4]))])


def case():
    n = R.choice([0, 1, 2, 3, 4, 5, 6])
    return {
        "twRef": "TW-1",
        "originalPremium": round(R.uniform(1000, 900_000_000), R.choice([0, 1, 2, 2, 2, 3])),
        "riCommPct": pct(), "taxPct": pct(),
        "reinsurers": [{"name": f"R{i}", "sharePct": pct(), "premium": round(R.uniform(1000, 900_000_000), R.choice([0, 2, 2, 3])),
                        "riCommPct": pct(), "taxPct": pct()} for i in range(n)],
    }


def alpha_unrounded(case_data):
    """Alpha 案件列表（cases.js listFinancials）與畫面（case-calculations.js）的「未進位」算法，照原始碼公式。"""
    total = {"cedantPremium": 0.0, "leg1": 0.0, "leg2": 0.0, "brokerage": 0.0}
    for r in case_data["reinsurers"]:
        order = float(r["sharePct"] or 0) / 100
        cp = float(case_data["originalPremium"] or 0) * order
        leg1 = cp - cp * float(case_data["riCommPct"] or 0) / 100 - cp * float(case_data["taxPct"] or 0) / 100
        rp = float(r["premium"] or 0) * order
        leg2 = rp - rp * float(r["riCommPct"] or 0) / 100 - rp * float(r["taxPct"] or 0) / 100
        total["cedantPremium"] += cp
        total["leg1"] += leg1
        total["leg2"] += leg2
        total["brokerage"] += leg1 - leg2
    return total


cases = [case() for _ in range(4000)]
worst = {"cedantPremium": 0.0, "leg1": 0.0, "leg2": 0.0, "brokerage": 0.0}
bad_sum = bad_broker = bad_list = bad_line = bad_tx = bad_cent = bad_bound = 0
for c in cases:
    totals = case_totals(c)
    legs = [calc_legs_for_reinsurer(c, r) for r in c["reinsurers"]]
    # 1. 合計 = 各再保人（已進位）金額相加後再進位
    for key, src in (("cedantPremium", "cp"), ("cedantCommission", "ri"), ("cedantTax", "tax"), ("leg1", "leg1"),
                     ("reinsurerPremium", "reinsurerCp"), ("reinsurerDeductions", "reinsurerRi"), ("reinsurerTax", "reinsurerTax"),
                     ("leg2", "leg2"), ("leg3", "leg3"), ("brokerage", "brokerage")):
        if totals[key] != money(sum(l[src] for l in legs)):
            bad_sum += 1
    # 2. Brokerage = Leg 1 - Leg 2（逐家進位後，差額仍是整分）
    if totals["brokerage"] != money(totals["leg1"] - totals["leg2"]):
        bad_broker += 1
    # 3. 列表的兩個金額就是合計裡的兩項
    lf = list_financials(c)
    if lf != {"ourSharePremium": totals["cedantPremium"], "brokerage": totals["brokerage"]}:
        bad_list += 1
    # 4. 每一家的單行金額與記帳算法一致
    for r, l in zip(c["reinsurers"], legs):
        line = for_reinsurer(c, r)
        if (line["leg1"], line["leg2"], line["leg3"], line["cedantPremium"]) != (l["leg1"], l["leg2"], l["leg3"], l["cp"]):
            bad_line += 1
    # 5. 記帳交易（不拆分）加總 = 合計（畫面、列表、記帳三處相同）
    tx = build_premium_transactions(c)
    for leg, key in (("Leg 1", "leg1"), ("Leg 2", "leg2"), ("Leg 3", "brokerage")):
        if money(sum(t["amount"] for t in tx if t["legType"] == leg)) != totals[key]:
            bad_tx += 1
    # 6. 所有金額都是整分（沒有浮點殘渣）
    for v in totals.values():
        if v != money(v):
            bad_cent += 1
    # 7. 與 Alpha 未進位算法的差距：每家再保人最多 3 個進位點，每個最多 0.005（再加合計進位 0.005）
    ref = alpha_unrounded(c)
    n = max(len(c["reinsurers"]), 1)
    for key in worst:
        diff = abs(totals[key] - ref[key])
        worst[key] = max(worst[key], diff)
        if diff > 0.005 * (8 * n + 1) + 1e-6 * max(1.0, abs(ref[key])):
            bad_bound += 1

n_cases = len(cases)
check(f"{n_cases} random cases: totals = sum of per-reinsurer rounded amounts", bad_sum == 0, bad_sum)
check("Brokerage = Leg 1 - Leg 2 in every case", bad_broker == 0, bad_broker)
check("list figures (ourSharePremium, brokerage) equal the totals", bad_list == 0, bad_list)
check("per-reinsurer lines equal the accounting legs", bad_line == 0, bad_line)
check("accounting transactions add up to the totals (list = screen = ledger)", bad_tx == 0, bad_tx)
check("every total is a whole number of cents (no floating-point residue)", bad_cent == 0, bad_cent)
check("difference from Alpha's unrounded figures stays within the rounding bound", bad_bound == 0, bad_bound)
check("empty / missing reinsurers give zero totals", all(v == 0 for v in case_totals({"originalPremium": 100}).values())
      and all(v == 0 for v in case_totals(None).values()))
check("known example: 1,234,567.89 @33.33%, 12.5% + 3% -> Leg1 347701.85, Brokerage 25067.45",
      case_totals({"originalPremium": 1234567.89, "riCommPct": 12.5, "taxPct": 3,
                   "reinsurers": [{"sharePct": 33.33, "premium": 1100000, "riCommPct": 10, "taxPct": 2}]})["leg1"] == 347701.85
      and case_totals({"originalPremium": 1234567.89, "riCommPct": 12.5, "taxPct": 3,
                       "reinsurers": [{"sharePct": 33.33, "premium": 1100000, "riCommPct": 10, "taxPct": 2}]})["brokerage"] == 25067.45)

fails = [r for r in results if not r[1]]
for n, ok, d in results:
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed")
print("VM 與 Alpha 未進位算法的最大差距（{} 個隨機案件，單位：該幣別）：".format(n_cases)
      + ", ".join(f"{k}={v:.4f}" for k, v in worst.items()))
