import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
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

# 預期表（獨立寫死，不引用 ROLE_PERMISSIONS）: (fx_read, fx_write, mdm_read, mdm_write)
EXPECT = {
    "admin": (1, 1, 1, 1),
    "sales": (1, 0, 1, 1),
    "accounting": (1, 0, 0, 0),
    "accounting_manager": (1, 1, 0, 0),
    "general_manager": (1, 0, 1, 1),
    "viewer": (0, 0, 0, 0),
}


def new_client():
    return Client(enforce_csrf_checks=True, HTTP_HOST="localhost")


def csrf(c):
    c.get("/api/auth/csrf")
    return c.cookies["csrftoken"].value


def post(c, url, body, token=None):
    return c.post(url, data=json.dumps(body), content_type="application/json",
                  HTTP_X_CSRFTOKEN=token or c.cookies["csrftoken"].value)


def login(c, username, password=PW):
    cache.clear()  # 避免測試中途被限流；限流本身在最後單獨測
    token = csrf(c)
    return post(c, "/api/auth/login", {"username": username, "password": password}, token)


def make_account(person, username):
    u = User.objects.create_user(username=username, password=PW)
    person.auth_user_id = str(u.pk)
    person.account_status = "active"
    person.save()
    return u


def code(resp):
    try:
        return resp.json().get("error")
    except Exception:
        return None


try:
    with transaction.atomic():
        # ---- 匿名 ----
        c = new_client()
        for url in ("/api/fx-rates", "/api/master-data", "/api/app-context"):
            r = c.get(url)
            check(f"anonymous GET {url} -> 401", r.status_code == 401 and code(r) == "AUTHENTICATION_REQUIRED", r.status_code)
        check("anonymous /health/ stays public", c.get("/health/").status_code == 200)

        # ---- CSRF ----
        c = new_client(); csrf(c)
        r = c.post("/api/auth/login", data=json.dumps({"username": "x", "password": "y"}), content_type="application/json")
        check("login without CSRF token -> 403", r.status_code == 403, r.status_code)

        # ---- 六個角色 ----
        for role, (fr, fw, mr, mw) in EXPECT.items():
            person = pick(role)
            if person is None:
                check(f"[{role}] has a Personnel row to test with", False); continue
            make_account(person, f"t_{role}")
            c = new_client()
            bad = login(c, f"t_{role}", "wrong-password-123")
            check(f"[{role}] wrong password -> 401 INVALID_CREDENTIALS", bad.status_code == 401 and code(bad) == "INVALID_CREDENTIALS")
            ok = login(c, f"t_{role}")
            check(f"[{role}] login ok", ok.status_code == 200 and ok.json()["principal"]["roleCode"] == role, ok.status_code)
            ctx = c.get("/api/app-context")
            check(f"[{role}] app-context 200 and role matches", ctx.status_code == 200 and ctx.json()["principal"]["roleCode"] == role)

            def expect(resp, allowed, okcodes):
                return (resp.status_code in okcodes) if allowed else (resp.status_code == 403 and code(resp) == "PERMISSION_DENIED")

            check(f"[{role}] GET fx-rates {'allowed' if fr else 'denied'}", expect(c.get("/api/fx-rates"), fr, (200,)))
            check(f"[{role}] POST fx-rates {'allowed' if fw else 'denied'}", expect(post(c, "/api/fx-rates", {"yearMonth": "bad"}), fw, (400,)))
            check(f"[{role}] GET master-data {'allowed' if mr else 'denied'}", expect(c.get("/api/master-data"), mr, (200,)))
            check(f"[{role}] POST master-data {'allowed' if mw else 'denied'}", expect(post(c, "/api/master-data", {"entityType": "zzz"}), mw, (400,)))
            put = c.put("/api/master-data", data=json.dumps({}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
            check(f"[{role}] PUT master-data {'allowed' if mw else 'denied'}", expect(put, mw, (400,)))
            check(f"[{role}] DELETE master-data always denied", c.delete("/api/master-data", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value).status_code in (403, 405))

            if role == "sales":
                # 實際寫入一筆，確認操作者是登入者本人（不是固定值 vm-system）
                w = post(c, "/api/master-data", {"entityType": "class", "name": "ZZ Authz Test Class"})
                from masterdata.models import MasterRecord
                rec = MasterRecord.objects.filter(name="ZZ Authz Test Class").first()
                check("[sales] real write attributed to the logged-in person",
                      w.status_code == 201 and rec and rec.created_by == f"personnel:{person.pk}", getattr(rec, "created_by", None))
            if role == "accounting_manager":
                fxw = post(c, "/api/fx-rates", {"yearMonth": "2099-01", "rates": [
                    {"currency": cur, "rate": 1.5} for cur in ("USD", "EUR", "JPY", "GBP", "HKD", "MYR")]})
                from fxrates.models import FxRate
                row = FxRate.objects.filter(year_month="2099-01").first()
                check("[accounting_manager] real FX write attributed to the logged-in person",
                      fxw.status_code == 200 and row and row.created_by == f"personnel:{person.pk}", getattr(row, "created_by", None))

            out = post(c, "/api/auth/logout", {})
            check(f"[{role}] logout ok", out.status_code == 200)
            check(f"[{role}] after logout GET fx-rates -> 401", c.get("/api/fx-rates").status_code == 401)

        # ---- 異常情境 ----
        p = pick("viewer")
        u = make_account(p, "t_edge")
        c = new_client()
        p.account_status = "disabled"; p.save()
        r = login(c, "t_edge")
        check("account_status=disabled -> 403 ACCOUNT_INACTIVE (no session)", r.status_code == 403 and code(r) == "ACCOUNT_INACTIVE" and c.get("/api/app-context").status_code == 401)
        p.account_status = "active"; p.is_active = False; p.deactivated_by = "t"; p.deactivated_at = "2026-01-01T00:00:00Z"; p.save()
        r = login(c, "t_edge")
        check("personnel inactive -> 403 PERSONNEL_INACTIVE", r.status_code == 403 and code(r) == "PERSONNEL_INACTIVE")
        p.is_active = True; p.deactivated_by = None; p.deactivated_at = None; p.save()
        u.is_active = False; u.save()
        r = login(c, "t_edge")
        check("Django user inactive -> 401", r.status_code == 401)
        u.is_active = True; u.save()
        orphan = User.objects.create_user(username="t_orphan", password=PW)
        r = login(new_client(), "t_orphan")
        check("account not linked to Personnel -> 403 PERSONNEL_NOT_LINKED", r.status_code == 403 and code(r) == "PERSONNEL_NOT_LINKED")

        # 已登入後，人員被停用 -> 既有 session 立刻失效（不需等 session 過期）
        c = new_client()
        r = login(c, "t_edge")
        check("re-login after fix ok", r.status_code == 200)
        p.is_active = False; p.deactivated_by = "t"; p.deactivated_at = "2026-01-01T00:00:00Z"; p.save()
        check("live session is refused once personnel is deactivated", c.get("/api/app-context").status_code == 403)
        p.is_active = True; p.deactivated_by = None; p.deactivated_at = None; p.save()

        # ---- 改密碼 ----
        c = new_client(); login(c, "t_edge")
        r = post(c, "/api/auth/change-password", {"currentPassword": "nope", "newPassword": "Another-Long-Pass-77"})
        check("change-password wrong current -> 400", r.status_code == 400 and code(r) == "INVALID_CURRENT_PASSWORD")
        r = post(c, "/api/auth/change-password", {"currentPassword": PW, "newPassword": "short1"})
        check("change-password too short -> 400 WEAK_PASSWORD", r.status_code == 400 and code(r) == "WEAK_PASSWORD")
        r = post(c, "/api/auth/change-password", {"currentPassword": PW, "newPassword": "Another-Long-Pass-77"})
        check("change-password ok and stays logged in", r.status_code == 200 and c.get("/api/app-context").status_code == 200)
        check("old password no longer works", login(new_client(), "t_edge", PW).status_code == 401)
        check("new password works", login(new_client(), "t_edge", "Another-Long-Pass-77").status_code == 200)

        # ---- 限流 ----
        cache.clear()
        c = new_client(); token = csrf(c)
        codes = [post(c, "/api/auth/login", {"username": "t_edge", "password": "bad"}, token).status_code for _ in range(12)]
        check("login throttling kicks in (429) after repeated failures", 429 in codes, codes)
        cache.clear()

        raise Rollback()
except Rollback:
    pass

width = max(len(n) for n, _, _ in results)
fails = 0
for n, ok, d in results:
    if not ok:
        fails += 1
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-fails}/{len(results)} passed; database changes rolled back")

from personnel.models import Personnel as P
print("personnel with accounts after rollback:", P.objects.exclude(auth_user_id__isnull=True).count(),
      "| users:", User.objects.count())
