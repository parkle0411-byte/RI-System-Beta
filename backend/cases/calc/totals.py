"""
案件合計（案件列表與畫面顯示用）。

**VM 刻意與 Alpha 不同的地方**：Alpha 有三套算法 ——
  - 記帳（lib/accounting.js）：每一步四捨五入到分（#3）
  - 案件列表（api/cases.js listFinancials）與畫面顯示（public/case-calculations.js）：完全不進位
兩者在「分」以下會不一致。依 2026-09-25 的決定，VM 一律採用「記帳」那一套（逐步進位），
所以列表、畫面、記帳三處看到的數字相同。差距上限見 qa/suites/case_totals.py 的量測。

做法：每一家再保人各自算出（已進位到分的）各項金額，合計後再進位一次。
"""
from .accounting import calc_legs_for_reinsurer
from .jsnum import get, is_array, money

# 畫面 totals() 的欄位名稱 <- calc_legs_for_reinsurer 的欄位名稱
_FIELDS = {
    "cedantPremium": "cp",
    "cedantCommission": "ri",
    "cedantTax": "tax",
    "leg1": "leg1",
    "reinsurerPremium": "reinsurerCp",
    "reinsurerDeductions": "reinsurerRi",
    "reinsurerTax": "reinsurerTax",
    "leg2": "leg2",
    "leg3": "leg3",
    "brokerage": "brokerage",
}


def for_reinsurer(case_data, reinsurer):
    """單一再保人的各項金額（畫面 forReinsurer 的欄位名稱）。"""
    legs = calc_legs_for_reinsurer(case_data, reinsurer)
    return {name: legs[source] for name, source in _FIELDS.items()}


def case_totals(case_data):
    """整個案件所有再保人的合計（畫面 totals 的欄位名稱）。"""
    reinsurers = get(case_data, "reinsurers")
    reinsurers = reinsurers if is_array(reinsurers) else []
    sums = {name: 0.0 for name in _FIELDS}
    for reinsurer in reinsurers:
        line = for_reinsurer(case_data, reinsurer)
        for name in sums:
            sums[name] += line[name]
    return {name: money(value) for name, value in sums.items()}


def list_financials(case_data):
    """案件列表每一列的兩個金額（Alpha 的 ourSharePremium 與 brokerage）。"""
    totals = case_totals(case_data)
    return {"ourSharePremium": totals["cedantPremium"], "brokerage": totals["brokerage"]}
