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
from production.models import ProductionExclusion, ProductionReport
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
    return Personnel.objects.create(name=kw.pop("name", f"ZZ PRD {role} {_seq[0]}"), department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.prd.{tag}", password="Prd-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Prd-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Prd Cedant", originalInsured="ZZ Prd Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
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
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=f"ZZ-PRD-{_ref[0]:04d}", announced_at=timezone.now())
    case.refresh_from_db(); return case
URL = "/api/production-report"
M1, M2, M3, M4 = "2031-05", "2031-06", "2031-07", "2031-08"   # 遠在未來的月份：真實案件不會落在這裡
def get(c, month): return call(c, "get", f"{URL}?month={month}")
def post(c, action, month, **extra): return call(c, "post", URL, {"action": action, "month": month, **extra})
def mine(rows, *cases): return [r for r in rows if r["caseUid"] in {str(x.case_uid) for x in cases}]
def patch(case, **fields):
    p = copy.deepcopy(Case.objects.get(pk=case.pk).payload); p.update(fields)
    Case.objects.filter(pk=case.pk).update(payload=p); case.refresh_from_db(); return case
def at(case, when, status=None):
    Case.objects.filter(pk=case.pk).update(announced_at=when, **({"status": status} if status else {})); case.refresh_from_db(); return case
def audit(uid, action=None, et="case"):
    q = AuditLog.objects.filter(entity_type=et, entity_id=str(uid)); return q.filter(action=action) if action else q
def snaps(uid, reason=None, et="case"):
    q = EntitySnapshot.objects.filter(entity_type=et, entity_id=str(uid)); return q.filter(snapshot_reason=reason) if reason else q
def fx(month, currency, rate):
    return FxRate.objects.create(year_month=month, currency=currency, rate=rate, created_by="t", updated_by="t")
def denied_write(fn):
    try:
        with transaction.atomic(): fn()
        return False
    except (DatabaseError, IntegrityError):
        return True
EARLY = datetime(2026, 9, 1, 4, 0, tzinfo=tz.utc)

try:
    with transaction.atomic():
        admin_p, sales_p, gm_p, view_p = person("admin", "admin"), person("sales", "reinsurance"), person("general_manager", "reinsurance"), person("viewer", "business_1")
        fin_p, finm_p = person("accounting", "finance"), person("accounting_manager", "finance")
        admin, sales, gm, viewer, fin, finm = (account(admin_p, "admin"), account(sales_p, "sales"), account(gm_p, "gm"), account(view_p, "view"),
                                               account(fin_p, "fin"), account(finm_p, "finm"))

        # ================= 權限與月份 =================
        check("viewer: no production.read -> 403", get(viewer, M1).status_code == 403)
        check("anonymous -> 401", call(new_client(), "get", f"{URL}?month={M1}").status_code == 401)
        for bad in ("2031-13", "2031-5", "", "abc", "2031-05x"):
            r = get(fin, bad); check(f"GET month {bad!r} -> 400 invalid_month", r.status_code == 400 and code(r) == "invalid_month")
        r = call(fin, "get", URL); check("GET without month -> 400", code(r) == "invalid_month")
        r = post(fin, "generate", " 2031-05 ", sourceSignature="x"); check("POST month is trimmed (' 2031-05 ' accepted)", code(r) != "invalid_month", code(r))
        r = post(fin, "settle", M1); check("unknown action -> 400 unsupported_action", r.status_code == 400 and code(r) == "unsupported_action")
        sc = {name: get(c, M1).json()["scope"] for name, c in (("gm", gm), ("sales", sales), ("fin", fin), ("finm", finm), ("admin", admin))}
        check("scope: GM and sales can read but not operate", not sc["gm"]["canOperate"] and not sc["sales"]["canOperate"] and not sc["gm"]["canClose"])
        check("scope: Finance Staff operates but cannot close; Finance Manager and Admin can close", sc["fin"]["canOperate"] and not sc["fin"]["canClose"]
              and sc["finm"]["canOperate"] and sc["finm"]["canClose"] and sc["admin"]["canClose"])

        # ================= 案件 =================
        c1 = at(make_case(sales, "posted", policyFrom="2031-05-10", policyTo="2032-05-10"), EARLY)                  # USD，兩家再保人
        c2 = at(make_case(sales, "posted", policyFrom="2031-05-01", policyTo="2032-05-01", currency="TWD"), EARLY)  # TWD，分績兩人
        patch(c2, splitEnabled=True, splitParties=[{"name": "ZZ A", "pct": 50}, {"name": "ZZ B", "pct": 50}], originalPremium=1001)
        c3 = at(make_case(sales, "posted", policyFrom="2031-05-01", policyTo="2032-05-01"), EARLY)                  # 分期：5 月、6 月
        patch(c3, installmentEnabled=True, performanceInstallments=[
            {"id": "I1", "performanceMonth": M1, "premium": 600}, {"id": "I2", "performanceMonth": M2, "premium": 400}])
        c4 = at(make_case(sales, "reversed", policyFrom="2031-05-01", policyTo="2032-05-01"), EARLY)                # Reverse 過：待沖銷
        patch(c4, reversalCycle=1, pendingReversalOffset=True, transactions=[
            {"txNo": "ZZ-OLD-R1-TX1", "amount": 100, "legType": "Leg 1", "reversed": True, "settlement": "settled"},
            {"txNo": "ZZ-OLD-R1-TX2", "amount": 90, "legType": "Leg 2", "reversed": True, "reversalOffsetApplied": True}])
        c5 = make_case(sales, "draft", policyFrom="2031-05-01", policyTo="2032-05-01")                                                     # Draft 不列入
        c9 = at(make_case(sales, "posted", policyFrom="2031-05-01", policyTo="2032-05-01", currency="TWD"), EARLY)   # 整案排除用
        c6 = at(make_case(sales, "posted", policyFrom="2031-05-01", policyTo="2032-05-01"),                         # 台北 6/1 01:00 Announce
                datetime(2031, 5, 31, 17, 0, tzinfo=tz.utc))

        j = get(fin, M1).json(); rows = mine(j["rows"], c1, c2, c3, c4, c5, c6)
        by = lambda case: [r for r in rows if r["caseUid"] == str(case.case_uid)]
        check("Draft case is not in the preview", by(c5) == [])
        check("VM (Taipei month): announced 2031-05-31 17:00 UTC = 06-01 Taipei -> not in May", by(c6) == [], [r["id"] for r in by(c6)])
        check("... but in June", len(mine(get(fin, M2).json()["rows"], c6)) == 2)
        check("USD without a May rate: missingRateCurrencies, rows have null NTD amounts, cannot generate",
              "USD" in j["summary"]["missingRateCurrencies"]
              and all(r["premium"] is None and r["missingRate"] for r in by(c1)) and j["scope"]["canGenerate"] is False, j["summary"])
        r = post(fin, "generate", M1, sourceSignature=j["sourceSignature"])
        check("generate without the FX rate -> 400 fx_rate_required with currencies", r.status_code == 400 and code(r) == "fx_rate_required" and "USD" in r.json()["currencies"])
        fx(M1, "USD", "31.5")
        j = get(fin, M1).json(); rows = mine(j["rows"], c1, c2, c3, c4, c6)
        r1 = by(c1)
        check("c1: one row per reinsurer (single A/E)", [r["id"].split(":", 1)[1] for r in r1] == ["FULL:R0:P0", "FULL:R1:P0"], [r["id"] for r in r1])
        check("c1 figures in NTD at 31.5 (premium 600/400 -> 18900/12600; income 198/208 -> 6237/6552)",
              [(r["premium"], r["income"]) for r in r1] == [(18900, 6237), (12600, 6552)], [(r["premium"], r["income"]) for r in r1])
        check("c1 row fields: rate, currency, comm, policyNo, remark, tranxDate, type", r1[0]["rate"] == 31.5 and r1[0]["currency"] == "USD"
              and round(r1[0]["comm"], 6) == 33.0 and r1[0]["policyNo"] == c1.tw_ref and r1[0]["remark"] == "Fac" and r1[0]["tranxDate"] == "2031-05-31"
              and r1[0]["type"] == "N" and r1[0]["reinsurer"] == "ZZ Re A" and by(c1)[1]["reinsurer"] == "ZZ Re B", r1[0])
        r2 = by(c2)
        check("c2 (TWD, 50/50 split): rate 1, two people per reinsurer, shares add up", len(r2) == 4 and all(r["rate"] == 1 for r in r2)
              and {r["ae"] for r in r2} == {"ZZ A", "ZZ B"}, [(r["ae"], r["premium"], r["income"]) for r in r2])
        check("c3 installment: only the May installment (I1) is in May", {r["installmentId"] for r in by(c3)} == {"I1"})
        check("c4 (Reversed) is included", len(by(c4)) == 2)
        check("summary totals match the rows", j["summary"]["rowCount"] == len(j["rows"]) and j["summary"]["premiumNtd"] == sum((r["premium"] or 0) for r in j["rows"]))

        # ================= 排除 =================
        sig0 = j["sourceSignature"]
        target = r2[0]
        for label, extra, want in (("sales", dict(scope="reinsurer", reason="x", rowId=target["id"]), 403),):
            check(f"exclude by {label} -> {want}", post(sales, "exclude", M1, **extra).status_code == want)
        r = post(fin, "exclude", M1, scope="all", reason="x", rowId=target["id"]); check("exclude: bad scope -> 400 invalid_scope", code(r) == "invalid_scope")
        r = post(fin, "exclude", M1, scope="reinsurer", reason="   ", rowId=target["id"]); check("exclude: blank reason -> 400 reason_required", code(r) == "reason_required")
        r = post(fin, "exclude", M1, scope="reinsurer", reason="x", rowId="nope"); check("exclude: unknown row -> 409 row_not_available", code(r) == "row_not_available")
        r = post(fin, "exclude", M1, scope="reinsurer", reason="  waiting for signed slip  ", rowId=target["id"])
        ex = r.json().get("exclusion", {})
        check("exclude (reinsurer) -> 201, deferred to next month, reason trimmed", r.status_code == 201 and ex.get("deferred_to") == M2 and ex.get("scope") == "reinsurer"
              and ex.get("reinsurer_key") == target["reinsurerKey"] and ex.get("reason") == "waiting for signed slip" and ex.get("created_by") == fin_p.name, r.content[:300])
        check("VM: exclusion is audited (exclude_production_row)", audit(ex.get("id"), "exclude_production_row", "production_exclusion").exists())
        j = get(fin, M1).json()
        moved = [r for r in j["excluded"] if r["reinsurerKey"] == target["reinsurerKey"]]
        check("excluded reinsurer: both split rows move to 'excluded' with the exclusion details", len(moved) == 2 and moved[0]["exclusion"]["deferredTo"] == M2
              and moved[0]["exclusion"]["reason"] == "waiting for signed slip" and not [r for r in j["rows"] if r["reinsurerKey"] == target["reinsurerKey"]])
        check("the signature changed after the exclusion", j["sourceSignature"] != sig0)
        check("deferred rows appear in the next month", len([r for r in get(fin, M2).json()["rows"] if r["reinsurerKey"] == target["reinsurerKey"]]) == 2)
        r = post(fin, "exclude", M1, scope="reinsurer", reason="again", rowId=target["id"]); check("excluding the same row again -> 409 row_not_available", code(r) == "row_not_available")
        r9 = mine(get(fin, M1).json()["rows"], c9)
        r = post(fin, "exclude", M1, scope="case", reason="whole installment later", rowId=r9[0]["id"]); e9 = r.json().get("exclusion", {})
        j9 = get(fin, M1).json()
        check("exclude (case scope): no reinsurer key; every reinsurer row of that installment moves to 'excluded'", r.status_code == 201 and e9.get("reinsurer_key") is None
              and e9.get("installment_key") == r9[0]["key"] and mine(j9["rows"], c9) == [] and len(mine(j9["excluded"], c9)) == len(r9) == 2, r.content[:200])
        eobj = ProductionExclusion.objects.get(pk=ex["id"])
        check("DB: ri_runtime cannot UPDATE an exclusion", denied_write(lambda: ProductionExclusion.objects.filter(pk=eobj.pk).update(reason="changed")))
        check("DB: ri_runtime cannot DELETE an exclusion", denied_write(lambda: ProductionExclusion.objects.filter(pk=eobj.pk).delete()))
        check("DB: the same target cannot be excluded twice", denied_write(lambda: ProductionExclusion.objects.create(case_id=eobj.case_id, year_month=M1, scope="reinsurer",
              installment_key=eobj.installment_key, reinsurer_key=eobj.reinsurer_key, deferred_to=M2, reason="dup", created_by="t")))

        # ================= 產生版本 =================
        j = get(fin, M1).json()
        r = post(fin, "generate", M1, sourceSignature="stale"); check("generate with a stale signature -> 409 source_changed", code(r) == "source_changed")
        check("GM cannot generate (403)", post(gm, "generate", M1, sourceSignature=j["sourceSignature"]).status_code == 403)
        r = post(fin, "generate", M1, sourceSignature=j["sourceSignature"]); v1 = r.json().get("report", {})
        check("generate -> 201 version 1 valid, rows stored", r.status_code == 201 and v1.get("version") == 1 and v1.get("status") == "valid"
              and v1.get("rows") == j["rows"] and v1.get("excluded") == j["excluded"] and v1.get("sourceSignature") == j["sourceSignature"], r.content[:300])
        check("VM: generate is audited", audit(v1.get("reportUid"), "generate_production_report", "production_report").exists())
        r = post(fin, "generate", M1, sourceSignature=j["sourceSignature"]); v2 = r.json().get("report", {})
        rep1 = ProductionReport.objects.get(report_uid=v1["reportUid"])
        check("generate again -> version 2; version 1 becomes invalid (row_version 2)", v2.get("version") == 2 and rep1.status == "invalid" and rep1.row_version == 2)
        j = get(fin, M1).json()
        check("GET lists both versions, latest first; canCloseLatest for Finance Manager only", [v["version"] for v in j["versions"]] == [2, 1]
              and get(finm, M1).json()["scope"]["canCloseLatest"] is True and j["scope"]["canCloseLatest"] is False)

        # ================= 關帳：檢查 =================
        base = dict(reportUid=v2["reportUid"], rowVersion=1, sourceSignature=j["sourceSignature"])
        check("Finance Staff cannot close (403)", post(fin, "close", M1, **base).status_code == 403)
        r = post(finm, "close", M1, **{**base, "reportUid": str(uuid.uuid4())}); check("close unknown report -> 404", code(r) == "report_not_found")
        r = post(finm, "close", M1, **{**base, "reportUid": v1["reportUid"], "rowVersion": 2}); check("close a non-latest version -> 409 latest_valid_required", code(r) == "latest_valid_required")
        ProductionReport.objects.filter(report_uid=v1["reportUid"]).update(status="valid")   # 人為造出「兩個 valid」
        r = post(finm, "close", M1, **{**base, "reportUid": v1["reportUid"], "rowVersion": 2}); check("close a valid but older version -> 409 latest_valid_required", code(r) == "latest_valid_required")
        ProductionReport.objects.filter(report_uid=v1["reportUid"]).update(status="invalid")
        r = post(finm, "close", M1, **{**base, "rowVersion": 5}); check("close with a stale rowVersion -> 409 version_conflict", code(r) == "version_conflict")
        r = post(finm, "close", M1, **{k: v for k, v in base.items() if k != "rowVersion"}); check("close without rowVersion -> 409 version_conflict", code(r) == "version_conflict")
        r = post(finm, "close", M1, **{**base, "sourceSignature": "x"}); check("close with a different signature -> 409 source_changed", code(r) == "source_changed")
        patch(c1, originalInsured="ZZ Prd Insured changed")
        r = post(finm, "close", M1, **base); check("source data changed after generate -> 409 source_changed", code(r) == "source_changed")
        patch(c1, originalInsured="ZZ Prd Insured")
        check("nothing was closed by the failed attempts", ProductionReport.objects.get(report_uid=v2["reportUid"]).status == "valid" and Case.objects.get(pk=c1.pk).status == "posted")

        # ================= 關帳：成功 =================
        before = {c.pk: Case.objects.get(pk=c.pk).row_version for c in (c1, c2, c3, c4)}
        r = post(finm, "close", M1, **base); body = r.json()
        check("close -> 200 closed", r.status_code == 200 and body.get("status") == "closed" and body.get("reportUid") == v2["reportUid"], r.content[:300])
        rep2 = ProductionReport.objects.get(report_uid=v2["reportUid"])
        check("report closed with token, closedBy, closedAt, row_version 2", rep2.status == "closed" and rep2.close_token and rep2.closed_by == finm_p.name and rep2.closed_at and rep2.row_version == 2)
        c1.refresh_from_db(); tx = c1.payload.get("transactions", [])
        check("c1: all keys confirmed -> Confirmed (closed), not partial", c1.status == "closed" and c1.payload["productionPartiallyConfirmed"] is False
              and sorted(c1.payload["confirmedProductionKeys"]) == sorted(r["reinsurerKey"] for r in r1) and c1.row_version == before[c1.pk] + 1)
        check("c1: premium transactions Leg 1-3 numbered from the TW Ref", len(tx) >= 6 and all(t["txNo"].startswith(c1.tw_ref + "-R") for t in tx), [t["txNo"] for t in tx][:3])
        check("c1: audit production_case_confirmed + VM snapshot", audit(c1.case_uid, "production_case_confirmed").first().metadata == {"reportUid": v2["reportUid"], "month": M1, "productionClosed": True}
              and snaps(c1.case_uid, "production_case_confirmed").filter(entity_version=c1.row_version).exists())
        c2.refresh_from_db()
        check("c2: one reinsurer deferred -> stays Announced, partially confirmed, no transactions", c2.status == "posted" and c2.payload["productionPartiallyConfirmed"] is True
              and not c2.payload.get("transactions"), (c2.status, c2.payload.get("productionPartiallyConfirmed")))
        c3.refresh_from_db()
        check("c3: June installment still open -> stays Announced, partial", c3.status == "posted" and c3.payload["productionPartiallyConfirmed"] is True)
        c4.refresh_from_db(); t4 = c4.payload["transactions"]
        rvs = [t for t in t4 if "-RVS" in t["txNo"]]
        check("c4 (Reversed): closed; one -RVS1 offset for the not-yet-offset entry only", c4.status == "closed" and [t["txNo"] for t in rvs] == ["ZZ-OLD-R1-TX1-RVS1"]
              and rvs[0]["amount"] == -100 and rvs[0]["isReversalEntry"] is True and rvs[0]["settlement"] == "open" and c4.payload["pendingReversalOffset"] is False, [t["txNo"] for t in t4])
        check("c4: original entry marked reversalOffsetApplied; new cycle transactions end with -C1", t4[0].get("reversalOffsetApplied") is True
              and any(t["txNo"].endswith("-C1") for t in t4) and all(not t["txNo"].endswith("-C1") for t in t4[:3]), [t["txNo"] for t in t4])
        check("confirmedCases counts cases closed now (c1, c4, plus any real ones)", body.get("confirmedCases", 0) >= 2)
        f = FxRate.objects.get(year_month=M1, currency="USD")
        check("FX for the month locked", f.is_locked and f.lock_reason == f"Production Report {M1} closed" and f.locked_by and f.row_version == 2)
        check("VM: FX lock audited (lock_fx_rate) + snapshot fx_rate_locked", audit(f.id, "lock_fx_rate", "fx_rate").exists() and snaps(f.id, "fx_rate_locked", "fx_rate").exists())
        check("close audited on the report", audit(v2["reportUid"], "close_production_report", "production_report").first().after_data["status"] == "closed")
        j = get(finm, M1).json()
        check("after close: month closed, cannot generate or close again; confirmed rows gone", j["scope"]["monthClosed"] and not j["scope"]["canGenerate"]
              and not j["scope"]["canCloseLatest"] and mine(j["rows"], c1, c4) == [] and j["scope"]["fxLocked"])
        check("after close: generate -> 409 month_closed; exclude -> 409 month_closed", code(post(fin, "generate", M1, sourceSignature=j["sourceSignature"])) == "month_closed"
              and code(post(fin, "exclude", M1, scope="case", reason="x", rowId="a")) == "month_closed")
        check("DB: a second closed report for the same month is rejected", denied_write(lambda: ProductionReport.objects.filter(report_uid=v1["reportUid"]).update(
              status="closed", close_token=uuid.uuid4(), closed_by="t", closed_at=timezone.now())))
        jm2 = get(finm, M2).json()
        check("June preview: c3's I2 and the deferred c2 rows", {r["installmentId"] for r in mine(jm2["rows"], c3)} == {"I2"} and len(mine(jm2["rows"], c2)) == 2)

        # ================= 關帳衝突：產生之後案件被改（簽章不變） =================
        c7 = at(make_case(sales, "posted", policyFrom="2031-07-01", policyTo="2032-07-01", currency="TWD"), EARLY)
        j = get(finm, M3).json()
        rep = post(finm, "generate", M3, sourceSignature=j["sourceSignature"]).json()["report"]
        Case.objects.filter(pk=c7.pk).update(row_version=c7.row_version + 1)   # 有人同時存檔（內容相同，簽章不變）
        # 版本號改了但簽章不變：state 會重新讀到新版本，所以這不算衝突 -> 應可關帳
        r = post(finm, "close", M3, reportUid=rep["reportUid"], rowVersion=1, sourceSignature=j["sourceSignature"])
        check("a version bump without content change before close is fine (state is re-read)", r.status_code == 200, r.content[:200])

        # ================= transactions 損毀 =================
        c8 = at(make_case(sales, "reversed", policyFrom="2031-08-01", policyTo="2032-08-01", currency="TWD"), EARLY)
        patch(c8, pendingReversalOffset=True, transactions=[None])
        j = get(finm, M4).json()
        rep = post(finm, "generate", M4, sourceSignature=j["sourceSignature"]).json()["report"]
        r = post(finm, "close", M4, reportUid=rep["reportUid"], rowVersion=1, sourceSignature=j["sourceSignature"])
        check("close with a null inside transactions -> 409 transactions_corrupt, nothing closed", code(r) == "transactions_corrupt"
              and ProductionReport.objects.get(report_uid=rep["reportUid"]).status == "valid" and Case.objects.get(pk=c8.pk).status == "reversed", code(r))
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Prd Insured").count(),
      "| 2031 reports =", ProductionReport.objects.filter(year_month__startswith="2031").count())
