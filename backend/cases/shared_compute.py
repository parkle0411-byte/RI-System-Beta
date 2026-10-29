"""Accounting 一次請求裡，同一件案件的付款排程與交易明細只算一次，讓付款排程列、SoA 交易列與 Swiss 排程共用。

2026-10-15 壓力測試（1 萬件案件）發現同一件案件的付款排程平均被算 2.3 次、有收款的案件交易明細被算兩次。
這裡不改任何計算規則：只有在「兩種呼叫方式的輸入內容完全相同」時才共用結果，否則維持原本各算各的。
  - transaction_rows 用「補上幣別與再保人」的 payload（override），其他地方用原本的 payload（raw）。
  - 兩者逐項相等（含型別）時，所有人用同一份 override 的結果；不相等（payload 缺 currency／reinsured 等）就各自計算。
結果不會被修改：付款排程列、交易列都是把欄位複製進新的字典，最後整份回應還會 json_roundtrip 深層複製。
"""
from datetime import datetime, timezone

from .calc.payment_terms import build_payment_schedule
from .cash_ledger import transaction_details
from .case_result_cache import cached


class CaseCompute:
    def __init__(self, case, now=None):
        self.case = case                                    # accounting_views._case_view 的結果
        self.now = now or datetime.now(timezone.utc)        # 整件案件共用同一個時間
        raw = case["payload"]
        self.override = {**raw, "currency": case["currency"], "reinsured": case["reinsured"]}
        self.same = self.override == raw and all(type(self.override[k]) is type(raw.get(k)) for k in ("currency", "reinsured"))
        self._memo = {}

    def _variant(self, variant):
        return "override" if (variant == "override" or self.same) else "raw"

    def payload(self, variant):
        return self.override if self._variant(variant) == "override" else self.case["payload"]

    def schedule(self, variant="raw"):
        key = ("schedule", self._variant(variant))
        if key not in self._memo:
            payload = self.payload(variant)
            # 2026-10-29：跨請求記住答案（同一份資料、同一個台北日期），見 case_result_cache
            self._memo[key] = cached("schedule", payload, self.now, lambda: build_payment_schedule(payload, self.now))
        return self._memo[key]

    def details(self, variant="raw"):
        key = ("details", self._variant(variant))
        if key not in self._memo:
            payload = self.payload(variant)
            self._memo[key] = cached("details", payload, self.now, lambda: transaction_details(payload, self.now, self.schedule(variant)))
        return self._memo[key]
