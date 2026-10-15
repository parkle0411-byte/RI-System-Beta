"""Accounting／Dashboard／Production Report 的時間花在哪裡（python manage.py shell < profile.py；只在壓測環境）。"""
import cProfile, io, os, pstats, time
assert os.environ.get("STRESS_STACK") == "true"
from django.contrib.auth import get_user_model
from django.db import connection, reset_queries
from django.test import Client
from django.test.utils import CaptureQueriesContext

c = Client(HTTP_HOST="localhost")
c.force_login(get_user_model().objects.get(username="stress.finmgr"))
for path in ["/api/accounting", "/api/dashboard", "/api/production-report?month=2026-09", "/api/cases"]:
    c.get(path)  # 暖機
    with CaptureQueriesContext(connection) as q:
        pr = cProfile.Profile()
        t = time.perf_counter()
        pr.enable()
        r = c.get(path)
        pr.disable()
        total = time.perf_counter() - t
    db = sum(float(x["time"]) for x in q.captured_queries)
    print(f"\n===== {path}  狀態 {r.status_code}  回應 {len(r.content)/1048576:.1f} MB  總 {total:.1f} 秒（含 profiler 負擔）  SQL {len(q.captured_queries)} 次共 {db:.1f} 秒")
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(14)
    print("\n".join(line[:150] for line in s.getvalue().splitlines() if line.strip())[:2600])
