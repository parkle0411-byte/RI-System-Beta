import io
import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import Client, override_settings
from django.utils import timezone

from audit.models import AppendOnlyError, AuditLog, EntitySnapshot
from audit.services import record_audit
from fxrates.models import FxRate
from masterdata.models import MasterRecord
from personnel.models import Personnel

User = get_user_model()

# 測試自己建立臨時人員（在會回滾的交易內），不挑用真實資料：真實人員被建了帳號或改名都不影響測試
_DEPT = {"admin": "admin", "sales": "reinsurance", "accounting": "finance", "accounting_manager": "finance",
         "general_manager": "reinsurance", "viewer": "business_1"}
_seq = [0]
def pick(role):
    _seq[0] += 1
    return Personnel.objects.create(name=f"ZZ T {role} {_seq[0]}", department=_DEPT[role], role_code=role, created_by="t", updated_by="t")
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


class Rollback(Exception):
    pass


PW = "Correct-Horse-Battery-9"


def expect_db_error(name, sql, params=None):
    """在 savepoint 內執行，應該被資料庫拒絕。"""
    try:
        with transaction.atomic():
            with connection.cursor() as c:
                c.execute(sql, params or [])
        check(name, False, "statement unexpectedly succeeded")
    except DatabaseError as e:
        check(name, True, str(e)[:90])


def new_client():
    return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)


def csrf(c):
    c.get("/api/auth/csrf")
    return c.cookies["csrftoken"].value


def call(c, method, url, body=None, **extra):
    fn = getattr(c, method)
    kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value, **extra)
    if body is not None:
        return fn(url, data=json.dumps(body), content_type="application/json", **kw)
    return fn(url, **kw)


def login_as(role, username):
    person = pick(role)
    u = User.objects.create_user(username=username, password=PW)
    person.auth_user_id = str(u.pk); person.account_status = "active"; person.save()
    c = new_client(); cache.clear(); tok = csrf(c)
    r = c.post("/api/auth/login", data=json.dumps({"username": username, "password": PW}),
               content_type="application/json", HTTP_X_CSRFTOKEN=tok)
    assert r.status_code == 200, r.content
    return c, person


# ============ A. 資料庫層（交易外執行：DDL 即使被拒也會隱式提交，不能放在測試交易裡）============
with connection.cursor() as c:
    c.execute("SELECT CURRENT_USER()"); who = c.fetchone()[0]
check("backend connects as ri_runtime", who.startswith("ri_runtime@"), who)
for tbl in ("ri_audit_log", "ri_entity_snapshots"):
    expect_db_error(f"runtime UPDATE {tbl} denied", f"UPDATE {tbl} SET entity_type = 'x'")
    expect_db_error(f"runtime DELETE {tbl} denied", f"DELETE FROM {tbl}")
    expect_db_error(f"runtime TRUNCATE {tbl} denied", f"TRUNCATE TABLE {tbl}")
for tbl in ("ri_master_records", "ri_personnel", "ri_cases", "ri_fx_rates"):
    expect_db_error(f"runtime DELETE {tbl} denied (never physically deleted)", f"DELETE FROM {tbl}")
expect_db_error("runtime ALTER TABLE denied", "ALTER TABLE ri_audit_log ADD COLUMN zz INT")
expect_db_error("runtime DROP TABLE denied", "DROP TABLE ri_audit_log")
expect_db_error("runtime DROP TRIGGER denied", "DROP TRIGGER ri_audit_log_no_update")
expect_db_error("runtime CREATE TABLE denied", "CREATE TABLE zz_x (id INT)")
expect_db_error("audit retention < 20 years rejected by trigger",
                "INSERT INTO ri_audit_log (entity_type, entity_id, action, before_data, after_data, actor_id, source, occurred_at, retention_until, metadata) "
                "VALUES ('t','1','a', NULL, JSON_OBJECT('a',1), 'x', 'application', NOW(6), DATE_ADD(NOW(6), INTERVAL 5 YEAR), JSON_OBJECT())")
expect_db_error("audit row with neither before nor after rejected (CHECK)",
                "INSERT INTO ri_audit_log (entity_type, entity_id, action, actor_id, source, occurred_at, retention_until, metadata) "
                "VALUES ('t','1','a','x','application', NOW(6), DATE_ADD(NOW(6), INTERVAL 21 YEAR), JSON_OBJECT())")
n = AuditLog.objects.count()
check("audit table still has all rows after the attempts", n >= 104, n)



try:
    with transaction.atomic():
        # ============ C. 應用層防護 ============
        first = AuditLog.objects.order_by("id").first()
        for label, fn in {
            "queryset.update": lambda: AuditLog.objects.update(actor_name="x"),
            "queryset.delete": lambda: AuditLog.objects.all().delete(),
            "instance.save on existing row": lambda: (setattr(first, "actor_name", "x"), first.save()),
            "instance.delete": lambda: first.delete(),
            "snapshot queryset.update": lambda: EntitySnapshot.objects.update(created_by="x"),
            "snapshot queryset.delete": lambda: EntitySnapshot.objects.all().delete(),
        }.items():
            try:
                fn(); check(f"model guard: {label} refused", False)
            except AppendOnlyError:
                check(f"model guard: {label} refused", True)
        with mock.patch("audit.services.connection", mock.Mock(in_atomic_block=False)):
            try:
                record_audit(entity_type="t", entity_id=1, action="a", after={"a": 1}, actor=None)
                check("audit write outside a transaction refused", False)
            except RuntimeError:
                check("audit write outside a transaction refused", True)
        with override_settings(AUDIT_LOG_ENABLED=False):
            try:
                record_audit(entity_type="t", entity_id=1, action="a", after={"a": 1}, actor=None)
                check("AUDIT_LOG_ENABLED=false is refused, not silently skipped", False)
            except Exception as e:
                check("AUDIT_LOG_ENABLED=false is refused, not silently skipped", "AUDIT_LOG_ENABLED" in str(e))

        # ============ D. 由 API 到稽核紀錄 ============
        sales, sp = login_as("sales", "a_sales")
        before_n = AuditLog.objects.count()
        r = call(sales, "post", "/api/master-data", {"entityType": "class", "name": "ZZ Audit Class"}, HTTP_X_REQUEST_ID="req-abc-123")
        rec = MasterRecord.objects.get(name="ZZ Audit Class")
        ev = AuditLog.objects.filter(entity_type="master_record", entity_id=str(rec.id)).order_by("id")
        check("create master -> 201 and exactly one audit event", r.status_code == 201 and ev.count() == 1, ev.count())
        e = ev.first()
        check("create event: action/actor/role/source", (e.action, e.actor_id, e.actor_role, e.source) == ("create_master", f"personnel:{sp.pk}", "sales", "application"), (e.action, e.actor_id))
        check("create event: before is null, after has Alpha's fields",
              e.before_data is None and set(e.after_data) == {"id", "entityType", "code", "name", "displayOrder", "isActive", "rowVersion", "payload"}, list(e.after_data or {}))
        check("create event carries the X-Request-ID", e.request_id == "req-abc-123", e.request_id)
        check("retention_until is 20 years after occurred_at", e.retention_until.year - e.occurred_at.year == 20, (e.occurred_at, e.retention_until))
        sn = EntitySnapshot.objects.get(entity_type="master_record", entity_id=str(rec.id), entity_version=1)
        check("create snapshot v1 reason master_created", sn.snapshot_reason == "master_created" and sn.created_by == f"personnel:{sp.pk}")

        r = call(sales, "put", "/api/master-data", {"id": rec.id, "entityType": "class", "name": "ZZ Audit Class 2", "rowVersion": 1, "isActive": True})
        e = AuditLog.objects.filter(entity_type="master_record", entity_id=str(rec.id)).order_by("-id").first()
        check("update master -> update_master with before/after", r.status_code == 200 and e.action == "update_master" and e.before_data["name"] == "ZZ Audit Class" and e.after_data["name"] == "ZZ Audit Class 2" and e.before_data["rowVersion"] == 1 and e.after_data["rowVersion"] == 2)
        r = call(sales, "put", "/api/master-data", {"id": rec.id, "entityType": "class", "name": "ZZ Audit Class 2", "rowVersion": 2, "isActive": False})
        e = AuditLog.objects.filter(entity_type="master_record", entity_id=str(rec.id)).order_by("-id").first()
        check("deactivate -> deactivate_master", e.action == "deactivate_master" and e.after_data["isActive"] is False)
        r = call(sales, "put", "/api/master-data", {"id": rec.id, "entityType": "class", "name": "ZZ Audit Class 2", "rowVersion": 3, "isActive": True})
        e = AuditLog.objects.filter(entity_type="master_record", entity_id=str(rec.id)).order_by("-id").first()
        check("reactivate -> reactivate_master", e.action == "reactivate_master")
        versions = list(EntitySnapshot.objects.filter(entity_type="master_record", entity_id=str(rec.id)).order_by("entity_version").values_list("entity_version", "snapshot_reason"))
        check("snapshots v1..v4 with matching reasons", versions == [(1, "master_created"), (2, "master_updated"), (3, "master_deactivated"), (4, "master_reactivated")], versions)

        n0 = AuditLog.objects.count(); s0 = EntitySnapshot.objects.count()
        r1 = call(sales, "post", "/api/master-data", {"entityType": "class", "name": "zz audit class 2"})          # duplicate
        r2 = call(sales, "put", "/api/master-data", {"id": rec.id, "entityType": "class", "name": "X", "rowVersion": 1})  # stale version
        check("rejected writes (409) leave no audit or snapshot", r1.status_code == 409 and r2.status_code == 409 and AuditLog.objects.count() == n0 and EntitySnapshot.objects.count() == s0)

        # 原子性：稽核寫入失敗 -> 業務寫入一起回滾
        with mock.patch("masterdata.views.record_audit", side_effect=RuntimeError("audit down")):
            r = call(sales, "post", "/api/master-data", {"entityType": "class", "name": "ZZ Atomic"})
        check("audit failure rolls the business write back (no orphan record)", r.status_code == 500 and not MasterRecord.objects.filter(name="ZZ Atomic").exists() and not EntitySnapshot.objects.filter(snapshot_data__name="ZZ Atomic").exists(), r.status_code)

        # FX
        fm, fp = login_as("accounting_manager", "a_fm")
        rates = [{"currency": c, "rate": 1.5} for c in ("USD", "EUR", "JPY", "GBP", "HKD", "MYR")]
        r = call(fm, "post", "/api/fx-rates", {"yearMonth": "2099-01", "rates": rates})
        ids = list(FxRate.objects.filter(year_month="2099-01").values_list("id", flat=True))
        evs = AuditLog.objects.filter(entity_type="fx_rate", entity_id__in=[str(i) for i in ids])
        check("FX save -> 6 create_fx_rate events and 6 snapshots",
              r.status_code == 200 and evs.filter(action="create_fx_rate").count() == 6 and EntitySnapshot.objects.filter(entity_type="fx_rate", entity_id__in=[str(i) for i in ids]).count() == 6)
        row = FxRate.objects.filter(year_month="2099-01", currency="USD").first()
        e = evs.filter(entity_id=str(row.id)).first()
        check("FX event shape (rate is a number, yearMonth camelCase)", e.after_data["rate"] == 1.5 and e.after_data["yearMonth"] == "2099-01" and e.actor_id == f"personnel:{fp.pk}", e.after_data)
        versions = {x["currency"]: FxRate.objects.get(year_month="2099-01", currency=x["currency"]).row_version for x in rates}
        r = call(fm, "post", "/api/fx-rates", {"yearMonth": "2099-01", "rates": [{"currency": c, "rate": 1.6, "rowVersion": versions[c]} for c in versions]})
        upd = AuditLog.objects.filter(entity_type="fx_rate", action="update_fx_rate", entity_id__in=[str(i) for i in ids])
        check("FX re-save -> 6 update_fx_rate events with before data", r.status_code == 200 and upd.count() == 6 and all(u.before_data["rate"] == 1.5 and u.after_data["rate"] == 1.6 for u in upd))
        n0 = AuditLog.objects.count()
        r = call(fm, "post", "/api/fx-rates", {"yearMonth": "2099-01", "rates": [{"currency": c, "rate": 1.7, "rowVersion": 1} for c in versions]})
        check("FX stale version -> 409 and no audit written", r.status_code == 409 and AuditLog.objects.count() == n0)

        # 讀取 API
        admin, _ = login_as("admin", "a_admin")
        r = admin.get("/api/audit-log?limit=5"); body = r.json()
        check("GET /api/audit-log (admin) -> 200, readOnly, 5 newest first",
              r.status_code == 200 and body["readOnly"] is True and len(body["events"]) == 5 and body["events"][0]["id"] > body["events"][1]["id"], r.status_code)
        check("audit-log event keys match Alpha", list(body["events"][0]) == ["id", "entity_type", "entity_id", "action", "before_data", "after_data", "actor_id", "actor_name", "actor_role", "request_id", "source", "occurred_at", "retention_until", "metadata"], list(body["events"][0]))
        check("audit-log limit is capped at 250", len(admin.get("/api/audit-log?limit=99999").json()["events"]) <= 250)
        check("audit-log rejects non-GET", call(admin, "post", "/api/audit-log", {}).status_code in (403, 405))
        for role, allowed in (("general_manager", True), ("accounting", False), ("viewer", False)):
            c2, _ = login_as(role, f"a_{role}")
            check(f"audit-log as {role}: {'allowed' if allowed else 'denied'}", c2.get("/api/audit-log").status_code == (200 if allowed else 403))
        check("audit-log as sales: denied", sales.get("/api/audit-log").status_code == 403)
        check("audit-log anonymous: 401", new_client().get("/api/audit-log").status_code == 401)

        # 帳號指令：有紀錄，且密碼絕不出現在稽核裡
        target = pick("viewer")
        out = io.StringIO()
        call_command("create_ri_account", personnel_id=target.pk, username="zz_cli_user", stdout=out)
        pw_line = [l for l in out.getvalue().splitlines() if "password :" in l][0]
        generated = pw_line.split("password :")[1].strip()
        e = AuditLog.objects.filter(entity_type="personnel", entity_id=str(target.pk), action="create_account").first()
        check("create_ri_account writes create_account audit + snapshot", e is not None and e.source == "cli" and e.metadata["username"] == "zz_cli_user" and EntitySnapshot.objects.filter(entity_type="personnel", entity_id=str(target.pk), snapshot_reason="personnel_account_created").exists())
        call_command("reset_ri_password", personnel_id=target.pk, stdout=io.StringIO())
        call_command("disable_ri_account", personnel_id=target.pk, stdout=io.StringIO())
        acts = list(AuditLog.objects.filter(entity_type="personnel", entity_id=str(target.pk)).order_by("id").values_list("action", flat=True))
        check("reset + disable are recorded (after the baseline import event)", acts == ["create_account", "reset_account_password", "disable_account"], acts)
        dump = json.dumps(list(AuditLog.objects.filter(entity_type="personnel", entity_id=str(target.pk)).values("before_data", "after_data", "metadata")), default=str)
        check("the generated password never appears in the audit trail", generated not in dump and "pbkdf2" not in dump)

        raise Rollback()
except Rollback:
    pass

fails = [r for r in results if not r[1]]
for n, ok, d in results:
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: audit rows =", AuditLog.objects.count(), "| snapshots =", EntitySnapshot.objects.count(),
      "| users =", User.objects.count(), "| ZZ records =", MasterRecord.objects.filter(name__startswith="ZZ").count())
