"""案件文件（api/case-documents.js 的純函式）與 Signed Slip 提醒（lib/signed-slip-reminders.js）的差異測試輸入向量。"""
import base64

from .vectors import DATES_ODD, DATES_VALID, NOW_POINTS, R
from .workflow_vectors import WS_VARIANTS, dates, name_value

FILENAMES = ["a.pdf", "A.PDF", "x.tar.pdf", "noext", "a.", ".pdf", "a.Jpeg", "b.jpg", "c.png", "m.eml", "m.MSG", "d.docx",
             "a.txt", "a.pdf ", "ａ.ｐｄｆ", "a.pdf.exe", "報價單.pdf", "a.PnG", "x.EmL", "..", "", "a.doc", "a.jpeg"]
EMAIL_HEADERS = [b"From: a@b.c\r\n", b"from: a@b.c\n", b"SUBJECT: x\n", b"Received: x\n", b"X-From: x\n", b"Fro m: x\n",
                 b"Message-ID: <x>\n", b"MIME-Version: 1.0\n", b"Return-Path: <a>\n", b"Delivered-To: a\n", b"Date: today\n", b"To: a\n"]


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def _noise(n):
    return bytes(R.randrange(256) for _ in range(n))


def content_for(ext):
    r = R.random()
    tail = _noise(R.randint(0, 60))
    if ext == "pdf":
        return (b"%PDF-1.7\n" if r < 0.7 else R.choice([b"%PDF", b" %PDF-", b"%pdf-", b""])) + tail
    if ext == "png":
        return (bytes([137, 80, 78, 71, 13, 10, 26, 10]) if r < 0.7 else bytes([137, 80, 78, 71, 13, 10, 26])) + tail
    if ext in ("jpg", "jpeg"):
        return (bytes([255, 216, 255]) if r < 0.7 else bytes([255, 216, 254])) + tail
    if ext == "docx":
        head = bytes([80, 75, 3, 4]) if r < 0.8 else bytes([80, 75, 3, 5])
        parts = [b"[Content_Types].xml" if R.random() < 0.8 else b"[content_types].xml", b"word/" if R.random() < 0.8 else b"Word/"]
        R.shuffle(parts)
        return head + tail + parts[0] + _noise(5) + parts[1]
    if ext == "msg":
        return (bytes([208, 207, 17, 224, 161, 177, 26, 225]) if r < 0.7 else bytes([208, 207, 17, 224])) + tail
    # eml：標頭可能在第一行、在 \r 或 \n 之後、前面有空白、超過 8192 個位元組之後
    header = R.choice(EMAIL_HEADERS)
    where = R.random()
    if where < 0.4:
        return header + tail
    if where < 0.7:
        return R.choice([b"x\n", b"x\r", b"x\r\n", b"  ", b"x", b"\n\n"]) + header + tail
    if where < 0.85:
        colon = header.index(b":")
        # 讓標頭的冒號剛好落在第 8191／8192／8193 個位元組（8192 位元組的搜尋範圍的邊界）
        pad = R.choice([8192 - len(header) - 1, 8192 - len(header), 8191, 8193,
                        8191 - colon, 8192 - colon, 8193 - colon])
        return b"a" * (pad - 1) + b"\n" + header
    return _noise(40)


def encoded_value(ext):
    r = R.random()
    if r < 0.72:
        return _b64(content_for(ext if ext else R.choice(["pdf", "png", "eml"])))
    if r < 0.8:
        good = _b64(content_for("pdf"))
        return R.choice([good + "\n", " " + good, good[:-1], good.replace("+", "-").replace("/", "_"), good + "=", good.rstrip("=")])
    return R.choice(["", "YQ", "YQ=", "YQ==", "YWI=", "YWJj", "====", "abc", "ab=c", "JVBERi0=", "JVBERi0", None, 5, [], {}, True, "ＡＢＣＤ", "JVBE Ri0="])


def file_row(i, names):
    return {"id": f"f-{i}", "kind": R.choice(["offer", "signed", "confirmation", "other", "Signed"]),
            "reinsurers": R.choice([[R.choice(names) for _ in range(R.randint(0, 3))], [], None, "x"]),
            "is_selected": R.choice([True, True, True, False, 1, 0, None, "x", ""])}


def slip_case():
    d = {}
    if R.random() < 0.9:
        d["status"] = R.choice(["posted", "closed", "draft", "reversed", "Posted", None])
    if R.random() < 0.9:
        d["policyFrom"] = R.choice([dates(), "2026-01-01", "2026-06-01", "2026-07-27", "2026-07-26", "", None])
    if R.random() < 0.9:
        d["reinsurers"] = R.choice([[{"name": name_value()} for _ in range(R.randint(0, 4))], [{"name": "Munich Re"}, {"name": "swiss re"}], None, "x"])
    return d


def files_for(case):
    names = ["munich re", "Munich  Re", "SWISS RE", "swiss re (facility)", " AIG ", "x"]
    rows = case.get("reinsurers") if isinstance(case, dict) else None
    if isinstance(rows, list):
        names += [r["name"] for r in rows if isinstance(r, dict) and isinstance(r.get("name"), str)]
    return [R.choice([file_row(i, names), {"kind": "signed", "reinsurers": [R.choice(names)]}, None, "x", {}]) for i in range(R.randint(0, 5))]


TODAYS = ["2026-09-25", "2026-03-01", "2026-03-02", "2026-08-31", "2026-09-24", "2027-01-01", "2026-09-25x", "", None, ["2026-09-25"], 20260925]
EMAILS = ["a@example.com", "a@EXAMPLE.COM", "a@foo.example.com", "a@example.co", "a@notexample.com", "a@b.test", "a@test", "a@localhost",
          "a@x.localhost", "a@localhost.com", "a@invalid", "a@b.invalid", "a@example", "a@x.example", " A@Example.Org ", "a@b@example.com",
          "example.com", "", None, 5, "a@example.net.", "a@exaİmple.com", "a@Kexample.com", "A@EXAMPLE.ΣΣ", "a@Ex ample.com"]


def build(count_each):
    n = max(count_each // 2, 1)
    out = []
    add = out.append
    for _ in range(n):
        add({"fn": "documentsReinsurerKey", "args": [name_value()]})
        add({"fn": "slipReinsurerKey", "args": [name_value()]})
    for _ in range(n):
        case = slip_case()
        add({"fn": "documentsRequiredReinsurers", "args": [case]})
        add({"fn": "slipRequiredReinsurers", "args": [case]})
    for _ in range(n * 2):
        case = slip_case()
        names = ["munich re", "Munich  Re", "swiss re (facility)", "x"]
        add({"fn": "documentsCoverageFor", "args": [case, [file_row(i, names) for i in range(R.randint(0, 6))]]})
    for _ in range(n):
        base = R.choice(["報價單" * 30 + "😀.pdf", "a/b\\c\x00d\x1f\x7fe.pdf", "x" * 179 + "😀", "x" * 178 + "😀", "\t name.pdf ", "a b.pdf"])
        add({"fn": "safeFilename", "args": [R.choice([base, base + ".pdf", None, 0, 5, True, [], {}, ["a/b"], ""])]})
    for _ in range(n * 3):
        filename = R.choice(FILENAMES)
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        add({"fn": "decodeAndValidate", "args": [filename, encoded_value(ext)]})
    for _ in range(n):
        add({"fn": "slipDateUtc", "args": [dates()]})
        add({"fn": "slipAddDays", "args": [dates(), R.choice([7, 60, 0, -1, -60, 365, 0.5, -0.5, 1e8, 1e9])]})
        add({"fn": "slipDaysBetween", "args": [dates(), dates()]})
    for _ in range(max(n // 2, 1)):
        add({"fn": "slipTaipeiToday", "args": [], "now": R.choice(NOW_POINTS)})
    for _ in range(n * 2):
        case = R.choice([slip_case(), slip_case(), None, {}, "x"])
        args = [case, files_for(case), R.choice([None, "", "2026-09-01", "2026-09-18", "2026-09-19", "bad", dates()]), R.choice(TODAYS)]
        add({"fn": "slipReminderDue", "args": args})
        add({"fn": "slipMissingSignedReinsurers", "args": args[:2]})
    for _ in range(n * 2):
        case = R.choice([slip_case(), slip_case(), {}])
        if R.random() < 0.8:
            add({"fn": "slipSignedSlipTracking", "args": [case, files_for(case), R.choice(TODAYS)]})
        else:
            add({"fn": "slipSignedSlipTracking", "args": [case, files_for(case)], "now": R.choice(NOW_POINTS)})
    for _ in range(n):
        email = R.choice(EMAILS)
        if isinstance(email, str) and R.random() < 0.2:
            email = R.choice(WS_VARIANTS) + email + R.choice(WS_VARIANTS)
        add({"fn": "slipIsReservedTestEmail", "args": [email]})
    return out


__all__ = ["build", "DATES_ODD", "DATES_VALID"]
