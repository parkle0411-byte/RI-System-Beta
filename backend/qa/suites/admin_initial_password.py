import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import AuditLog
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
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass

def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def csrf(c): c.get("/api/auth/csrf"); return c.cookies["csrftoken"].value
def call(c, m, url, body=None):
    kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def login(u, p):
    c = new_client(); cache.clear(); t = csrf(c)
    return c, c.post("/api/auth/login", data=json.dumps({"username": u, "password": p}), content_type="application/json", HTTP_X_CSRFTOKEN=t)
def code(r):
    try: return r.json().get("error")
    except Exception: return None

try:
    with transaction.atomic():
        ap = pick("admin")
        au = User.objects.create_user(username="pw_admin", password="Admin-Long-Pass-1")
        ap.auth_user_id = str(au.pk); ap.account_status = "active"; ap.save()
        admin, r = login("pw_admin", "Admin-Long-Pass-1"); assert r.status_code == 200

        tgt = Personnel.objects.create(name="ZZ Pw", department="business_1", role_code="viewer", created_by="t", updated_by="t")
        users_before = User.objects.count()
        def make(pw=..., username="zz.pw.user", **extra):
            body = {"personnelId": tgt.pk, "username": username, **extra}
            if pw is not ...: body["initialPassword"] = pw
            return call(admin, "post", "/api/personnel-accounts", body)

        # --- 不合格的密碼一律 400，且什麼都沒建立 ---
        for label, pw in [("too short", "Ab1!xyz"), ("very common", "password"), ("all digits", "12345678"),
                          ("blank (spaces)", " " * 10), ("too long", "Aa1!" * 40), ("same as username", "zz.pw.user")]:
            r = make(pw)
            check(f"weak password rejected ({label}) -> 400 weak_password", r.status_code == 400 and code(r) == "weak_password", (r.status_code, code(r), r.content[:80]))
        tgt.refresh_from_db()
        check("rejected attempts created nothing (no user, person still unbound)", User.objects.count() == users_before and tgt.auth_user_id is None and tgt.account_status == "not_configured")

        # --- 管理員指定的密碼 ---
        good = "Tw!nsur3-Start-9"
        r = make(good); j = r.json()
        check("admin-set password -> 201, source=admin", r.status_code == 201 and j["passwordSource"] == "admin", (r.status_code, j))
        check("admin-set password is NOT echoed back anywhere in the response", "initialPassword" not in j and good not in r.content.decode())
        uc, lr = login("zz.pw.user", good)
        check("the person can log in with the admin-set password", lr.status_code == 200 and lr.json()["principal"]["roleCode"] == "viewer")
        check("person shows an active account", j["person"]["accountStatus"] == "active" and j["person"]["accountUsername"] == "zz.pw.user")
        ev = AuditLog.objects.filter(entity_type="personnel", entity_id=str(tgt.pk), action="create_account").first()
        check("audit records passwordSource=admin", ev.metadata.get("passwordSource") == "admin")

        # --- 留空 / 不填 = 系統產生（維持原行為） ---
        for label, kw in (("empty string", {"pw": ""}), ("field omitted", {})):
            other = Personnel.objects.create(name=f"ZZ Pw {label}", department="business_1", role_code="viewer", created_by="t", updated_by="t")
            uname = "zz.gen." + label.split()[0]
            body = {"personnelId": other.pk, "username": uname}
            if "pw" in kw: body["initialPassword"] = kw["pw"]
            r = call(admin, "post", "/api/personnel-accounts", body); j = r.json()
            gen = j.get("initialPassword", "")
            check(f"blank initialPassword ({label}) -> system generated and returned once", r.status_code == 201 and j["passwordSource"] == "generated" and len(gen) >= 16, r.status_code)
            check(f"generated password works ({label})", login(uname, gen)[1].status_code == 200)
            e2 = AuditLog.objects.filter(entity_type="personnel", entity_id=str(other.pk), action="create_account").first()
            check(f"audit records passwordSource=generated ({label})", e2.metadata.get("passwordSource") == "generated")
            good_all = gen

        # --- 稽核裡不可能出現任何密碼 ---
        dump = json.dumps(list(AuditLog.objects.values("before_data", "after_data", "metadata")), default=str)
        check("no password (admin-set or generated) appears in the audit trail", good not in dump and good_all not in dump and "pbkdf2" not in dump)

        # --- 其他規則不受影響 ---
        r = call(admin, "post", "/api/personnel-accounts", {"personnelId": tgt.pk, "username": "again.user", "initialPassword": good})
        check("second account for the same person still refused (409)", r.status_code == 409 and code(r) == "account_exists")
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: users =", User.objects.count(), "| ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count())
