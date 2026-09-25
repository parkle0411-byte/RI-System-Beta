import io
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client

from audit.models import AuditLog, EntitySnapshot
from audit.services import CLI_ACTOR
from personnel import accounts
from personnel.models import Personnel
from personnel.views import unique_violation_response

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


def login(username, password):
    c = new_client(); cache.clear(); tok = csrf(c)
    r = c.post("/api/auth/login", data=json.dumps({"username": username, "password": password}),
               content_type="application/json", HTTP_X_CSRFTOKEN=tok)
    return c, r


def login_as(role, username):
    person = pick(role)
    u = User.objects.create_user(username=username, password=PW)
    person.auth_user_id = str(u.pk); person.account_status = "active"; person.save()
    c, r = login(username, PW)
    assert r.status_code == 200, r.content
    return c, person


def code(r):
    try:
        return r.json().get("error")
    except Exception:
        return None


def create(c, **kw):
    body = {"name": "ZZ Person", "department": "business_1", "isActive": True}
    body.update(kw)
    return call(c, "post", "/api/personnel", body)


try:
    with transaction.atomic():
        clients = {}
        for role in ("admin", "sales", "accounting", "accounting_manager", "general_manager", "viewer"):
            clients[role] = login_as(role, f"p_{role}")
        admin, admin_p = clients["admin"]

        # ============ 權限矩陣 ============
        read_ok = {"admin", "general_manager"}
        for role, (c, _) in clients.items():
            ok = role in read_ok
            check(f"[{role}] GET /api/personnel {'allowed' if ok else 'denied'}", c.get("/api/personnel").status_code == (200 if ok else 403))
            w_post = call(c, "post", "/api/personnel", {})
            w_put = call(c, "put", "/api/personnel", {})
            wok = role == "admin"
            check(f"[{role}] POST/PUT /api/personnel {'allowed (400 validation)' if wok else 'denied'}",
                  (w_post.status_code == 400 and w_put.status_code == 400) if wok else (w_post.status_code == 403 and w_put.status_code == 403), (w_post.status_code, w_put.status_code))
            oo = role in {"admin", "sales"}
            check(f"[{role}] GET personnel-options {'allowed' if oo else 'denied'}", c.get("/api/personnel-options").status_code == (200 if oo else 403))
            acc = call(c, "post", "/api/personnel-accounts", {})
            check(f"[{role}] account API {'allowed (400 validation)' if wok else 'denied'}", acc.status_code == (400 if wok else 403), acc.status_code)
        anon = new_client()
        check("anonymous personnel APIs -> 401", all(anon.get(u).status_code == 401 for u in ("/api/personnel", "/api/personnel-options")))

        # ============ 列表 ============
        r = admin.get("/api/personnel"); body = r.json()
        check("list: counts and scope", r.status_code == 200 and body["counts"]["total"] == len(body["personnel"]) and body["scope"]["credentialsEnabled"] is True)
        check("list: admin sees accountUsername, general_manager does not",
              "accountUsername" in body["personnel"][0] and "accountUsername" not in clients["general_manager"][0].get("/api/personnel").json()["personnel"][0])
        check("list: Alpha field names", {"id", "name", "email", "department", "roleCode", "isActive", "isSplitEligible", "accountStatus", "accountBound", "supervisorName", "supervisorEmail", "rowVersion", "updatedAt"} <= set(body["personnel"][0]))

        # ============ 新增：驗證 ============
        for label, kw, err in [
            ("empty name", {"name": " "}, "name_required"),
            ("bad department", {"department": "nope"}, "invalid_department"),
            ("bad role", {"roleCode": "boss"}, "invalid_role"),
            ("bad email", {"email": "not-an-email"}, "invalid_email"),
            ("email too long", {"email": "a" * 250 + "@x.com"}, "invalid_email"),
        ]:
            r = create(admin, **kw)
            check(f"create rejects {label} -> 400 {err}", r.status_code == 400 and code(r) == err, (r.status_code, code(r)))

        # ============ 新增：預設值 ============
        r = create(admin, name="ZZ Fin", department="finance")
        p = r.json()["person"]
        check("default role by department (finance -> accounting) and not split-eligible", r.status_code == 201 and p["roleCode"] == "accounting" and p["isSplitEligible"] is False, p)
        r = create(admin, name="ZZ Re GM", department="reinsurance", roleCode="general_manager")
        check("reinsurance general_manager is not split-eligible", r.json()["person"]["isSplitEligible"] is False)
        r = create(admin, name="ZZ Biz", department="business_2")
        check("business dept defaults: viewer, split-eligible", r.json()["person"]["roleCode"] == "viewer" and r.json()["person"]["isSplitEligible"] is True)
        r = create(admin, name="ZZ Explicit", department="business_2", isSplitEligible=False)
        check("explicit isSplitEligible=false is honoured", r.json()["person"]["isSplitEligible"] is False)
        r = create(admin, name="ZZ Email", email="  Mixed.Case@Example.COM ")
        check("email is trimmed and lower-cased", r.json()["person"]["email"] == "mixed.case@example.com")
        # #15: 可以直接建立「在職」人員（過去因為旗標被鎖死而做不到）
        r = create(admin, name="ZZ Active15", isActive=True)
        check("#15: creating an ACTIVE person works", r.status_code == 201 and r.json()["person"]["isActive"] is True)
        r = create(admin, name="ZZ Inactive", isActive=False)
        row = Personnel.objects.get(name="ZZ Inactive")
        check("inactive create records who/when deactivated", r.status_code == 201 and row.deactivated_by == f"personnel:{admin_p.pk}" and row.deactivated_at is not None)

        # ============ 重複 ============
        first = create(admin, name="ZZ Person", department="business_1")
        r2 = create(admin, name="zz PERSON", department="business_1")
        check("duplicate name+department (case-insensitive) -> 409", first.status_code == 201 and r2.status_code == 409 and code(r2) == "duplicate_name")
        r3 = create(admin, name="ZZ Person", department="business_2")
        check("same name in another department is allowed", r3.status_code == 201)
        e1 = create(admin, name="ZZ E1", email="dup@example.com")
        e2 = create(admin, name="ZZ E2", email="DUP@example.com")
        check("duplicate email (case-insensitive) -> 409", e1.status_code == 201 and e2.status_code == 409 and code(e2) == "duplicate_email")
        # DB 唯一約束是最終防線
        for label, field, val, expect in (("name+department", "name", "ZZ Person", "duplicate_name"), ("email", "email", "dup@example.com", "duplicate_email")):
            try:
                with transaction.atomic():
                    Personnel.objects.create(name=val if field == "name" else "ZZ Other", email=val if field == "email" else None,
                                             department="business_1", role_code="viewer", created_by="t", updated_by="t")
                check(f"DB constraint blocks duplicate {label}", False)
            except IntegrityError as exc:
                resp = unique_violation_response(exc)
                check(f"DB constraint blocks duplicate {label} and maps to {expect}", resp is not None and resp.status_code == 409 and resp.data["error"] == expect, str(exc)[:80])

        # ============ #14 主管解析：同名跨部門，結果固定 ============
        s1 = Personnel.objects.create(name="ZZ Sup", email="s1@example.com", department="business_1", role_code="viewer", created_by="t", updated_by="t")
        s2 = Personnel.objects.create(name="ZZ Sup", email="s2@example.com", department="reinsurance", role_code="general_manager", created_by="t", updated_by="t")
        picks = []
        for i in range(4):
            r = create(admin, name=f"ZZ Emp b1 {i}", department="business_1", supervisorName="zz sup")
            picks.append(r.json()["person"]["supervisorEmail"])
        check("#14: same-department supervisor is preferred, every time", picks == ["s1@example.com"] * 4, picks)
        picks = [create(admin, name=f"ZZ Emp sr {i}", department="special_risk", supervisorName="ZZ SUP").json()["person"]["supervisorEmail"] for i in range(3)]
        check("#14: otherwise the General Manager is chosen, every time", picks == ["s2@example.com"] * 3, picks)
        r = create(admin, name="ZZ Emp fin", department="finance", supervisorName="ZZ Sup")
        check("#14: non-GM from another department is rejected", r.json()["person"]["supervisorEmail"] == "s2@example.com" or code(r) == "invalid_supervisor")
        r = create(admin, name="ZZ Emp none", department="business_2", supervisorName="Nobody Here")
        check("unknown supervisor -> 400 invalid_supervisor", r.status_code == 400 and code(r) == "invalid_supervisor")
        s1.is_active = False; s1.deactivated_by = "t"; s1.deactivated_at = "2026-01-01T00:00:00Z"; s1.save()
        r = create(admin, name="ZZ Emp inactive sup", department="business_1", supervisorName="ZZ Sup")
        check("inactive same-department supervisor is skipped (falls back to the GM)", r.status_code == 201 and r.json()["person"]["supervisorEmail"] == "s2@example.com", r.status_code)

        # ============ 編輯 / 停用 / 版本 ============
        target = Personnel.objects.get(name="ZZ E1")
        r = call(admin, "put", "/api/personnel", {"id": target.pk, "rowVersion": 99, "name": "ZZ E1", "department": "business_1"})
        check("stale rowVersion -> 409 with currentRowVersion", r.status_code == 409 and code(r) == "version_conflict" and r.json()["currentRowVersion"] == target.row_version)
        check("missing id/version -> 400 version_required", code(call(admin, "put", "/api/personnel", {"name": "x", "department": "business_1"})) == "version_required")
        check("unknown id -> 404", call(admin, "put", "/api/personnel", {"id": 999999, "rowVersion": 1, "name": "x", "department": "business_1"}).status_code == 404)
        r = call(admin, "put", "/api/personnel", {"id": target.pk, "rowVersion": target.row_version, "name": "ZZ E1 Renamed", "department": "business_1", "email": "dup@example.com", "isActive": True})
        check("edit -> 200, version bumped", r.status_code == 200 and r.json()["person"]["rowVersion"] == target.row_version + 1 and r.json()["person"]["name"] == "ZZ E1 Renamed")
        e2p = Personnel.objects.get(name="ZZ Fin")
        r = call(admin, "put", "/api/personnel", {"id": e2p.pk, "rowVersion": e2p.row_version, "name": "zz e1 renamed", "department": "business_1"})
        check("rename onto an existing name+department -> 409", r.status_code == 409 and code(r) == "duplicate_name")
        me = Personnel.objects.get(name="ZZ E1 Renamed")
        r = call(admin, "put", "/api/personnel", {"id": me.pk, "rowVersion": me.row_version, "name": me.name, "department": "business_1", "supervisorName": me.name})
        check("selecting yourself as supervisor is rejected", r.status_code == 400 and code(r) == "invalid_supervisor")

        # 停用 -> 編輯不覆寫停用時間 -> 重新啟用（#15）
        me = Personnel.objects.get(name="ZZ E1 Renamed")
        r = call(admin, "put", "/api/personnel", {"id": me.pk, "rowVersion": me.row_version, "name": me.name, "department": "business_1", "email": me.email, "isActive": False})
        me.refresh_from_db()
        first_stamp = me.deactivated_at
        check("deactivate -> deactivate_personnel + who/when", r.status_code == 200 and me.is_active is False and me.deactivated_by == f"personnel:{admin_p.pk}" and first_stamp is not None)
        r = call(admin, "put", "/api/personnel", {"id": me.pk, "rowVersion": me.row_version, "name": me.name + " x", "department": "business_1", "email": me.email, "isActive": False})
        me.refresh_from_db()
        check("editing an already-inactive person keeps the original deactivation time", r.status_code == 200 and me.deactivated_at == first_stamp)
        r = call(admin, "put", "/api/personnel", {"id": me.pk, "rowVersion": me.row_version, "name": me.name, "department": "business_1", "email": me.email, "isActive": True})
        me.refresh_from_db()
        check("#15: reactivate works and clears deactivation fields", r.status_code == 200 and me.is_active and me.deactivated_by is None and me.deactivated_at is None)
        acts = list(AuditLog.objects.filter(entity_type="personnel", entity_id=str(me.pk)).order_by("id").values_list("action", flat=True))
        check("audit trail for that person", acts == ["create_personnel", "update_personnel", "deactivate_personnel", "update_personnel", "reactivate_personnel"] or acts[-3:] == ["deactivate_personnel", "update_personnel", "reactivate_personnel"], acts)
        snaps = list(EntitySnapshot.objects.filter(entity_type="personnel", entity_id=str(me.pk)).order_by("entity_version").values_list("entity_version", flat=True))
        check("a snapshot exists for every version", snaps == list(range(snaps[0], snaps[0] + len(snaps))) and snaps[-1] == me.row_version, snaps)
        ev = AuditLog.objects.filter(entity_type="personnel", entity_id=str(me.pk), action="deactivate_personnel").first()
        check("audit event: actor, before/after state", ev.actor_id == f"personnel:{admin_p.pk}" and ev.before_data["isActive"] is True and ev.after_data["isActive"] is False)

        # 原子性
        with mock.patch("personnel.views.record_audit", side_effect=RuntimeError("audit down")):
            r = create(admin, name="ZZ Atomic")
        check("audit failure rolls the create back", r.status_code == 500 and not Personnel.objects.filter(name="ZZ Atomic").exists())

        # ============ 帳號 API ============
        acct = Personnel.objects.create(name="ZZ Acct", department="business_1", role_code="viewer", created_by="t", updated_by="t")
        for label, kw, expect in [("bad username", {"username": "A B"}, "invalid_username"), ("short username", {"username": "ab"}, "invalid_username")]:
            r = call(admin, "post", "/api/personnel-accounts", {"personnelId": acct.pk, **kw})
            check(f"create account rejects {label}", r.status_code == 400 and code(r) == expect, code(r))
        check("create account for unknown person -> 404", call(admin, "post", "/api/personnel-accounts", {"personnelId": 999999, "username": "zz.nobody"}).status_code == 404)
        check("missing personnelId -> 400", code(call(admin, "post", "/api/personnel-accounts", {"username": "zz.x"})) == "personnel_required")

        r = call(admin, "post", "/api/personnel-accounts", {"personnelId": acct.pk, "username": "ZZ.Acct@Example.com", "email": "ZZ.Acct@Example.com"})
        j = r.json()
        initial = j.get("initialPassword", "")
        check("create account -> 201, username lower-cased, one-time password", r.status_code == 201 and j["username"] == "zz.acct@example.com" and len(initial) >= 16 and j["person"]["accountStatus"] == "active" and j["person"]["accountUsername"] == "zz.acct@example.com", r.status_code)
        check("password is not part of the person object", initial not in json.dumps(j["person"]))
        check("response is no-store", r["Cache-Control"].startswith("no-store"))
        ucl, lr = login("ZZ.ACCT@example.com", initial)
        check("the new account can log in (case-insensitive) as a viewer", lr.status_code == 200 and lr.json()["principal"]["roleCode"] == "viewer")
        check("viewer cannot read personnel", ucl.get("/api/personnel").status_code == 403)
        check("email was copied onto the Personnel record", Personnel.objects.get(pk=acct.pk).email == "zz.acct@example.com")

        r = call(admin, "post", "/api/personnel-accounts", {"personnelId": acct.pk, "username": "another.name"})
        check("second account for the same person -> 409 account_exists", r.status_code == 409 and code(r) == "account_exists")
        other = Personnel.objects.create(name="ZZ Acct2", department="business_1", role_code="viewer", created_by="t", updated_by="t")
        check("username already used (case-insensitive) -> 409", code(call(admin, "post", "/api/personnel-accounts", {"personnelId": other.pk, "username": "ZZ.ACCT@EXAMPLE.COM"})) == "username_taken")
        check("email already on another person -> 409", code(call(admin, "post", "/api/personnel-accounts", {"personnelId": other.pk, "username": "zz.other", "email": "zz.acct@example.com"})) == "email_taken")
        inactive = Personnel.objects.get(name="ZZ Inactive")
        check("inactive person cannot get an account -> 409", code(call(admin, "post", "/api/personnel-accounts", {"personnelId": inactive.pk, "username": "zz.inactive"})) == "personnel_inactive")

        # 重設密碼
        r = call(admin, "post", "/api/personnel-accounts/reset-password", {"personnelId": acct.pk})
        newpw = r.json().get("newPassword", "")
        check("reset -> new one-time password and the live session is ended", r.status_code == 200 and newpw and newpw != initial and r.json()["sessionsEnded"] >= 1, r.status_code)
        check("the user's old session no longer works", ucl.get("/api/app-context").status_code == 401)
        check("old password rejected, new password accepted", login("zz.acct@example.com", initial)[1].status_code == 401 and login("zz.acct@example.com", newpw)[1].status_code == 200)
        check("admin cannot reset their own password here", code(call(admin, "post", "/api/personnel-accounts/reset-password", {"personnelId": admin_p.pk})) == "cannot_reset_own_password")
        check("reset for a person without an account -> 409", code(call(admin, "post", "/api/personnel-accounts/reset-password", {"personnelId": other.pk})) == "no_active_account")

        # 停用
        ucl2, _ = login("zz.acct@example.com", newpw)
        r = call(admin, "post", "/api/personnel-accounts/disable", {"personnelId": acct.pk})
        check("disable -> status disabled, sessions ended", r.status_code == 200 and r.json()["person"]["accountStatus"] == "disabled" and r.json()["sessionsEnded"] >= 1)
        check("disabled user's session is dead and login is refused", ucl2.get("/api/app-context").status_code == 401 and login("zz.acct@example.com", newpw)[1].status_code == 401)
        check("disabling twice -> 409", code(call(admin, "post", "/api/personnel-accounts/disable", {"personnelId": acct.pk})) == "already_disabled")
        check("admin cannot disable their own account", code(call(admin, "post", "/api/personnel-accounts/disable", {"personnelId": admin_p.pk})) == "cannot_disable_own_account")

        # Email 變更規則
        acct.refresh_from_db()
        r = call(admin, "put", "/api/personnel", {"id": acct.pk, "rowVersion": acct.row_version, "name": acct.name, "department": "business_1", "email": "new.mail@example.com", "isActive": True})
        acct.refresh_from_db()
        check("disabled account + new email -> binding reset (not_configured, unbound)", r.status_code == 200 and acct.account_status == "not_configured" and acct.auth_user_id is None and acct.email == "new.mail@example.com", (r.status_code, acct.account_status))
        ev = AuditLog.objects.filter(entity_type="personnel", entity_id=str(acct.pk), action="update_personnel").order_by("-id").first()
        check("that audit event says the account was reset", ev.metadata.get("accountResetForEmailChange") is True)
        r = call(admin, "post", "/api/personnel-accounts", {"personnelId": acct.pk, "username": "zz.acct.v2", "email": "new.mail@example.com"})
        check("a fresh account can be created for the new email", r.status_code == 201)
        acct.refresh_from_db()
        r = call(admin, "put", "/api/personnel", {"id": acct.pk, "rowVersion": acct.row_version, "name": acct.name, "department": "business_1", "email": "third@example.com", "isActive": True})
        check("active account: changing email is blocked", r.status_code == 409 and code(r) == "disable_account_before_email_change")
        r = call(admin, "put", "/api/personnel", {"id": acct.pk, "rowVersion": acct.row_version, "name": acct.name, "department": "business_1", "email": "new.mail@example.com", "roleCode": "sales", "isActive": True})
        check("changing role while the account is active is allowed", r.status_code == 200)

        # 最後一位管理員
        pl = Personnel.objects.filter(role_code="admin", account_status="active").exclude(pk=admin_p.pk).first()
        if pl:
            accounts.disable_account(personnel_id=pl.pk, actor=CLI_ACTOR, source="cli")
        admin_p.refresh_from_db()
        r = call(admin, "put", "/api/personnel", {"id": admin_p.pk, "rowVersion": admin_p.row_version, "name": admin_p.name, "department": admin_p.department, "roleCode": "viewer", "isActive": True})
        check("last active admin cannot be demoted", r.status_code == 409 and code(r) == "last_active_admin", (r.status_code, code(r)))
        r = call(admin, "put", "/api/personnel", {"id": admin_p.pk, "rowVersion": admin_p.row_version, "name": admin_p.name, "department": admin_p.department, "roleCode": "admin", "isActive": False})
        check("last active admin cannot be deactivated", r.status_code == 409 and code(r) == "last_active_admin")
        try:
            accounts.disable_account(personnel_id=admin_p.pk, actor=CLI_ACTOR, source="cli")
            check("service refuses to disable the last active admin account", False)
        except accounts.AccountError as e:
            check("service refuses to disable the last active admin account", e.code == "last_active_admin", e.code)

        # personnel-options
        r = admin.get("/api/personnel-options").json()
        check("options: only active people, default owner is the caller", all(p["isActive"] for p in r["personnel"]) and r["defaultOwnerId"] == admin_p.pk and "ZZ Inactive" not in [p["name"] for p in r["personnel"]])

        # CLI 仍可用（走同一份服務）
        cli_target = Personnel.objects.create(name="ZZ Cli", department="business_1", role_code="viewer", created_by="t", updated_by="t")
        out = io.StringIO()
        call_command("create_ri_account", personnel_id=cli_target.pk, username="zz.cli", stdout=out)
        cli_pw = [l for l in out.getvalue().splitlines() if "password :" in l][0].split("password :")[1].strip()
        call_command("reset_ri_password", personnel_id=cli_target.pk, stdout=io.StringIO())
        call_command("disable_ri_account", personnel_id=cli_target.pk, stdout=io.StringIO())
        check("CLI commands still work through the shared service", AuditLog.objects.filter(entity_id=str(cli_target.pk), source="cli").count() == 3)

        # 密碼絕不進稽核
        dump = json.dumps(list(AuditLog.objects.values("before_data", "after_data", "metadata")), default=str)
        check("no generated password ever appears in the audit trail", all(x and x not in dump for x in (initial, newpw, cli_pw)) and "pbkdf2" not in dump)

        raise Rollback()
except Rollback:
    pass

fails = [r for r in results if not r[1]]
for n, ok, d in results:
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| users =", User.objects.count(),
      "| personnel =", Personnel.objects.count(), "| audit rows =", AuditLog.objects.count())
