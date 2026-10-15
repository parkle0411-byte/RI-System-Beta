"""Accounting GET 的時間分解（不開 profiler，純計時）。python manage.py shell < stages.py；只在壓測環境。
照 cases/accounting_views.py AccountingView.get 的流程，逐段計時；另外量 build_payment_schedule 被呼叫幾次、花多久，
以及回應裡哪些欄位最佔空間、gzip 能壓多小。"""
import json, os, time, zlib
from collections import Counter, defaultdict
assert os.environ.get("STRESS_STACK") == "true"

import cases.accounting_views as av
import cases.cash_ledger as cl
import cases.facility_accounting as fa
import cases.ledger as lg
import cases.calc.payment_terms as pt
from cases.calc.jsnum import json_roundtrip, js_locale_key, js_to_string
from cases.models import Case
from cases.cash_ledger import payment_batches
from cases.reference_views import schedule_reference_metadata
from cases.transaction_ledger import transaction_rows
from rest_framework.renderers import JSONRenderer

calls = {"n": 0, "t": 0.0}
orig = pt.build_payment_schedule


def timed(*a, **k):
    t = time.perf_counter()
    try:
        return orig(*a, **k)
    finally:
        calls["n"] += 1
        calls["t"] += time.perf_counter() - t


for mod in (av, cl, fa, lg):          # 這些模組各自 import 了一份，逐一替換成計時版
    if hasattr(mod, "build_payment_schedule"):
        mod.build_payment_schedule = timed

import cases.transaction_ledger as tl
sub = defaultdict(lambda: [0, 0.0])


def wrap(mod, name, label):
    inner = getattr(mod, name)

    def w(*a, **k):
        t0 = time.perf_counter()
        try:
            return inner(*a, **k)
        finally:
            sub[label][0] += 1
            sub[label][1] += time.perf_counter() - t0
    setattr(mod, name, w)


wrap(tl, "transaction_details", "transaction_details（含下面兩項）")
wrap(fa, "apply_transactions", "  └ apply_transactions（人工結清判斷）")
wrap(cl, "transaction_details", "ledger_rows 內再呼叫 transaction_details（有收款的案件）")
stage = defaultdict(float)


def tick(name, since):
    stage[name] += time.perf_counter() - since
    return time.perf_counter()


T0 = time.perf_counter()
t = time.perf_counter()
cases = list(av._live(Case.objects.filter(status__in=(*av.LEDGER_STATUSES, "reversed"))).select_related("parent_case").order_by("tw_ref", "id"))
t = tick("1 讀資料庫（含 payload 欄位）", t)
rows, transactions, swiss_rows, case_views = [], [], [], []
for case in cases:
    t = time.perf_counter()
    c = av._case_view(case)
    t = tick("2 case_payload（整份 payload deepcopy）", t)
    case_rows, w = lg.ledger_rows([c]) if c["status"] in av.LEDGER_STATUSES else ([], [])
    t = tick("3 ledger_rows（付款排程列）", t)
    for item in case_rows:
        if item.get("source") == "premium":
            item.update(schedule_reference_metadata(c["payload"], item))
    t = tick("4 排程列補對帳編號", t)
    ctx = transaction_rows([c])
    t = tick("5 transaction_rows（SoA 交易列）", t)
    case_views.append(c); rows.extend(case_rows); transactions.extend(ctx)
t = time.perf_counter()
rows.sort(key=lambda r: (js_locale_key(r["twRef"]), js_locale_key(av._text(r.get("dueDate")))))
t = tick("6 排序", t)
batches = payment_batches(case_views)
t = tick("7 收款批次", t)
data = {"ok": True, "rows": rows, "transactionRows": transactions, "warnings": [], "currencies": [], "scope": {"canEdit": True}, "cashBatches": batches, "swissRows": swiss_rows}
data = json_roundtrip(data)
t = tick("8 json_roundtrip（整份回應再複製一次）", t)
body = JSONRenderer().render(data)
t = tick("9 轉成 JSON 文字（DRF）", t)
total = time.perf_counter() - T0
print(f"\n總計 {total:.1f} 秒；回應 {len(body)/1048576:.1f} MB；{len(cases)} 件案件")
for k in sorted(stage):
    print(f"  {k:44s} {stage[k]:6.1f} 秒  {stage[k]/total*100:4.0f}%")
for k, (n, sec) in sub.items():
    print(f"  {k:60s} {n:6d} 次 {sec:5.1f} 秒")
print(f"\nbuild_payment_schedule 被呼叫 {calls['n']} 次（{calls['n']/len(cases):.1f} 次／案件），合計 {calls['t']:.1f} 秒（含在上面各段裡）")

# 回應裡哪些欄位最佔空間
def size_by_key(rows_):
    c = Counter()
    for r in rows_:
        for k, v in r.items():
            c[k] += len(json.dumps(v, ensure_ascii=False, default=str)) + len(k) + 4
    return c
for name, rs in (("transactionRows", transactions), ("rows（付款排程）", rows)):
    c = size_by_key(rs)
    tot = sum(c.values())
    print(f"\n{name}: {len(rs)} 列，{tot/1048576:.1f} MB；最大的欄位：")
    for k, v in c.most_common(8):
        print(f"   {k:28s} {v/1048576:5.1f} MB  {v/tot*100:4.0f}%")
t = time.perf_counter()
gz = zlib.compress(body, 4)
print(f"\ngzip(level 4): {len(body)/1048576:.1f} MB → {len(gz)/1048576:.1f} MB（{len(gz)/len(body)*100:.0f}%），壓縮 {time.perf_counter()-t:.1f} 秒")
