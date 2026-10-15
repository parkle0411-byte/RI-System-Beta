"""讀取型 API 的結果快取（Dashboard、Production Report）。2026-10-15 壓力測試後加入。

做法：每次請求先用很便宜的查詢取得「資料變更指紋」（案件筆數、版本號總和、最新更新時間…），指紋和上次相同、
而且還沒超過保險上限（預設 60 秒）才直接回傳上次算好的結果；否則重算並存起來。
  - 呼叫端必須「先取得指紋、再讀資料」：這樣中間有人存檔時，最壞只是多算一次，不會把舊資料標成新的。
  - 快取放在各 worker 自己的記憶體，重啟或部署後清空；最多保留 MAX_ENTRIES 筆。
  - 回傳的物件是共用的：呼叫端只能讀，不能修改（目前兩個呼叫端都只做 json_roundtrip，會深層複製）。
  - 寫入動作（Production 的 Generate／Close／Exclude）不使用快取，仍然每次從資料庫讀最新資料。
設定：RI_RESULT_CACHE=false 關閉（測試用）、RI_RESULT_CACHE_TTL 保險上限秒數。
"""
import threading
import time
from collections import OrderedDict

from django.conf import settings
from django.db.models import Count, Max, Sum

MAX_ENTRIES = 32
stats = {"hits": 0, "misses": 0}
_lock = threading.Lock()
_store = OrderedDict()


def enabled():
    return bool(getattr(settings, "RESULT_CACHE_ENABLED", True))


def table_fingerprint(queryset, version="row_version", stamp="updated_at"):
    """這批資料的變更指紋。每次存檔都會讓版本號加一、更新時間變新，所以任何新增、修改、停用、回收都會改變指紋。"""
    fields = {"n": Count("pk"), "top": Max("pk")}
    if version:
        fields["v"] = Sum(version)
    if stamp:
        fields["s"] = Max(stamp)
    return tuple(sorted(queryset.order_by().aggregate(**fields).items()))


def get_or_compute(key, fingerprint, compute):
    if not enabled():
        return compute()
    ttl = getattr(settings, "RESULT_CACHE_TTL_SECONDS", 60)
    with _lock:
        entry = _store.get(key)
        if entry and entry[0] == fingerprint and time.monotonic() - entry[1] < ttl:
            _store.move_to_end(key)
            stats["hits"] += 1
            return entry[2]
        stats["misses"] += 1
    started = time.monotonic()           # 以「開始計算」的時間起算保險上限
    value = compute()
    with _lock:
        _store[key] = (fingerprint, started, value)
        _store.move_to_end(key)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)
    return value


def clear():
    with _lock:
        _store.clear()
