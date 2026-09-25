import io
import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=f"ZZ PW {role} {_seq[0]}", department=dept, role_code=role, created_by="t", updated_by="t", **kw)

def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def login(username, password):
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": username, "password": password}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return c, r
def code(r):
    try: return r.json().get("error")
    except Exception: return None
def direct_account(p, username, password):
    u = User.objects.create_user(username=username, password=password)
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save(); return u
BUSINESS = [("get", "/api/cases"), ("get", "/api/fx-rates"), ("get", "/api/master-data"), ("get", "/api/personnel-options"),
            ("get", "/api/personnel"), ("get", "/api/audit-log"), ("post", "/api/cases")]
OLD, NEW, NEWER = "Temp-Start-Pass-1", "Brand-New-Pass-2", "Another-New-Pass-3"

try:
    with transaction.atomic():
        ap = person("admin", "admin"); direct_account(ap, "pw2_admin", "Admin-Long-Pass-1")
        admin, r = login("pw2_admin", "Admin-Long-Pass-1"); assert r.status_code == 200
        check("an account that predates the feature (flag False) is not forced", r.json()["principal"]["mustChangePassword"] is False
              and call(admin, "get", "/api/fx-rates").status_code == 200)

        # --- 建立帳號 → 強制改密碼 ---
        tgt = person("sales", "reinsurance")
        r = call(admin, "post", "/api/personnel-accounts", {"personnelId": tgt.pk, "username": "zz.pw2.user", "initialPassword": OLD}); j = r.json()
        tgt.refresh_from_db()
        check("create account (admin-set password) marks mustChangePassword", r.status_code == 201 and tgt.must_change_password and j["person"]["accountMustChangePassword"] is True, (r.status_code, j))
        user, r = login("zz.pw2.user", OLD)
        check("login works and reports mustChangePassword=true", r.status_code == 200 and r.json()["principal"]["mustChangePassword"] is True)
        for m, url in BUSINESS:
            r = call(user, m, url, {"case": {}} if m == "post" else None)
            check(f"forced user: {m.upper()} {url} -> 403 PASSWORD_CHANGE_REQUIRED", r.status_code == 403 and code(r) == "PASSWORD_CHANGE_REQUIRED", (r.status_code, code(r)))
        r = call(user, "get", "/api/app-context"); check("forced user: app-context still works and shows the flag", r.status_code == 200 and r.json()["principal"]["mustChangePassword"] is True)
        check("forced user: csrf endpoint still works", user.get("/api/auth/csrf").status_code == 200)

        # --- 改密碼 ---
        r = call(user, "post", "/api/auth/change-password", {"currentPassword": "wrong-Pass-9", "newPassword": NEW}); check("wrong current password -> 400", code(r) == "INVALID_CURRENT_PASSWORD")
        r = call(user, "post", "/api/auth/change-password", {"currentPassword": OLD, "newPassword": "short1"}); check("weak new password -> 400 WEAK_PASSWORD", code(r) == "WEAK_PASSWORD")
        r = call(user, "post", "/api/auth/change-password", {"currentPassword": OLD, "newPassword": OLD}); check("new password equal to the temporary one -> 400 PASSWORD_UNCHANGED", code(r) == "PASSWORD_UNCHANGED")
        tgt.refresh_from_db(); check("failed attempts keep the flag", tgt.must_change_password)
        check("still blocked after failed attempts", code(call(user, "get", "/api/cases")) == "PASSWORD_CHANGE_REQUIRED")
        r = call(user, "post", "/api/auth/change-password", {"currentPassword": OLD, "newPassword": NEW}); j = r.json()
        tgt.refresh_from_db()
        check("valid change -> 200, principal.mustChangePassword=false, flag cleared in DB", r.status_code == 200 and j["principal"]["mustChangePassword"] is False and not tgt.must_change_password, (r.status_code, j))
        check("same session works right away (200 on business APIs)", call(user, "get", "/api/cases").status_code == 200 and call(user, "get", "/api/personnel-options").status_code == 200)
        check("old password no longer works, new one does", login("zz.pw2.user", OLD)[1].status_code == 401 and login("zz.pw2.user", NEW)[1].json()["principal"]["mustChangePassword"] is False)
        check("changing the password did not touch row_version / audit", tgt.row_version == 2 and not AuditLog.objects.filter(entity_type="personnel", entity_id=str(tgt.pk), action="change_password").exists())

        # --- 重設密碼 → 再次強制 ---
        r = call(admin, "post", "/api/personnel-accounts/reset-password", {"personnelId": tgt.pk}); j = r.json(); tgt.refresh_from_db()
        check("reset password marks mustChangePassword again", r.status_code == 200 and tgt.must_change_password)
        check("reset ended the old session", call(user, "get", "/api/app-context").status_code == 401)
        u2, r = login("zz.pw2.user", j["newPassword"])
        check("new (generated) password: login ok but business APIs blocked", r.status_code == 200 and code(call(u2, "get", "/api/cases")) == "PASSWORD_CHANGE_REQUIRED")
        r = call(u2, "post", "/api/auth/change-password", {"currentPassword": j["newPassword"], "newPassword": NEWER}); check("...then changing it frees the account", r.status_code == 200 and call(u2, "get", "/api/cases").status_code == 200)
        ev = AuditLog.objects.filter(entity_type="personnel", entity_id=str(tgt.pk), action="reset_account_password").first()
        check("audit of the reset records mustChangePassword, never the password", ev.metadata.get("mustChangePassword") is True and j["newPassword"] not in json.dumps([ev.metadata, ev.after_data]))

        # --- 停用 → 重新啟用 ---
        r = call(admin, "post", "/api/personnel-accounts/disable", {"personnelId": tgt.pk}); check("disable works", r.status_code == 200)
        tgt.refresh_from_db(); v_before = tgt.row_version
        check("disabled: cannot log in", login("zz.pw2.user", NEWER)[1].status_code == 401)
        r = call(admin, "post", "/api/personnel-accounts/enable", {"personnelId": tgt.pk}); j = r.json(); tgt.refresh_from_db(); usr = User.objects.get(pk=int(tgt.auth_user_id))
        check("enable -> 200, status active, flag set, disabled_* cleared, Django user active again, row_version +1",
              r.status_code == 200 and tgt.account_status == "active" and tgt.must_change_password and tgt.account_disabled_at is None and tgt.account_disabled_by is None
              and usr.is_active and tgt.row_version == v_before + 1 and j["person"]["accountStatus"] == "active" and j["person"]["accountMustChangePassword"] is True, (r.status_code, j))
        ev = AuditLog.objects.filter(entity_type="personnel", entity_id=str(tgt.pk), action="enable_account").first()
        check("audit enable_account: before disabled -> after active, actor is the admin, no password",
              ev and ev.before_data["accountStatus"] == "disabled" and ev.after_data["accountStatus"] == "active" and ev.actor_id == f"personnel:{ap.pk}"
              and ev.metadata["mustChangePassword"] is True and NEWER not in json.dumps([ev.metadata, ev.before_data, ev.after_data]))
        check("snapshot personnel_account_enabled", EntitySnapshot.objects.filter(entity_type="personnel", entity_id=str(tgt.pk), snapshot_reason="personnel_account_enabled", entity_version=tgt.row_version).count() == 1)
        u3, r = login("zz.pw2.user", NEWER)
        check("re-enabled: the OLD password still works (no new secret issued) but business APIs are blocked", r.status_code == 200 and r.json()["principal"]["mustChangePassword"] is True and code(call(u3, "get", "/api/cases")) == "PASSWORD_CHANGE_REQUIRED")
        r = call(u3, "post", "/api/auth/change-password", {"currentPassword": NEWER, "newPassword": OLD + "x"}); check("...and after changing the password it is usable again", r.status_code == 200 and call(u3, "get", "/api/cases").status_code == 200)

        # --- 啟用的限制 ---
        def enable(pid): return call(admin, "post", "/api/personnel-accounts/enable", {"personnelId": pid})
        r = enable(tgt.pk); check("enable an already-active account -> 409 not_disabled", r.status_code == 409 and code(r) == "not_disabled")
        none = person("viewer", "business_1"); r = enable(none.pk); check("enable a person without an account -> 409 no_account", r.status_code == 409 and code(r) == "no_account")
        gone = person("viewer", "business_1"); direct_account(gone, "zz.pw2.gone", "Gone-Pass-1234")
        call(admin, "post", "/api/personnel-accounts/disable", {"personnelId": gone.pk}); Personnel.objects.filter(pk=gone.pk).update(is_active=False, deactivated_by="t", deactivated_at="2026-01-01T00:00:00Z")
        r = enable(gone.pk); check("enable while the Personnel record is inactive -> 409 personnel_inactive", r.status_code == 409 and code(r) == "personnel_inactive")
        check("...and nothing changed for them", Personnel.objects.get(pk=gone.pk).account_status == "disabled" and not User.objects.get(username="zz.pw2.gone").is_active)
        check("enable unknown person -> 404", enable(99999999).status_code == 404 and code(enable(99999999)) == "personnel_not_found")
        r = call(admin, "post", "/api/personnel-accounts/enable", {}); check("enable without personnelId -> 400", r.status_code == 400)
        check("enable requires login (401)", call(new_client(), "post", "/api/personnel-accounts/enable", {"personnelId": tgt.pk}).status_code == 401)
        r = call(u3, "post", "/api/personnel-accounts/enable", {"personnelId": tgt.pk}); check("enable requires accounts.manage (sales -> 403)", r.status_code == 403 and code(r) == "PERMISSION_DENIED")
        gm = person("general_manager", "reinsurance"); direct_account(gm, "zz.pw2.gm", "Gm-Long-Pass-123"); gmc, _ = login("zz.pw2.gm", "Gm-Long-Pass-123")
        rows = call(gmc, "get", "/api/personnel").json()["personnel"]
        check("accountMustChangePassword visible only with accounts.manage", all("accountMustChangePassword" not in x for x in rows)
              and all("accountMustChangePassword" in x for x in call(admin, "get", "/api/personnel").json()["personnel"]))
        check("General Manager cannot enable (403)", call(gmc, "post", "/api/personnel-accounts/enable", {"personnelId": tgt.pk}).status_code == 403)

        # --- CLI ---
        def cli(name, **kw):
            out = io.StringIO(); call_command(name, stdout=out, **kw); return out.getvalue()
        cp = person("viewer", "business_2")
        out = cli("create_ri_account", personnel_id=cp.pk, username="zz.pw2.cli", email=""); cp.refresh_from_db()
        check("CLI create_ri_account also marks mustChangePassword", cp.must_change_password and "required to change" in out)
        Personnel.objects.filter(pk=cp.pk).update(must_change_password=False)
        cli("reset_ri_password", personnel_id=cp.pk); cp.refresh_from_db(); check("CLI reset_ri_password marks mustChangePassword", cp.must_change_password)
        cli("disable_ri_account", personnel_id=cp.pk); Personnel.objects.filter(pk=cp.pk).update(must_change_password=False)
        out = cli("enable_ri_account", personnel_id=cp.pk); cp.refresh_from_db()
        check("CLI enable_ri_account re-enables and marks mustChangePassword", cp.account_status == "active" and cp.must_change_password and "re-enabled" in out)
        ev = AuditLog.objects.filter(entity_type="personnel", entity_id=str(cp.pk), action="enable_account").first(); check("CLI enable is audited with source=cli", ev and ev.source == "cli" and ev.actor_id == "cli")
        try:
            cli("enable_ri_account", personnel_id=cp.pk); check("CLI enable on an active account fails", False)
        except Exception as e:
            check("CLI enable on an active account fails with a clear message", "not disabled" in str(e), e)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ users =", User.objects.filter(username__startswith="zz").count() + User.objects.filter(username="pw2_admin").count())
