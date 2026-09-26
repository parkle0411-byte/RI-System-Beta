"""產生 PDF 的 markup 檢查（api/render-document-pdf.js 的 rejectUnsafeMarkup 與開頭的檢查）的差異測試輸入向量。

特別針對 JavaScript 與 Python 正規式容易不同的地方：
  - \\s：JavaScript 含 U+FEFF、U+00A0、U+1680…；Python 的 str.isspace() 另外含 U+001C–U+001F、U+0085（JavaScript 不含）
  - /i 沒有 u 旗標：JavaScript 不會把 ſ（U+017F）當成 s、K（U+212A）當成 k；Python 的 re.I 預設會
  - \\w、\\b：JavaScript 只看 ASCII
  - markup.length 是 UTF-16 單位：一個 emoji 算 2
"""
from .vectors import R

WS = [" ", "\t", "\n", "\r", "\x0b", "\x0c", "\xa0", " ", " ", " ", " ", " ", " ", " ",
      "　", "﻿", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "​", "᠎", ""]
TAGS = ["script", "SCRIPT", "Script", "iframe", "object", "embed", "link", "base", "scripts", "scriptx", "basefont", "linker",
        "ſcript", "Key", "scrİpt", "ıframe", "object1", "embed_", "base-", "lınk", "img", "div", "p"]
AFTER = [">", " ", "/", "x", "_", "1", "-", "é", "é", "", "\n", "\xa0", ":", "ſ"]
PIECES = [
    "@import", "@IMPORT", "@importx", "@import_", "@import ", "@imp0rt", "@ımport", "@import-",
    "url(", "URL(", "url (", "url\t(", "uri(", "urlx(", "ur l(", "ſurl(",
    "javascript:", "JavaScript :", "javascript :", "javaſcript:", "java script:", "javascript﻿:", "javascript\x1c:",
    "onerror=", "onload =", "on=", "on_x=", "on1=", "onclick =", "onſ=", "onK=", "onErr0r=", "o nerror=",
    "data:image/jpeg;base64,", "data:image/png;base64,", "DATA:image/jpeg;base64,", "data:image/jpeg;base64", "http://a/x.jpg",
    "中文", "晶華保險", "😀", "é", "&amp;", "<", ">", "\"", "'", "=", "src", "SRC", "ſrc", "<img", "<IMG", "<ımg", "<img/",
]


def _img():
    q = R.choice(["'", '"', "`", ""])
    target = R.choice(["data:image/jpeg;base64,/9j/", "data:image/png;base64,iVB", "DATA:IMAGE/JPEG;BASE64,x", "http://x/y.png",
                       "data:image/jpeg;base64", "", " data:image/jpeg;base64,x"])
    attrs = R.choice(["", " alt=x", " class=\"logo\"", " alt='>'", " width=1"])
    return f"<{R.choice(['img', 'IMG', 'Img', 'ımg', 'img2', 'imgx'])}{R.choice(WS)}{attrs}{R.choice(WS)}{R.choice(['src', 'SRC', 'ſrc', 'xsrc', 'data-src'])}{R.choice(WS)}={R.choice(WS)}{q}{target}{q}>"


def _fragment():
    r = R.random()
    if r < 0.25:
        return f"<{R.choice(TAGS)}{R.choice(AFTER)}"
    if r < 0.45:
        return _img()
    if r < 0.6:
        return f"{R.choice(WS)}{R.choice(['on', 'ON', 'On', 'o', 'onn'])}{R.choice(['error', 'load', '', '_', '1', 'ſ', 'é', 'x'])}{R.choice(WS)}{R.choice(['=', ':', ''])}"
    if r < 0.75:
        word = R.choice(["url", "javascript", "@import"])
        return f"{word}{R.choice(WS)}{R.choice(['(', ':', 'x', ''])}"
    return R.choice(PIECES)


def _markup():
    parts = [R.choice(["<div class=\"page\">", "", "<p>", "text "])]
    for _ in range(R.randint(0, 5)):
        parts.append(_fragment())
        if R.random() < 0.5:
            parts.append(R.choice(WS) + R.choice(["x", "hello", "中文", "😀", "", " "]))
    return "".join(parts)


def build(count_each):
    vectors = []
    for _ in range(count_each * 3):
        vectors.append({"fn": "renderPdfRejectUnsafeMarkup", "args": [_markup()]})
    for piece in PIECES + [f"<{t}{a}" for t in TAGS for a in AFTER[:4]]:
        vectors.append({"fn": "renderPdfRejectUnsafeMarkup", "args": [piece]})
    for _ in range(count_each):
        body = R.choice([{"markup": _markup()}, {"markup": R.choice(WS) * R.randint(0, 3)}, {"markup": R.choice(WS) + "x"},
                         {"markup": None}, {"markup": 123}, {"markup": ["<p>"]}, {"markup": {}}, {}, None, "", 0, {"markup": ""},
                         {"markup": True}, {"markup": "<p>ok</p>", "kind": "debit"}])
        vectors.append({"fn": "renderPdfMarkupStatus", "args": [body]})
    # 長度上限在 UTF-16 單位：emoji 算 2（Python 的 len 會算 1）
    for text in ("a" * 1_999_999 + "😀", "a" * 1_999_998 + "😀", "a" * 2_000_000, "a" * 2_000_001, "😀" * 1_000_000, "😀" * 1_000_000 + "a",
                 "<script>" + "a" * 1_999_992, "<script>" + "a" * 1_999_993):
        vectors.append({"fn": "renderPdfMarkupStatus", "args": [{"markup": text}]})
    return vectors
