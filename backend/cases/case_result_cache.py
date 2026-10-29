"""每件案件記住「付款排程」與「交易明細」的答案（2026-10-29 效能優化，業主同意）。

這兩個計算只取決於「傳進去的案件資料」與「台北日期」（逾期判斷只看台北的今天是幾號），
所以用「資料內容的指紋 ＋ 台北日期」當鑰匙：資料改了任何一個字、或過了台北午夜，鑰匙就不同，會重新計算。
不依賴 row_version（測試與資料修補可能直接改資料而不加版本），也不會因為別的案件改變而失效（彼此獨立）。

- 每個 gunicorn worker 各自一份，放在記憶體；最多 RI_CASE_RESULT_CACHE_SIZE 筆（預設 30,000；1 萬件案件約需 2.1 萬筆，每筆約 4.5 KB），超過就丟掉最久沒用的。
- RI_CASE_RESULT_CACHE=false 可以整個關掉（直接計算，和以前完全相同）。
- 資料無法轉成 JSON（理論上不會發生）時不記，直接計算。
- 呼叫端只能讀取結果，不能修改（Accounting、Dashboard 都是另外組新的資料，最後整份回應還會深層複製）。
"""
import hashlib
import json
import os
import threading
from collections import OrderedDict

from .calc.payment_terms import taipei_date

_LOCK = threading.Lock()
_STORE = OrderedDict()


def enabled():
    return os.environ.get("RI_CASE_RESULT_CACHE", "true").strip().lower() != "false"


def _limit():
    try:
        return max(0, int(os.environ.get("RI_CASE_RESULT_CACHE_SIZE", "30000")))
    except ValueError:
        return 30000


def _key(kind, payload, now):
    try:
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=True)
    except (TypeError, ValueError):
        return None
    return (kind, taipei_date(now), hashlib.sha256(text.encode("utf-8", "surrogatepass")).digest())


def cached(kind, payload, now, compute):
    """kind：'schedule' 或 'details'；compute：沒有記住時實際計算的函式。"""
    if not enabled():
        return compute()
    key = _key(kind, payload, now)
    if key is None:
        return compute()
    with _LOCK:
        hit = _STORE.get(key)
        if hit is not None:
            _STORE.move_to_end(key)
            return hit
    value = compute()
    limit = _limit()
    if limit:
        with _LOCK:
            _STORE[key] = value
            _STORE.move_to_end(key)
            while len(_STORE) > limit:
                _STORE.popitem(last=False)
    return value


def clear():
    with _LOCK:
        _STORE.clear()
