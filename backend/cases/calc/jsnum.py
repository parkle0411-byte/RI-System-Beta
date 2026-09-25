"""
JavaScript 語意的小工具。

案件計算要與 Alpha（JavaScript）「逐位相同」，而 JavaScript 與 Python 在這些地方行為不同：
  - Math.round 對 .5 一律往正無限大進位（Python 的 round 是銀行家進位）
  - Number("...") 的解析規則（空字串 = 0、0x/0b/0o、Infinity；不接受底線、nan、全形數字）
  - 數字轉文字（50 而不是 50.0；1e-7；超過 1e21 才用指數）
  - 「空白」的定義（\\u00a0 與 \\ufeff 算空白；\\u180e、\\u200b、\\u0085 不算）
  - Date 對「2/30」這類日期是往後滾動，而不是判為無效
  - undefined 與 null 是兩回事（String(undefined) 是 "undefined"）
每一項都已用 Node 實測，並由差異測試（scripts/run_qa.sh calc）持續比對。
"""
import math
import re
import sys
from decimal import Decimal

EPSILON = sys.float_info.epsilon  # 與 Number.EPSILON 相同（2**-52）


class _Undefined:
    """JavaScript 的 undefined（與 None = null 區分）。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "UNDEFINED"

    def __bool__(self):
        return False


UNDEFINED = _Undefined()

# ECMAScript 的 WhiteSpace + LineTerminator（String.prototype.trim 與正則 \s 使用同一組）
JS_WS = "\t\n\x0b\x0c\r \xa0                　﻿"
WS_CLASS = "[\t\n\x0b\x0c\r \xa0  -     　﻿]"


def js_trim(text):
    return text.strip(JS_WS)


def is_nullish(value):
    return value is None or value is UNDEFINED


def js_truthy(value):
    if value is None or value is UNDEFINED or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return not (value == 0 or value != value)
    if isinstance(value, str):
        return value != ""
    return True  # 物件、陣列（包含空的）在 JavaScript 都是 truthy


def js_or(*values):
    """a || b || c：回傳第一個 truthy 的值；都不是就回傳最後一個。"""
    for value in values[:-1]:
        if js_truthy(value):
            return value
    return values[-1]


def get(obj, key):
    """obj?.key；找不到時是 undefined（不是 None）。"""
    if isinstance(obj, dict):
        return obj.get(key, UNDEFINED)
    return UNDEFINED


def at(seq, index):
    """seq?.[index]"""
    if isinstance(seq, list) and isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(seq):
        return seq[index]
    if isinstance(seq, dict) and isinstance(index, int) and not isinstance(index, bool):
        return seq.get(str(index), UNDEFINED)  # JavaScript 的 obj?.[0] 會取鍵 "0"
    return UNDEFINED


def js_spread(value):
    """{...value}：物件複製；字串與陣列會以「索引」為鍵展開；其他（數字、null、undefined）是空的。"""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        units = value.encode("utf-16-le", "surrogatepass")
        return {str(i): units[2 * i:2 * i + 2].decode("utf-16-le", "surrogatepass") for i in range(len(units) // 2)}
    if isinstance(value, list):
        return {str(i): v for i, v in enumerate(value)}
    return {}


def is_array(value):
    return isinstance(value, list)


def js_round(x):
    """Math.round：四捨五入，.5 往正無限大。"""
    if x != x or x in (math.inf, -math.inf):
        return x
    floor = math.floor(x)
    return float(floor + 1 if x - floor >= 0.5 else floor)


def money(value):
    """Math.round((Number(value) + Number.EPSILON) * 100) / 100"""
    return js_round((js_to_number(value) + EPSILON) * 100) / 100


def js_num_str(x):
    """Number::toString（ECMAScript 規範的十進位表示）。"""
    x = float(x)
    if x != x:
        return "NaN"
    if x == 0:
        return "0"
    if x == math.inf:
        return "Infinity"
    if x == -math.inf:
        return "-Infinity"
    sign = "-" if x < 0 else ""
    _, digits, exp = Decimal(repr(abs(x))).as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exp += 1
    ds = "".join(str(d) for d in digits)
    k, n = len(ds), exp + len(ds)
    if k <= n <= 21:
        body = ds + "0" * (n - k)
    elif 0 < n <= 21:
        body = ds[:n] + "." + ds[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + ds
    else:
        e = n - 1
        tail = ("e+" if e >= 0 else "e-") + str(abs(e))
        body = ds + tail if k == 1 else ds[0] + "." + ds[1:] + tail
    return sign + body


def js_to_string(value):
    """String(value)"""
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        try:
            return js_num_str(float(value))
        except OverflowError:
            return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join("" if is_nullish(v) else js_to_string(v) for v in value)
    return "[object Object]"


_RADIX = {
    "0x": (16, re.compile(r"[0-9a-fA-F]+")),
    "0o": (8, re.compile(r"[0-7]+")),
    "0b": (2, re.compile(r"[01]+")),
}
_DECIMAL_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def js_string_to_number(text):
    """Number(<字串>)"""
    t = js_trim(text)
    if t == "":
        return 0.0
    if t in ("Infinity", "+Infinity"):
        return math.inf
    if t == "-Infinity":
        return -math.inf
    prefix = t[:2].lower()
    if prefix in _RADIX and len(t) > 2:
        base, digits = _RADIX[prefix]
        if not digits.fullmatch(t[2:]):
            return math.nan
        try:
            return float(int(t[2:], base))
        except OverflowError:
            return math.inf
    if _DECIMAL_RE.fullmatch(t):
        return float(t)
    return math.nan


def js_to_number(value):
    """Number(value)"""
    if value is UNDEFINED:
        return math.nan
    if value is None or value is False:
        return 0.0
    if value is True:
        return 1.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
    if isinstance(value, str):
        return js_string_to_number(value)
    if isinstance(value, list):
        return js_string_to_number(js_to_string(value))
    return math.nan


def js_max(*values):
    """Math.max：只要有一個 NaN 結果就是 NaN（Python 的 max 不會）。"""
    return math.nan if any(v != v for v in values) else max(values)


def js_min(*values):
    return math.nan if any(v != v for v in values) else min(values)


def js_is_finite(x):
    return x == x and x not in (math.inf, -math.inf)


def js_is_integer(value):
    """Number.isInteger（只有「數字」才可能是整數；字串不算）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    x = float(value)
    return js_is_finite(x) and math.floor(x) == x


def strip_ws_regex(pattern, flags=0):
    """把 \\s 換成 JavaScript 的空白定義。"""
    return re.compile(pattern.replace("\\s", WS_CLASS), flags)


# ---------- 日期：JavaScript 的 Date（UTC）语意 ----------

def days_from_civil(y, m, d):
    y -= m <= 2
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + (m <= 2), m, d)


MAX_DAYS = 100_000_000  # JavaScript Date 的範圍：±8.64e15 毫秒 = ±1 億天


def parse_iso_date_days(text):
    """
    new Date("YYYY-MM-DDT00:00:00Z") 的天數（自 1970-01-01）；無效則回傳 None。
    V8 對日期是「往後滾動」：2026-02-30 → 3 月 2 日；但月份不在 1–12、日不在 1–31 就是無效。
    （呼叫者已先用 /^\\d{4}-\\d{2}-\\d{2}$/ 檢查過格式。）
    """
    y, m, d = int(text[0:4]), int(text[5:7]), int(text[8:10])
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    return days_from_civil(y, m, 1) + d - 1


def iso_date_prefix(days):
    """new Date(...).toISOString().slice(0, 10)"""
    y, m, d = civil_from_days(days)
    year = f"{y:04d}" if 0 <= y <= 9999 else ("+" if y > 0 else "-") + f"{abs(y):06d}"
    return f"{year}-{m:02d}-{d:02d}"[:10]
