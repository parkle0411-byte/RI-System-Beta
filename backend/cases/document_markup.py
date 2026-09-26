"""
產生 PDF 前的 markup 檢查 - 對應 Alpha api/render-document-pdf.js 的 rejectUnsafeMarkup 與 handler 開頭的檢查。
純函式、不依賴 Django（差異測試 qa/calc/compare.py 直接 import：renderPdfRejectUnsafeMarkup、renderPdfMarkupStatus）。
"""
import re

from .calc.jsnum import JS_WS, js_trim

MAX_MARKUP_UNITS = 2_000_000          # JavaScript 的 markup.length（UTF-16 單位）

# Alpha rejectUnsafeMarkup 的正規式。JavaScript 的 /i（沒有 u 旗標）只做 ASCII 的大小寫對應、\w 與 \b 也只看 ASCII，
# 所以用 re.ASCII | re.I；但 JavaScript 的 \s 包含 Unicode 空白，re.ASCII 下要自己列出（JS_WS）。
_S = f"[{re.escape(JS_WS)}]"
_UNSAFE = [re.compile(p, re.ASCII | re.I) for p in (
    r"<(script|iframe|object|embed|link|base)\b",
    r"@import\b",
    rf"url{_S}*\(",
    rf"<img\b[^>]*\bsrc{_S}*={_S}*[\"'](?!data:image/jpeg;base64,)",
    rf"{_S}on\w+{_S}*=",
    rf"javascript{_S}*:",
)]


def js_length(text):
    return len(text.encode("utf-16-le")) // 2


def reject_unsafe_markup(value):
    return any(p.search(value) for p in _UNSAFE)


def markup_problem(markup):
    """Alpha handler 開頭的 markup 檢查（差異測試：renderPdfMarkupStatus）。回傳 (status, code, message) 或 None。"""
    if not isinstance(markup, str) or not js_trim(markup):
        return 400, "markup_required", "PDF markup is required."
    if js_length(markup) > MAX_MARKUP_UNITS:
        return 413, "markup_too_large", "PDF markup is too large."
    if reject_unsafe_markup(markup):
        return 400, "markup_unsafe", "PDF markup contains unsupported content."
    return None
