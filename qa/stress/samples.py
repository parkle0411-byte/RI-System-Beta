"""負載產生器用的範例清單（從資料庫現況產生，寫到 /tmp/stress_samples.json；python manage.py shell < samples.py）。"""
import json, os, random
assert os.environ.get("STRESS_STACK") == "true"
from cases.models import Case
random.seed(7)
closed = list(Case.objects.filter(status="closed").order_by("?").only("case_uid", "payload", "currency")[:2500])
posted = [str(u) for u in Case.objects.filter(status="posted").values_list("case_uid", flat=True)[:300]]
unpaid = []
for c in closed:
    legs = [t for t in c.payload.get("transactions", []) if t.get("legType") == "Leg 1"]
    if legs and not c.payload.get("paymentEntries"):
        unpaid.append({"caseUid": str(c.case_uid), "txNo": legs[0]["txNo"], "amount": abs(legs[0]["amount"]), "currency": c.currency})
drafts = [{"caseUid": str(u), "rowVersion": v} for u, v in Case.objects.filter(status="draft").values_list("case_uid", "row_version")[:600]]
roles = [("sales1", "sales"), ("sales2", "sales"), ("sales3", "sales"), ("gm", "general_manager"), ("fin1", "accounting"), ("fin2", "accounting"), ("finmgr", "accounting_manager")]
samples = {"password": "Stress-Load-Test-9!", "users": [{"username": "stress." + n, "role": r} for n, r in roles],
           "ledger": [str(c.case_uid) for c in closed[:800]] + posted[:200], "unpaid": unpaid[:600], "drafts": drafts,
           "months": ["2026-10", "2026-09", "2026-08"]}
json.dump(samples, open("/tmp/stress_samples.json", "w"))
print("samples:", {k: len(v) for k, v in samples.items() if isinstance(v, list)})
