"""
案件文件的純邏輯（不碰資料庫與檔案）。移植自 Hatchable Alpha 的 api/case-documents.js
（reinsurerKey、requiredReinsurers、coverageFor、safeFilename、decodeAndValidate），
並以差異測試與 Alpha 原始 JavaScript 逐位比對（backend/qa/alpha_js/excerpts/case-documents-excerpts.js）。

與 Alpha 的差異：單檔上限由呼叫者傳入（VM 是 10 MB，Alpha 是 5 MB；差異測試用 5 MB 比對邏輯）。
"""
import base64
import re
from urllib.parse import quote

from .calc.jsnum import get, is_array, js_or, js_slice, js_to_string, js_truthy
from .calc.signed_slip import reinsurer_key, required_reinsurers

EXTENSIONS = ("pdf", "docx", "png", "jpg", "jpeg", "eml", "msg")
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "eml": "message/rfc822", "msg": "application/vnd.ms-outlook",
}
_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\]")
_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z")
# JavaScript 的 /^(?:From|…):/im：多行模式下 ^ 可以在 \n 或 \r 之後；i 旗標只對 ASCII 字母有效（latin1 內容）
_EML_HEADER = re.compile(
    rb"(?:\A|(?<=[\n\r]))(?:From|Return-Path|Received|Delivered-To|MIME-Version|Message-ID|Date|Subject):", re.I)
_MB = 1024 * 1024

__all__ = ["reinsurer_key", "required_reinsurers", "coverage_for", "safe_filename", "decode_and_validate",
           "storable_text", "content_disposition"]


def coverage_for(payload, files):
    """文件頁的涵蓋狀態（與 Announce 的 coverage 不同：多了 covered、selected 不排序、再保人名稱不去掉 Facility）。"""
    selected = [f for f in files if js_truthy(get(f, "is_selected"))]
    required = required_reinsurers(payload)
    offer = any(get(f, "kind") == "offer" for f in selected)
    covered = set()
    for f in selected:
        if get(f, "kind") in ("signed", "confirmation"):
            names = get(f, "reinsurers")
            for name in names if is_array(names) else []:
                covered.add(reinsurer_key(name))
    missing = [name for name in required if name not in covered]
    return {
        "offer": offer, "required": required, "covered": [name for name in required if name in covered],
        "missing": missing, "ready": offer and len(required) > 0 and len(missing) == 0,
        "selected": [get(f, "id") for f in selected],
    }


def safe_filename(value):
    """String(value || '').replace(/[\\x00-\\x1f\\x7f/\\\\]/g, '_').slice(0, 180)（以 UTF-16 單位截斷）"""
    return js_slice(_UNSAFE.sub("_", js_to_string(js_or(value, ""))), 0, 180)


def _size_text(max_bytes):
    return f"{max_bytes // _MB} MB" if max_bytes % _MB == 0 else f"{max_bytes} bytes"


def decode_and_validate(filename, encoded, max_bytes):
    """回傳 {"ext", "bytes", "contentType"} 或 {"error": [HTTP 狀態碼, 訊息]}。"""
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in EXTENSIONS:
        return {"error": [415, "Use PDF, DOCX, PNG, JPG, EML or MSG."]}
    limit = -(-max_bytes // 3) * 4 + 8  # Math.ceil(MAX_BYTES / 3) * 4 + 8
    if not isinstance(encoded, str) or not encoded or _utf16_len(encoded) > limit:
        return {"error": [413, f"Each file must be nonempty and no larger than {_size_text(max_bytes)}."]}
    if not _BASE64.match(encoded):
        return {"error": [400, "Invalid file encoding."]}
    raw = base64.b64decode(encoded)
    if not raw or len(raw) > max_bytes:
        return {"error": [413, f"Maximum file size is {_size_text(max_bytes)}."]}
    if ext == "pdf":
        matches = raw.startswith(b"%PDF-")
    elif ext == "png":
        matches = raw.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10]))
    elif ext in ("jpg", "jpeg"):
        matches = raw.startswith(bytes([255, 216, 255]))
    elif ext == "docx":
        matches = raw.startswith(bytes([80, 75, 3, 4])) and b"[Content_Types].xml" in raw and b"word/" in raw
    elif ext == "msg":
        matches = raw.startswith(bytes([208, 207, 17, 224, 161, 177, 26, 225]))
    else:
        matches = _EML_HEADER.search(raw[:8192]) is not None
    if not matches:
        return {"error": [415, "File content does not match its extension."]}
    return {"ext": ext, "bytes": raw, "contentType": CONTENT_TYPES[ext]}


def _utf16_len(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def storable_text(text):
    """
    存進 MySQL 前把「落單的 UTF-16 代理字元」換成 U+FFFD。
    Alpha 以 UTF-16 單位截斷檔名，可能把表情符號切成一半；Node 寫進 PostgreSQL 時會把落單的半個字元換成 U+FFFD，
    這裡做同樣的事（MySQL 不接受落單的代理字元）。
    """
    return "".join("�" if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in text)


def content_disposition(filename):
    """Alpha：attachment; filename=document; filename*=UTF-8'' + encodeURIComponent(filename).replace(/'/g, '%27')"""
    return "attachment; filename=document; filename*=UTF-8''" + quote(filename, safe="-_.!~*()'").replace("'", "%27")
