import json
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from personnel.accounts import generate_password
from personnel.models import Personnel
User = get_user_model(); results = []

# 測試自己建立臨時人員（在會回滾的交易內），不挑用真實資料：真實人員被建了帳號或改名都不影響測試
_DEPT = {"admin": "admin", "sales": "reinsurance", "accounting": "finance", "accounting_manager": "finance",
         "general_manager": "reinsurance", "viewer": "business_1"}
_seq = [0]
def pick(role):
    _seq[0] += 1
    return Personnel.objects.create(name=f"ZZ T {role} {_seq[0]}", department=_DEPT[role], role_code=role, created_by="t", updated_by="t")
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def csrf(c): c.get("/api/auth/csrf"); return c.cookies["csrftoken"].value
def call(c, m, url, body): return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
def login(u, p):
    c = new_client(); cache.clear(); t = csrf(c)
    return c, c.post("/api/auth/login", data=json.dumps({"username": u, "password": p}), content_type="application/json", HTTP_X_CSRFTOKEN=t)

# 系統產生的密碼永遠符合規則
bad = 0
for _ in range(2000):
    try: validate_password(generate_password())
    except Exception: bad += 1
check("2000 system-generated passwords all satisfy the rule", bad == 0, bad)

try:
    with transaction.atomic():
        p = pick("viewer")
        u = User.objects.create_user(username="pr_user", password="Start-Pass-1234")
        p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
        c, r = login("pr_user", "Start-Pass-1234"); assert r.status_code == 200
        def chg(new, cur="Start-Pass-1234"): return call(c, "post", "/api/auth/change-password", {"currentPassword": cur, "newPassword": new})
        for label, pw, needle in [("letters only", "abcdefgh", "英文字母與數字"), ("digits only", "12345678", "英文字母與數字"),
                                  ("symbols + digits", "!!!!1111", "英文字母與數字"), ("too short", "Abc12", "至少 8 個字元")]:
            r = chg(pw); j = r.json()
            check(f"change-password rejects {label} with a readable message", r.status_code == 400 and j["error"] == "WEAK_PASSWORD" and needle in j["message"], j)
        r = chg("Abcd1234")
        check("'Abcd1234' (letters+digits, 8 chars) is accepted now", r.status_code == 200, r.content[:80])
        check("and the new password works for login", login("pr_user", "Abcd1234")[1].status_code == 200)
        # 管理員建立帳號時指定的密碼用同一條規則
        admin_p = pick("admin")
        au = User.objects.create_user(username="pr_admin", password="Admin-Pass-1234")
        admin_p.auth_user_id = str(au.pk); admin_p.account_status = "active"; admin_p.save()
        ac, r = login("pr_admin", "Admin-Pass-1234"); assert r.status_code == 200
        t2 = Personnel.objects.create(name="ZZ Rule", department="business_1", role_code="viewer", created_by="t", updated_by="t")
        r = call(ac, "post", "/api/personnel-accounts", {"personnelId": t2.pk, "username": "zz.rule", "initialPassword": "onlyletters"})
        check("admin-set password without a digit is rejected with the same message", r.status_code == 400 and "英文字母與數字" in r.json()["message"], r.content[:100])
        r = call(ac, "post", "/api/personnel-accounts", {"personnelId": t2.pk, "username": "zz.rule", "initialPassword": "Abcd1234"})
        check("admin-set 'Abcd1234' is accepted", r.status_code == 201, r.content[:100])
        raise Rollback()
except Rollback:
    pass
f = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(f)}/{len(results)} passed; rolled back")
