"""Accounting 與案件明細的回應存檔，用來逐位元組比對「改前」與「改後」的程式（python manage.py shell < dump_responses.py；LABEL=before|after）。
只在壓測環境；檔案寫在 /data/documents（volume，後端容器重建後仍在）。"""
import hashlib, json, os, time
assert os.environ.get("STRESS_STACK") == "true"
from django.contrib.auth import get_user_model
from django.test import Client
from cases.models import Case
label = os.environ.get("LABEL", "run")
c = Client(HTTP_HOST="localhost")
c.force_login(get_user_model().objects.get(username="stress.finmgr"))
t = time.perf_counter()
r = c.get("/api/accounting")
elapsed = time.perf_counter() - t
open(f"/data/documents/accounting_{label}.json", "wb").write(r.content)
print(f"accounting {label}: status {r.status_code}, {len(r.content)} bytes, {elapsed:.1f}s, sha256 {hashlib.sha256(r.content).hexdigest()[:16]}")
uids = [str(u) for u in Case.objects.order_by("id").values_list("case_uid", flat=True)[::17][:600]]   # 約 600 件，涵蓋各狀態
bodies = []
for uid in uids:
    rr = c.get(f"/api/cases?caseUid={uid}")
    bodies.append(rr.content.decode())
blob = "\n".join(bodies).encode()
open(f"/data/documents/cases_{label}.json", "wb").write(blob)
print(f"cases {label}: {len(uids)} responses, {len(blob)} bytes, sha256 {hashlib.sha256(blob).hexdigest()[:16]}")
