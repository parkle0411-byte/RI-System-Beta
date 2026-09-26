"""Dashboard（api/dashboard.js 查詢之後的邏輯）差異測試的輸入向量。"""
from datetime import datetime, timedelta, timezone

from .vectors import MISSING, NOW_POINTS, R, maybe_omit
from .production_vectors import coherent_payload


def _shift(now_iso, days):
    t = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) + timedelta(days=days)
    return t


def case_row(i, now_iso):
    now = _shift(now_iso, 0)
    ym = now.strftime("%Y-%m")
    p = coherent_payload(R.choice([ym, (now - timedelta(days=40)).strftime("%Y-%m"), (now - timedelta(days=380)).strftime("%Y-%m")]))
    p["newOrRenew"] = R.choice(["New", "Renew", "Renew", None, "renew"])
    p["policyTo"] = R.choice([(now + timedelta(days=d)).strftime("%Y-%m-%d") for d in (-400, -1, 0, 1, 20, 200)] + [now.strftime("%Y-%m") + "-15", "", None, 20271231])
    p["classOfBusiness"] = R.choice(["Property", "Engineering", "Marine", "", None, "123", "Other", 7])
    if R.random() < 0.3:
        p["postedAt"] = R.choice([(now - timedelta(days=d)).isoformat() for d in (0, 10, 40, 365, 400)] + ["", None])
    if R.random() < 0.3:
        p["endoTypes"] = R.choice([["Extension"], [], None, "x"])
    for r in p["reinsurers"]:   # 名稱多樣化，讓占比圖真的出現「Other」
        if R.random() < 0.7:
            r["name"] = R.choice(["Munich Re", "Swiss Re", "Hannover Re", "SCOR", "Gen Re", "Lloyd's", "Partner Re", "RGA", "Everest Re", "AXA XL"]) + R.choice(["", " (Facility)"])
    if R.random() < 0.2:
        p["reinsurers"].append({"name": R.choice(["Re Z (Facility)", "Re Z [Facility]", "", None]), "sharePct": 10, "premium": 1000})
    announced = R.choice([(now - timedelta(days=d, hours=h)).isoformat().replace("+00:00", R.choice(["+00:00", "Z"]))
                          for d in (0, 0, 3, 35, 200, 370, 400) for h in (0, 7)] + [None, ""])
    row = {"id": i + 1, "parent_case_id": R.choice([None, None, None, 1, 2, 0]), "status": R.choice(["posted", "closed", "draft", "reversed", "posted"]),
           "announced_at": announced, "payload": p if R.random() > 0.03 else R.choice([None, {}])}
    return row


def fx_row(now_iso):
    now = _shift(now_iso, 0)
    ym = R.choice([(now + timedelta(days=d)).strftime("%Y-%m") for d in (-400, -60, -31, 0, 31, 62)])
    r = {"year_month": ym, "currency": R.choice(["USD", "usd", "EUR", "JPY", "", None]), "rate": R.choice([31.5, "30.123456", 0, -1, "abc", 33])}
    return r


def target_row(now_iso):
    now = _shift(now_iso, 0)
    t = R.choice(["annual", "monthly", "monthly", "other"])
    key = str(now.year + R.choice([0, 0, -1])) if t == "annual" else R.choice([(now - timedelta(days=d)).strftime("%Y-%m") for d in (0, 31, 62, 365)])
    return {"period_type": t, "period_key": key, "amount": R.choice([1000000, "250000.50", 0, "abc"])}


def build(count_each=1200):
    vectors = []
    points = NOW_POINTS + ["2026-01-15T03:00:00Z", "2027-01-01T00:30:00Z", "2026-12-31T23:30:00Z"]
    for _ in range(count_each):
        now = R.choice(points)
        cases = [case_row(i, now) for i in range(R.choice([0, 1, 3, 6, 10]))]
        if R.random() < 0.2:   # 業務量大：12 件有效保單（每件 3 家再保人、6 種類別），占比圖會出現「Other」
            for c in cases + [case_row(len(cases) + k, now) for k in range(12)]:
                if isinstance(c.get("payload"), dict):
                    c.update(parent_case_id=None, status=R.choice(["posted", "closed"]))
                    c["payload"]["policyTo"] = _shift(now, 300).strftime("%Y-%m-%d")
                    c["payload"]["classOfBusiness"] = R.choice(["Property", "Engineering", "Marine", "Casualty", "Energy", "Aviation", "Cargo"])
                    if c not in cases:
                        cases.append(c)
        fx = [fx_row(now) for _ in range(R.choice([0, 1, 3, 6]))]
        targets = [target_row(now) for _ in range(R.choice([0, 1, 3, 8]))]
        vectors.append({"fn": "dashboardSummary", "args": [cases, targets, fx], "now": now})
    return vectors
