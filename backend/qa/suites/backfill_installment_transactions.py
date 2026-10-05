import copy
import io
import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case
from personnel.models import Personnel
from production.calc import production_keys_for_case
from production.views import case_source

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass

def person(role, dept):
    return Personnel.objects.create(name=f"ZZ BFI {role}", department=dept, role_code=role, created_by="t", updated_by="t")
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.bfi.{tag}", password="Bfi-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Bfi-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Bfi Cedant", originalInsured="ZZ Bfi Insured", policyFrom="2031-05-01", policyTo="2032-05-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make_case(c, status="posted", **payload_over):
    r = call(c, "post", "/api/cases", {"case": ready()}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()["case"]["caseUid"]); _ref[0] += 1
    p = copy.deepcopy(case.payload); p.update(payload_over)
    Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-BFI-{_ref[0]:04d}", announced_at=timezone.now(), payload=p)
    case.refresh_from_db(); return case
def run(apply=False):
    out = io.StringIO(); call_command("backfill_installment_transactions", *(["--apply"] if apply else []), stdout=out)
    text = out.getvalue(); body = json.loads(text[:text.rindex("}") + 1]); return body, text
def keys_of(case, *installment_ids):
    return [k for k in production_keys_for_case(case_source(case)) if k.split(":")[1] in installment_ids]

INSTALLMENTS = [{"id": "I1", "performanceMonth": "2031-05", "premium": 600}, {"id": "I2", "performanceMonth": "2031-06", "premium": 400}]
try:
    with transaction.atomic():
        sales = account(person("sales", "reinsurance"), "sales")
        # a: 分期，第 1 期已確認但沒有交易（要補）
        a = make_case(sales, installmentEnabled=True, performanceInstallments=INSTALLMENTS)
        Case.objects.filter(pk=a.pk).update(payload={**a.payload, "confirmedProductionKeys": keys_of(a, "I1"), "productionPartiallyConfirmed": True}); a.refresh_from_db()
        # b: 分期，兩期都確認、狀態 closed，但沒有交易（兩期都補）
        b = make_case(sales, status="closed", installmentEnabled=True, performanceInstallments=INSTALLMENTS)
        Case.objects.filter(pk=b.pk).update(payload={**b.payload, "confirmedProductionKeys": keys_of(b, "I1", "I2"), "productionPartiallyConfirmed": False}); b.refresh_from_db()
        # c: 分期，舊的整案全額交易（沒有 installmentId）已涵蓋所有期別 -> 不補
        legacy = [{"txNo": "OLD-R1-TX1", "legType": "Leg 1", "amount": 540, "reinsurerIdx": 0, "settlement": "open"}]
        c = make_case(sales, status="closed", installmentEnabled=True, performanceInstallments=INSTALLMENTS, transactions=legacy)
        Case.objects.filter(pk=c.pk).update(payload={**c.payload, "confirmedProductionKeys": keys_of(c, "I1", "I2")}); c.refresh_from_db()
        # d: 分期，什麼都還沒確認 -> 不補
        d = make_case(sales, installmentEnabled=True, performanceInstallments=INSTALLMENTS)
        # e: 沒有分期 -> 不碰
        e = make_case(sales, status="closed")
        Case.objects.filter(pk=e.pk).update(payload={**e.payload, "confirmedProductionKeys": keys_of(e, "FULL")}); e.refresh_from_db()
        # f: 已 Reverse（待沖銷）-> 不碰
        f = make_case(sales, status="reversed", installmentEnabled=True, performanceInstallments=INSTALLMENTS, pendingReversalOffset=True, reversalCycle=1)
        # g: 第 1 期的交易已經有了（再跑不重複）
        have = [{"txNo": "OLD-R1-TX1-I1", "legType": "Leg 1", "amount": 324, "reinsurerIdx": 0, "settlement": "open", "installmentId": "I1"}]
        g = make_case(sales, installmentEnabled=True, performanceInstallments=INSTALLMENTS, transactions=have)
        Case.objects.filter(pk=g.pk).update(payload={**g.payload, "confirmedProductionKeys": keys_of(g, "I1"), "productionPartiallyConfirmed": True}); g.refresh_from_db()

        mine = {a.pk, b.pk, c.pk, d.pk, e.pk, f.pk, g.pk}
        before_rows = {x.pk: Case.objects.get(pk=x.pk).row_version for x in (a, b, c, d, e, f, g)}
        body, text = run(apply=False)
        planned = {row["caseId"]: row for row in body["cases"] if row["caseId"] in mine}
        check("dry-run lists exactly a (I1) and b (I1+I2)", set(planned) == {a.pk, b.pk}
              and planned[a.pk]["installments"] == ["I1"] and planned[b.pk]["installments"] == ["I1", "I2"], planned)
        check("dry-run wrote nothing", all(Case.objects.get(pk=x.pk).row_version == v for x, v in zip((a, b, c, d, e, f, g), before_rows.values()))
              and not Case.objects.get(pk=a.pk).payload.get("transactions") and "Dry-run" in text)
        check("dry-run counts: 2 reinsurers x 3 legs per installment", planned[a.pk]["newTransactions"] == 6 and planned[b.pk]["newTransactions"] == 12)

        body, text = run(apply=True)
        for x in (a, b, c, d, e, f, g):
            x.refresh_from_db()
        ta, tb = a.payload["transactions"], b.payload["transactions"]
        check("a: I1 transactions added (6, numbered -I1, 60% of each leg), row_version + 1",
              len(ta) == 6 and all(t["installmentId"] == "I1" and t["txNo"] == f"{a.tw_ref}-R{t['reinsurerIdx'] + 1}-TX{n}-I1"
                                   for t in ta for n in [int(t["legType"][-1])]) and a.row_version == before_rows[a.pk] + 1
              and sorted(t["amount"] for t in ta if t["legType"] == "Leg 1") == [216, 324], [(t["txNo"], t["amount"]) for t in ta])
        check("b: both installments added (12), status unchanged, confirmed keys untouched", len(tb) == 12 and b.status == "closed"
              and [t["installmentId"] for t in tb] == ["I1"] * 6 + ["I2"] * 6 and b.payload["confirmedProductionKeys"] == keys_of(b, "I1", "I2"))
        check("c (legacy full-amount transactions), d (nothing confirmed), e (no installments), f (reversed), g (I1 already has transactions) untouched",
              c.payload["transactions"] == legacy and not d.payload.get("transactions") and not e.payload.get("transactions") and not f.payload.get("transactions")
              and g.payload["transactions"] == have and all(x.row_version == before_rows[x.pk] for x in (c, d, e, f, g)))
        check("snapshot + maintenance audit for each changed case", all(
            EntitySnapshot.objects.filter(entity_type="case", entity_id=str(x.case_uid), entity_version=x.row_version, snapshot_reason="production_case_confirmed").exists()
            and AuditLog.objects.filter(entity_type="case", entity_id=str(x.case_uid), action="backfill_installment_transactions", source="maintenance", actor_id="cli").exists()
            for x in (a, b)))
        check("audit keeps before and after", AuditLog.objects.get(entity_type="case", entity_id=str(a.case_uid), action="backfill_installment_transactions").before_data["payload"].get("transactions", []) == []
              and len(AuditLog.objects.get(entity_type="case", entity_id=str(a.case_uid), action="backfill_installment_transactions").after_data["payload"]["transactions"]) == 6)
        rows_after = {x.pk: x.row_version for x in (a, b, g)}
        body, text = run(apply=True)
        for x in (a, b, g):
            x.refresh_from_db()
        check("second run does nothing for our cases (no duplicates)", not [row for row in body["cases"] if row["caseId"] in mine]
              and {x.pk: x.row_version for x in (a, b, g)} == rows_after and len(a.payload["transactions"]) == 6)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, dd in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {dd}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ BFI").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Bfi Insured").count())
