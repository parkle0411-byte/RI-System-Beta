#!/usr/bin/env python3
"""壓力測試負載產生器（只用標準函式庫；在壓測環境的網路內執行，打 http://nginx，與使用者的瀏覽器走同一條路）。

  load.py baseline            一個人、逐支 API 各打數次（沒有別人競爭時的基準）
  load.py burst  PATH...      7 人「同一秒」同時打同一支 API，重複數輪（例如週一早上大家同時打開 Accounting）
  load.py mixed  --minutes 5  7 人依角色輪流使用各畫面（案件列表／開案件／Accounting／Dashboard／Production／存檔／記收款…）
  load.py sustained PATH      7 人不停地連續打同一支 API（找出系統撐不撐得住）

回應時間 = 從送出請求到收完整個回應內容（包含 nginx、gunicorn、Django、MySQL；不含瀏覽器解析與畫面繪製）。
"""
import argparse
import http.client
import json
import random
import statistics
import sys
import threading
import time
from http.cookies import SimpleCookie

HOST, PORT = "nginx", 80
SAMPLES = json.load(open("/samples.json"))
PASSWORD = SAMPLES["password"]
RESULTS = []          # (label, status, seconds, bytes, user)
LOCK = threading.Lock()
PAGES = []            # (page, seconds, user)


class Session:
    def __init__(self, username, role):
        self.username, self.role = username, role
        self.cookies, self.conn = {}, None

    def _headers(self, method):
        h = {"Host": "nginx", "Accept": "application/json", "Origin": "http://nginx",
             "Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        if method != "GET":
            h["Content-Type"] = "application/json"
            h["X-CSRFToken"] = self.cookies.get("csrftoken", "")
        return h

    def request(self, method, path, body=None, label=None):
        payload = json.dumps(body).encode() if body is not None else None
        for attempt in (1, 2):
            if self.conn is None:
                self.conn = http.client.HTTPConnection(HOST, PORT, timeout=240)
            start = time.perf_counter()
            try:
                self.conn.request(method, path, body=payload, headers=self._headers(method))
                resp = self.conn.getresponse()
                data = resp.read()
                status = resp.status
                for header in resp.msg.get_all("Set-Cookie") or []:
                    jar = SimpleCookie(header)
                    for k, v in jar.items():
                        self.cookies[k] = v.value
                break
            except (http.client.HTTPException, ConnectionError, OSError) as exc:   # 連線被關掉：重連一次；再失敗就記錄為錯誤
                self.conn = None
                if attempt == 2:
                    status, data = (599 if "timed out" not in str(exc) else 598), b""
        elapsed = time.perf_counter() - start
        with LOCK:
            base, _, query = path.partition("?")
            keys = "&".join(sorted(part.split("=")[0] for part in query.split("&") if part))
            RESULTS.append((label or f"{method} {base}" + (f"?{keys}" if keys else ""), status, elapsed, len(data), self.username))
        return status, data, elapsed

    def login(self):
        self.request("GET", "/api/auth/csrf", label="(login) csrf")
        status, data, _ = self.request("POST", "/api/auth/login", {"username": self.username, "password": PASSWORD}, label="(login) login")
        if status != 200:
            raise SystemExit(f"登入失敗 {self.username}: {status} {data[:200]}")
        return self

    def json(self, method, path, body=None, label=None):
        status, data, elapsed = self.request(method, path, body, label)
        try:
            return status, json.loads(data) if data else {}, elapsed
        except ValueError:
            return status, {}, elapsed


def sessions():
    out = []
    for u in SAMPLES["users"]:
        s = Session(u["username"], u["role"])
        s.login()
        out.append(s)
        time.sleep(0.2)
    RESULTS.clear()
    return out


def percentile(sorted_values, p):
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def report(title, rows=None, pages=None):
    rows = RESULTS if rows is None else rows
    by = {}
    for label, status, secs, size, _ in rows:
        by.setdefault(label, []).append((status, secs, size))
    print(f"\n### {title}")
    print(f"{'請求':44s} {'次數':>5s} {'錯誤':>4s} {'最快':>7s} {'中位':>7s} {'P90':>7s} {'最慢':>7s} {'回應大小':>10s}")
    for label in sorted(by):
        items = by[label]
        times = sorted(s for _, s, _ in items)
        errors = sum(1 for st, _, _ in items if st >= 400)
        size = statistics.mean(sz for _, _, sz in items)
        print(f"{label:44s} {len(items):5d} {errors:4d} {times[0]:7.2f} {percentile(times, .5):7.2f} {percentile(times, .9):7.2f} {times[-1]:7.2f} {size / 1024:8.0f}KB")
    codes = {}
    for _, st, *_ in rows:
        codes[st] = codes.get(st, 0) + 1
    print("狀態碼:", dict(sorted(codes.items())))
    if pages:
        pb = {}
        for page, secs, _ in pages:
            pb.setdefault(page, []).append(secs)
        print(f"\n{'畫面（該畫面所有請求加總）':36s} {'次數':>5s} {'中位':>7s} {'P90':>7s} {'最慢':>7s}")
        for page in sorted(pb):
            t = sorted(pb[page])
            print(f"{page:36s} {len(t):5d} {percentile(t, .5):7.2f} {percentile(t, .9):7.2f} {t[-1]:7.2f}")
    sys.stdout.flush()


# ---------------------------------------------------------------- 場景
def baseline(reps):
    fin = Session("stress.finmgr", "accounting_manager").login()
    sales = Session("stress.sales1", "sales").login()
    gm = Session("stress.gm", "general_manager").login()
    uid = random.choice(SAMPLES["ledger"])
    calls = [(fin, "/api/app-context"), (sales, "/api/cases"), (sales, f"/api/cases?caseUid={uid}"), (sales, f"/api/case-workflow?caseUid={uid}"),
             (sales, f"/api/claims?caseUid={uid}"), (sales, f"/api/case-reminders?caseUid={uid}"), (fin, "/api/accounting"),
             (fin, f"/api/production-report?month={SAMPLES['months'][1]}"), (fin, "/api/dashboard"), (gm, "/api/dashboard-targets"),
             (sales, "/api/master-data"), (sales, "/api/personnel-options")]
    for sess, path in calls:
        sess.request("GET", path)          # 暖機（第一次要把資料讀進記憶體）；結果不計
    RESULTS.clear()
    for _ in range(reps):
        for sess, path in calls:
            sess.request("GET", path)
            time.sleep(0.3)
    report(f"基準：1 個人，每支 API {reps} 次")


def single(paths, reps):
    """一個人，只打指定的幾支 API（每支暖機 1 次，再各 reps 次）。"""
    fin = Session("stress.finmgr", "accounting_manager").login()
    for path in paths:
        fin.request("GET", path)
    RESULTS.clear()
    for _ in range(reps):
        for path in paths:
            fin.request("GET", path)
            time.sleep(0.5)
    report(f"1 個人，每支 API {reps} 次（已暖機）")


def burst(paths, rounds):
    users = sessions()
    for path in paths:
        RESULTS.clear()
        spans = []
        for r in range(rounds):
            barrier = threading.Barrier(len(users))
            times = []

            def go(sess):
                barrier.wait()
                t = time.perf_counter()
                sess.request("GET", path)
                times.append(time.perf_counter() - t)

            threads = [threading.Thread(target=go, args=(s,)) for s in users]
            [t.start() for t in threads]
            [t.join() for t in threads]
            spans.append(sorted(times))
            time.sleep(5)   # 讓系統喘口氣再下一輪
        report(f"7 人同一秒同時打 {path}（{rounds} 輪）")
        for i, t in enumerate(spans, 1):
            print(f"   第{i}輪 7 人各自的等待時間(秒): " + ", ".join(f"{x:.1f}" for x in t))


def make_actions(sess, idx):
    """每個人專用的案件與收款樣本（各人用不同的案件，避免互相造成版本衝突）。"""
    ledger = SAMPLES["ledger"]
    unpaid = SAMPLES["unpaid"][idx::7]
    drafts = SAMPLES["drafts"][idx::7]
    month = SAMPLES["months"]

    def page(name, calls):
        start = time.perf_counter()
        for method, path, body in calls():
            sess.request(method, path, body)
        with LOCK:
            PAGES.append((name, time.perf_counter() - start, sess.username))

    def cases_list():
        page("案件列表", lambda: [("GET", "/api/cases", None)])

    def open_case():
        uid = random.choice(ledger)
        page("開啟案件", lambda: [("GET", f"/api/cases?caseUid={uid}", None), ("GET", f"/api/case-workflow?caseUid={uid}", None)])

    def claims_tab():
        uid = random.choice(ledger)
        page("案件的 Claims 分頁", lambda: [("GET", f"/api/claims?caseUid={uid}", None)])

    def accounting():
        page("Accounting 頁", lambda: [("GET", "/api/accounting", None)])

    def dashboard():
        page("Dashboard", lambda: [("GET", "/api/dashboard", None)] + ([("GET", "/api/dashboard-targets", None)] if sess.role in ("general_manager", "admin") else []))

    def production():
        page("Production Report", lambda: [("GET", f"/api/production-report?month={random.choice(month)}", None)])

    def save_draft():
        if not drafts:
            return cases_list()
        d = random.choice(drafts)
        start = time.perf_counter()
        status, data, _ = sess.json("GET", f"/api/cases?caseUid={d['caseUid']}", label="GET /api/cases?caseUid= (存檔前載入)")
        if status == 200:
            case = data["case"]
            body = dict(case["payload"], remark="stress edit " + str(time.time()))
            status, data, _ = sess.json("PUT", "/api/cases", {"caseUid": d["caseUid"], "rowVersion": case["rowVersion"], "case": body}, label="PUT /api/cases (存檔)")
            if status == 200:
                d["rowVersion"] = data.get("case", {}).get("rowVersion", case["rowVersion"] + 1)
        with LOCK:
            PAGES.append(("編輯並存檔草稿", time.perf_counter() - start, sess.username))

    def record_payment():
        if not unpaid:
            return accounting()
        item = unpaid.pop()
        start = time.perf_counter()
        status, data, _ = sess.json("GET", f"/api/cases?caseUid={item['caseUid']}", label="GET /api/cases?caseUid= (記收款前載入)")
        if status == 200:
            version = data["case"]["rowVersion"]
            status, data, _ = sess.json("POST", "/api/accounting", {
                "action": "record_transaction_payments", "paymentDate": "2026-10-14", "amount": item["amount"], "reference": f"LOAD-{time.time():.0f}",
                "allocations": [{"caseUid": item["caseUid"], "txNo": item["txNo"], "rowVersion": version, "amount": item["amount"]}]},
                label="POST /api/accounting (記收款)")
        with LOCK:
            PAGES.append(("記一筆收款", time.perf_counter() - start, sess.username))

    sales = [(cases_list, 25), (open_case, 30), (dashboard, 10), (accounting, 10), (production, 5), (save_draft, 12), (claims_tab, 8)]
    finance = [(accounting, 38), (open_case, 15), (dashboard, 10), (production, 10), (cases_list, 10), (record_payment, 12), (claims_tab, 5)]
    table = finance if sess.role.startswith("accounting") else sales
    return [a for a, _ in table], [w for _, w in table]


def mixed(minutes, think_lo, think_hi):
    users = sessions()
    stop = time.time() + minutes * 60

    def run(idx, sess):
        actions, weights = make_actions(sess, idx)
        random.seed(idx * 7919 + int(time.time()))
        time.sleep(random.uniform(0, think_hi))
        while time.time() < stop:
            random.choices(actions, weights)[0]()
            time.sleep(random.uniform(think_lo, think_hi))

    threads = [threading.Thread(target=run, args=(i, s)) for i, s in enumerate(users)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    report(f"7 人混合使用 {minutes} 分鐘（每個動作之間停 {think_lo}–{think_hi} 秒）", pages=PAGES)
    print(f"整體: {len(RESULTS)} 個請求 / {minutes} 分鐘")


def sustained(path, seconds):
    users = sessions()
    stop = time.time() + seconds

    def run(sess):
        while time.time() < stop:
            sess.request("GET", path)

    threads = [threading.Thread(target=run, args=(s,)) for s in users]
    [t.start() for t in threads]
    [t.join() for t in threads]
    report(f"7 人連續不停地打 {path}，持續 {seconds} 秒")
    done = [r for r in RESULTS if r[1] == 200]
    print(f"成功完成 {len(done)} 次 → 系統每分鐘最多處理 {len(done) * 60 / seconds:.1f} 次")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=["baseline", "single", "burst", "mixed", "sustained"])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--think", default="5,20")
    ap.add_argument("--seconds", type=int, default=60)
    a = ap.parse_args()
    if a.scenario == "baseline":
        baseline(a.reps)
    elif a.scenario == "single":
        single(a.paths, a.reps)
    elif a.scenario == "burst":
        burst(a.paths or ["/api/accounting"], a.rounds)
    elif a.scenario == "mixed":
        lo, hi = (float(x) for x in a.think.split(","))
        mixed(a.minutes, lo, hi)
    else:
        sustained(a.paths[0], a.seconds)
