"""Dashboard 與 Production Report 一次請求的時間分解（不開 profiler，純計時）。python manage.py shell < stages_dashboard.py；只在壓測環境。"""
import json, os, time
from collections import defaultdict
assert os.environ.get("STRESS_STACK") == "true"

from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.renderers import JSONRenderer

import dashboard.calc as dc
import dashboard.views as dv
import production.calc as pc
import production.views as pv
from cases.calc.jsnum import json_roundtrip
from cases.models import Case
from fxrates.models import FxRate

timers = defaultdict(lambda: [0, 0.0])
from fxrates.models import FxRate as _Fx
for _y, _m in [(2025, 10), (2025, 11), (2025, 12)] + [(2026, i) for i in range(1, 11)]:
    for _cur, _rate in (("USD", 32.1), ("EUR", 35.4), ("JPY", 0.213), ("GBP", 41.2)):
        _Fx.objects.get_or_create(year_month=f"{_y}-{_m:02d}", currency=_cur, defaults={"rate": _rate, "created_by": "stress", "updated_by": "stress"})


def wrap(mod, name, label):
    inner = getattr(mod, name)

    def w(*a, **k):
        t = time.perf_counter()
        try:
            return inner(*a, **k)
        finally:
            timers[label][0] += 1
            timers[label][1] += time.perf_counter() - t
    setattr(mod, name, w)


def show(title, total, rendered_bytes, sql_time, sql_n):
    print(f"\n===== {title}: 總計 {total:.1f} 秒；回應 {rendered_bytes/1024:.0f} KB；SQL {sql_n} 次共 {sql_time:.1f} 秒（含傳輸）")
    for k, (n, s) in timers.items():
        print(f"   {k:46s} {n:7d} 次  {s:5.1f} 秒")
    timers.clear()


# ---------------- Dashboard
wrap(dc, "build_payment_schedule", "build_payment_schedule（未結清金額）")
wrap(dc.production, "installment_allocations", "installment_allocations（每月佣金）")
with CaptureQueriesContext(connection) as q:
    t0 = time.perf_counter()
    t = time.perf_counter()
    cases = Case.objects.filter(recycled_at__isnull=True, is_archived=False).order_by("id")
    rows = [{"id": c.pk, "parent_case_id": c.parent_case_id, "status": c.status, "payload": c.payload,
             "announced_at": dv._taipei_text(c.announced_at), "created_at": dv._taipei_text(c.created_at)} for c in cases]
    timers["讀 1 萬件案件（含 payload）並轉成 dict"] = [len(rows), time.perf_counter() - t]
    t = time.perf_counter()
    targets, fx = [], [{"year_month": f.year_month, "currency": f.currency, "rate": float(f.rate)} for f in FxRate.objects.all()]
    t = time.perf_counter()
    result = dc.build_dashboard(rows, targets, fx, dv._now(), tz=dv.TAIPEI, production_rules=True)
    timers["build_dashboard 全部（含上面兩項）"] = [1, time.perf_counter() - t]
    t = time.perf_counter()
    data = json_roundtrip(result)
    body = JSONRenderer().render(data)
    timers["json_roundtrip + 轉 JSON"] = [1, time.perf_counter() - t]
    total = time.perf_counter() - t0
show("Dashboard", total, len(body), sum(float(x["time"]) for x in q.captured_queries), len(q.captured_queries))
print("   其中 非 posted/closed 的案件（草稿、已沖回）：", sum(1 for r in rows if r["status"] not in ("posted", "closed")), "/", len(rows))

# ---------------- Production Report（2026-09 這個月）
wrap(pv.calc, "reference_links", "reference_links（連結表）")
wrap(pv.calc, "build_production_preview", "build_production_preview（逐案計算）")
wrap(pc, "installment_allocations", "installment_allocations")
month = "2026-09"
with CaptureQueriesContext(connection) as q:
    t0 = time.perf_counter()
    t = time.perf_counter()
    cases = list(pv._live_cases().order_by(pv.F("announced_at").asc(nulls_last=True), pv.F("created_at").asc(nulls_last=True), "id"))
    timers["讀 posted/closed/reversed 案件"] = [len(cases), time.perf_counter() - t]
    t = time.perf_counter()
    sources = [pv.case_source(c) for c in cases]
    timers["case_source"] = [len(sources), time.perf_counter() - t]
    t = time.perf_counter()
    raw_links = list(Case.objects.filter(tw_ref__isnull=False).values_list("tw_ref", "payload").iterator())
    timers["再讀一次「所有有 TW Ref 的案件」的完整 payload"] = [len(raw_links), time.perf_counter() - t]
    t = time.perf_counter()
    links = pv.calc.reference_links(raw_links)
    t = time.perf_counter()
    fx_rates = {month: {r.currency: float(r.rate) for r in _Fx.objects.filter(year_month=month)}}
    preview = pv.calc.build_production_preview(sources, month, fx_rates, [], links)
    t = time.perf_counter()
    summ = pv.summary(preview)
    data = json_roundtrip({"rows": preview["rows"], "excluded": preview["excluded"], "summary": summ})
    body = JSONRenderer().render(data)
    timers["summary + json_roundtrip + 轉 JSON"] = [1, time.perf_counter() - t]
    total = time.perf_counter() - t0
show("Production Report 2026-09", total, len(body), sum(float(x["time"]) for x in q.captured_queries), len(q.captured_queries))
print("   這個月實際的報表列數：", len(preview["rows"]), "；掃過的案件數：", len(cases))
