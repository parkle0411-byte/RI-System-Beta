import copy
import json
import uuid
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog, EntitySnapshot
from cases.calc.jsnum import money
from cases.models import Case
from fxrates.models import FxRate
from dashboard.models import DashboardTarget
from production import calc as production
from zoneinfo import ZoneInfo
from datetime import timedelta
from django.db import IntegrityError, DatabaseError
from datetime import datetime, timezone as tz
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=kw.pop("name", f"ZZ DSH {role} {_seq[0]}"), department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.dsh.{tag}", password="Dsh-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Dsh-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Dsh Cedant", originalInsured="ZZ Dsh Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0), dict(name="ZZ Re B (Facility)", sharePct=40, premium=400, riCommPct=5, taxPct=0)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make_case(c, status="posted", **over):
    r = call(c, "post", "/api/cases", {"case": ready(**over)}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
    if status != "draft":
        _ref[0] += 1
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-DSH-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case
TAIPEI = ZoneInfo("Asia/Taipei")
def patch(case, **fields):
    p = copy.deepcopy(Case.objects.get(pk=case.pk).payload); p.update(fields)
    Case.objects.filter(pk=case.pk).update(payload=p); case.refresh_from_db(); return case
def audit(uid, action=None, et="dashboard_target"):
    q = AuditLog.objects.filter(entity_type=et, entity_id=str(uid)); return q.filter(action=action) if action else q
def snaps(uid, reason=None, et="dashboard_target"):
    q = EntitySnapshot.objects.filter(entity_type=et, entity_id=str(uid)); return q.filter(snapshot_reason=reason) if reason else q
def denied_write(fn):
    try:
        with transaction.atomic(): fn()
        return False
    except (DatabaseError, IntegrityError):
        return True
T = "/api/dashboard-targets"

try:
    with transaction.atomic():
        admin_p, sales_p, gm_p, view_p, fin_p = person("admin", "admin"), person("sales", "reinsurance"), person("general_manager", "reinsurance"), person("viewer", "business_1"), person("accounting", "finance")
        admin, sales, gm, viewer, fin = account(admin_p, "admin"), account(sales_p, "sales"), account(gm_p, "gm"), account(view_p, "view"), account(fin_p, "fin")

        # ================= 權限 =================
        check("anonymous -> 401", call(new_client(), "get", "/api/dashboard").status_code == 401)
        check("finance staff has no dashboard.read -> 403", call(fin, "get", "/api/dashboard").status_code == 403)
        check("admin, sales, GM, viewer can read the dashboard", all(call(c, "get", "/api/dashboard").status_code == 200 for c in (admin, sales, gm, viewer)))
        check("targets: sales and finance cannot read (403); admin and GM can", call(sales, "get", T).status_code == 403 and call(fin, "get", T).status_code == 403
              and call(admin, "get", T).status_code == 200 and call(gm, "get", T).status_code == 200)
        check("targets: GM can write; viewer cannot", call(viewer, "post", T, {"periodType": "annual", "periodKey": "2031", "amount": 1}).status_code == 403)

        # ================= Dashboard：只看自己的案件（Case Viewer） =================
        now_tpe = timezone.now().astimezone(TAIPEI)
        ym = now_tpe.strftime("%Y-%m"); year = now_tpe.year
        month_start_tpe = now_tpe.replace(day=1, hour=0, minute=30, second=0, microsecond=0)   # 台北時間本月 1 日 00:30（UTC 是上個月）
        future = (now_tpe + timedelta(days=200)).strftime("%Y-%m-%d")
        def mk(status="posted", owner=view_p, **over):
            c = make_case(sales, "draft" if status == "draft" else status, currency="TWD", policyFrom=f"{ym}-01", policyTo=future, **over)
            Case.objects.filter(pk=c.pk).update(owner_personnel_id=owner.pk, **({"announced_at": month_start_tpe} if status != "draft" else {}))
            c.refresh_from_db(); return c
        c_own = mk(newOrRenew="New")                                        # 本月新件（台北時間月初 00:30 Announce）
        c_split = mk(owner=sales_p); patch(c_split, splitEnabled=True, splitParties=[{"personnelId": str(view_p.pk), "name": view_p.name, "pct": 100}])
        c_split_n = mk(owner=sales_p); patch(c_split_n, splitEnabled=True, splitParties=[{"personnelId": view_p.pk, "name": view_p.name, "pct": 100}])
        c_other = mk(owner=sales_p)                                         # 看不到
        c_draft = mk("draft")                                               # Open quote
        c_inst = mk(); patch(c_inst, installmentEnabled=True, performanceInstallments=[
            {"id": "I1", "performanceMonth": ym, "premium": 333.33}, {"id": "I2", "performanceMonth": "2099-01", "premium": 666.67}])
        patch(c_own, reinsurers=[{"name": "ZZ Re A [Facility]", "sharePct": 60, "premium": 600, "riCommPct": 5, "taxPct": 0},
                                 {"name": "ZZ Re B (Facility)", "sharePct": 40, "premium": 400, "riCommPct": 5, "taxPct": 0}])
        j = call(viewer, "get", "/api/dashboard").json(); m = j["metrics"]
        check("period uses Taipei time", j["period"] == {"year": year, "currentMonth": ym, "monthNumber": now_tpe.month}, j["period"])
        check("viewer sees own + split cases (personnelId as text or number), not others'", m["inForcePolicies"] == 4 and m["openQuotes"] == 1, m)
        check("VM (Taipei month): announced on the 1st 00:30 Taipei counts as this month's new business", m["newBusinessMtd"] == 4 and m["ytdCurrent"] == 4, m)
        # 每月佣金：用 Production 的規則（分期逐期進位，尾差在第一期）
        expected = 0.0
        for c in (c_own, c_split, c_split_n, c_inst):
            c.refresh_from_db()
            for inst in production.installment_allocations({**c.payload, "announcedAt": month_start_tpe.isoformat()}):
                if inst["performanceMonth"] == ym:
                    expected += inst["income"]
        got = j["brokerage"]["current"][now_tpe.month - 1]
        check("this month's brokerage = Production installment income (VM rule)", abs(got - expected) < 1e-9, (got, expected))
        names = [r["name"] for r in j["reinsurers"]]
        check("VM: reinsurer mix strips both (Facility) and [Facility]", "ZZ Re A" in names and "ZZ Re B" in names and not any("Facility" in n for n in names), names)
        check("class mix present", j["classMix"] and j["classMix"][0]["name"] == "ZZ Class", j["classMix"])
        check("admin sees at least the viewer's cases plus the other one", call(admin, "get", "/api/dashboard").json()["metrics"]["inForcePolicies"] >= 5)
        check("no-store", call(viewer, "get", "/api/dashboard")["Cache-Control"] == "no-store, max-age=0")
        from unittest import mock
        with mock.patch("dashboard.views._now", return_value=datetime(2026, 9, 30, 17, 0, tzinfo=tz.utc)):   # 台北 10/1 01:00
            per = call(viewer, "get", "/api/dashboard").json()["period"]
        check("VM: at 2026-09-30 17:00 UTC the dashboard is already October (Taipei)", per == {"year": 2026, "currentMonth": "2026-10", "monthNumber": 10}, per)

        # ================= 目標 =================
        r = call(admin, "post", T, {"periodType": "annual", "periodKey": str(year), "amount": 1234567.895})
        t1 = r.json().get("target", {})
        check("create annual target -> 201, amount rounded to cents", r.status_code == 201 and t1.get("periodKey") == str(year) and t1.get("amount") == 1234567.9
              and t1.get("isActive") is True and t1.get("rowVersion") == 1, r.content[:200])
        check("create: snapshot dashboard_target_created + audit create_dashboard_target", snaps(t1["id"], "dashboard_target_created").exists()
              and audit(t1["id"], "create_dashboard_target").first().metadata["dashboardConsumption"] is True)
        r = call(gm, "post", T, {"periodType": "monthly", "periodKey": ym, "amount": 5000}); t2 = r.json().get("target", {})
        check("GM creates a monthly target", r.status_code == 201)
        j = call(viewer, "get", "/api/dashboard").json()
        check("dashboard uses the annual and monthly targets", j["brokerage"]["annualTarget"] == 1234567.9 and j["brokerage"]["target"][now_tpe.month - 1] == 5000, j["brokerage"])
        r = call(admin, "post", T, {"periodType": "annual", "periodKey": str(year), "amount": 1}); check("duplicate period -> 409 duplicate_target", code(r) == "duplicate_target")
        for label, body, want in (("year '31'", {"periodType": "annual", "periodKey": "31", "amount": 1}, "invalid_period"),
                                  ("month 2031-13", {"periodType": "monthly", "periodKey": "2031-13", "amount": 1}, "invalid_period"),
                                  ("type weekly", {"periodType": "weekly", "periodKey": "2031", "amount": 1}, "invalid_period"),
                                  ("negative amount", {"periodType": "annual", "periodKey": "2032", "amount": -1}, "invalid_amount"),
                                  ("text amount", {"periodType": "annual", "periodKey": "2032", "amount": "abc"}, "invalid_amount"),
                                  ("missing amount", {"periodType": "annual", "periodKey": "2032"}, "invalid_amount")):
            r = call(admin, "post", T, body); check(f"create: {label} -> 400 {want}", r.status_code == 400 and code(r) == want, (r.status_code, code(r)))
        r = call(admin, "post", T, {"periodType": "annual", "periodKey": "2033", "amount": 1000.125, "isActive": False}); t3 = DashboardTarget.objects.get(pk=r.json()["target"]["id"])
        check("amount 1000.125 -> 1000.13 (Math.round with EPSILON, not banker's rounding)", r.json()["target"]["amount"] == 1000.13, r.json()["target"]["amount"])
        check("create inactive -> deactivated_by/at set", t3.is_active is False and t3.deactivated_by and t3.deactivated_at)
        r = call(admin, "put", T, {"periodType": "annual", "periodKey": str(year), "amount": 1}); check("PUT without id/rowVersion -> 400 version_required", code(r) == "version_required")
        r = call(admin, "put", T, {"id": 99999999, "rowVersion": 1, "periodType": "annual", "periodKey": str(year), "amount": 1}); check("PUT unknown id -> 404", code(r) == "target_not_found")
        r = call(admin, "put", T, {**t1, "rowVersion": 5, "amount": 1}); check("PUT stale -> 409 version_conflict with currentRowVersion", code(r) == "version_conflict" and r.json()["currentRowVersion"] == 1)
        r = call(admin, "put", T, {**t1, "periodKey": str(year + 1)}); check("PUT period change -> 400 period_immutable", code(r) == "period_immutable")
        r = call(admin, "put", T, {**t1, "amount": 2000000}); u = r.json().get("target", {})
        check("PUT amount -> version 2, audit update_dashboard_target with before, snapshot dashboard_target_updated", u.get("amount") == 2000000 and u.get("rowVersion") == 2
              and audit(t1["id"], "update_dashboard_target").first().before_data["amount"] == 1234567.9 and snaps(t1["id"], "dashboard_target_updated").filter(entity_version=2).exists())
        r = call(admin, "put", T, {**u, "isActive": False}); d = DashboardTarget.objects.get(pk=t1["id"])
        check("deactivate -> action/reason deactivate_dashboard_target, deactivated fields", r.status_code == 200 and not d.is_active and d.deactivated_by
              and audit(t1["id"], "deactivate_dashboard_target").exists() and snaps(t1["id"], "deactivate_dashboard_target").exists())
        check("an inactive annual target is not used by the dashboard", call(viewer, "get", "/api/dashboard").json()["brokerage"]["annualTarget"] is None)
        r = call(admin, "put", T, {**r.json()["target"], "isActive": True}); d.refresh_from_db()
        check("reactivate -> deactivated fields cleared, audit reactivate_dashboard_target", d.is_active and d.deactivated_by is None and d.deactivated_at is None
              and audit(t1["id"], "reactivate_dashboard_target").exists())
        lst = call(gm, "get", T).json()
        mine_t = [t for t in lst["targets"] if t["id"] in (t1["id"], t2["id"], t3.pk)]
        check("list: newest period first, scope.dashboardConsumption true (VM)", [t["periodKey"] for t in mine_t] == sorted([t["periodKey"] for t in mine_t], reverse=True)
              and lst["scope"] == {"dashboardConsumption": True})
        check("DB: ri_runtime cannot DELETE a target", denied_write(lambda: DashboardTarget.objects.filter(pk=t3.pk).delete()))
        check("DB: amount cannot be negative", denied_write(lambda: DashboardTarget.objects.filter(pk=t3.pk).update(amount=-1)))
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Dsh Insured").count(),
      "| targets =", DashboardTarget.objects.count())
