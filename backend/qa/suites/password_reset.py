import json
import re
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.db import transaction
from django.test import Client, override_settings
from audit.models import AuditLog
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None, clear=True):
    if clear: cache.clear()   # 限流用 cache 計數；一般測試每次先清掉，限流測試才累積
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def code(r):
    try: return r.json().get("error")
    except Exception: return None
def person(name, email="zz.pr@tw-insure.com", username=None, role="sales", **kw):
    p = Personnel.objects.create(name=name, department="reinsurance", role_code=role, email=email, created_by="t", updated_by="t", **kw)
    if username:
        u = User.objects.create_user(username=username, password="Old-Pass-Word-1")
        p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    return p
def login(c, username, password):
    return call(c, "post", "/api/auth/login", {"username": username, "password": password})
def links(): return [re.search(r"http://[^\s\"<>]+/reset-password\?uid=([^&\s]+)&amp;token=([^\s\"<]+)|http://[^\s\"<>]+/reset-password\?uid=([^&\s]+)&token=([^\s\"<]+)", m.body) for m in mail.outbox]
def link_parts(m):
    g = re.search(r"/reset-password\?uid=([^&\s]+)&token=([^\s\"<]+)", m.body)
    return (g.group(1), g.group(2)) if g else (None, None)
R = "/api/auth/password-reset"
C = "/api/auth/password-reset/confirm"
GENERIC = "If the account exists and has an e-mail address, a password reset link has been sent. The link is valid for 1 hour."

try:
    with transaction.atomic():
        anon = new_client()
        # ================= 寄信未啟用（VM 目前的狀態） =================
        with override_settings(EMAIL_ENABLED=False):
            check("email disabled: GET says enabled false (login page hides the link)", call(anon, "get", R).json() == {"enabled": False})
            r = call(anon, "post", R, {"identifier": "anyone"})
            check("email disabled: POST -> 503 password_reset_unavailable", r.status_code == 503 and code(r) == "password_reset_unavailable")

        with override_settings(EMAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", PUBLIC_BASE_URL="http://ri.example",
                               DEFAULT_FROM_EMAIL="ri@tw-insure.com"):
            p = person("ZZ PR Amy", email="ZZ.Amy@tw-insure.com", username="zz.pr.amy")
            person("ZZ PR NoMail", email=None, username="zz.pr.nomail")
            off = person("ZZ PR Disabled", email="zz.off@tw-insure.com", username="zz.pr.off"); off.account_status = "disabled"; off.save()
            gone = person("ZZ PR Left", email="zz.left@tw-insure.com", username="zz.pr.left"); gone.is_active = False; gone.deactivated_by = "t"; gone.deactivated_at = __import__("django.utils.timezone", fromlist=["x"]).now(); gone.save()
            check("email enabled: GET says enabled true", call(anon, "get", R).json() == {"enabled": True})

            mail.outbox = []
            for label, ident in (("unknown username", "zz.nobody"), ("unknown e-mail", "nobody@tw-insure.com"), ("account without e-mail", "zz.pr.nomail"),
                                 ("disabled account", "zz.pr.off"), ("inactive personnel", "zz.pr.left"),
                                 ("empty", "")):
                r = call(anon, "post", R, {"identifier": ident})
                check(f"{label}: same generic answer, no e-mail", r.status_code == 200 and r.json()["message"] == GENERIC and not mail.outbox, (r.status_code, len(mail.outbox)))

            r = call(anon, "post", R, {"identifier": "  ZZ.PR.AMY "})
            m = mail.outbox[-1] if mail.outbox else None
            check("username (any case, trimmed) -> generic answer and one e-mail to the Personnel address", r.status_code == 200 and r.json()["message"] == GENERIC
                  and len(mail.outbox) == 1 and m.to == ["ZZ.Amy@tw-insure.com"] and m.from_email == "ri@tw-insure.com", [x.to for x in mail.outbox])
            uid, token = link_parts(m) if m else (None, None)
            check("e-mail: subject, link to the VM reset page, 1-hour notice, HTML part", m and m.subject == "[Reinsurance Department System] 重設密碼 Password reset"
                  and "http://ri.example/reset-password?uid=" in m.body and uid and token and "1 小時" in m.body and m.alternatives, m and m.body[:200])
            a = AuditLog.objects.filter(entity_type="personnel", entity_id=str(p.pk), action="request_password_reset").first()
            check("audit request_password_reset without the link or token", a and a.metadata == {"username": "zz.pr.amy", "emailSent": True} and token not in json.dumps(a.after_data) + json.dumps(a.metadata))
            mail.outbox = []
            call(anon, "post", R, {"identifier": "zz.amy@TW-INSURE.com"})
            check("e-mail address (any case) also works", len(mail.outbox) == 1 and mail.outbox[0].to == ["ZZ.Amy@tw-insure.com"])

            # ---------- 設定新密碼 ----------
            other = new_client(); check("another device is logged in with the old password", login(other, "zz.pr.amy", "Old-Pass-Word-1").status_code == 200)
            r = call(anon, "post", C, {"uid": uid, "token": token, "newPassword": "New-Pass-Word-9"})
            check("a login after the request invalidates the earlier link (Django token includes last login)", r.status_code == 400 and code(r) == "invalid_reset_link")
            mail.outbox = []
            call(anon, "post", R, {"identifier": "zz.pr.amy"})
            uid, token = link_parts(mail.outbox[-1])
            r = call(anon, "post", C, {"uid": uid, "token": "x-bad", "newPassword": "New-Pass-Word-9"})
            check("wrong token -> 400 invalid_reset_link", r.status_code == 400 and code(r) == "invalid_reset_link")
            r = call(anon, "post", C, {"uid": "!!", "token": token, "newPassword": "New-Pass-Word-9"})
            check("malformed uid -> 400 invalid_reset_link", r.status_code == 400 and code(r) == "invalid_reset_link")
            r = call(anon, "post", C, {"uid": uid, "token": token, "newPassword": "short"})
            check("weak password -> 400 WEAK_PASSWORD (same rule as Change password)", r.status_code == 400 and code(r) == "WEAK_PASSWORD")
            Personnel.objects.filter(pk=p.pk).update(must_change_password=True)
            r = call(anon, "post", C, {"uid": uid, "token": token, "newPassword": "New-Pass-Word-9"})
            check("valid link + strong password -> 200", r.status_code == 200 and r.json()["ok"] is True, r.content[:200])
            check("new password works, old one does not", login(new_client(), "zz.pr.amy", "New-Pass-Word-9").status_code == 200
                  and login(new_client(), "zz.pr.amy", "Old-Pass-Word-1").status_code == 401)
            check("other logged-in sessions were ended", call(other, "get", "/api/app-context").status_code == 401)
            p.refresh_from_db()
            check("must_change_password cleared (the person chose it)", p.must_change_password is False)
            a = AuditLog.objects.filter(entity_type="personnel", entity_id=str(p.pk), action="reset_own_password").first()
            check("audit reset_own_password by the person, no password", a and a.actor_id == f"personnel:{p.pk}" and a.metadata["via"] == "email_link"
                  and a.metadata["mustChangePasswordCleared"] is True and a.metadata["sessionsEnded"] >= 1 and "New-Pass-Word-9" not in json.dumps(a.after_data) + json.dumps(a.metadata), a and a.metadata)
            r = call(anon, "post", C, {"uid": uid, "token": token, "newPassword": "Another-Pass-7"})
            check("the same link cannot be used twice", r.status_code == 400 and code(r) == "invalid_reset_link")

            # ---------- 過期 ----------
            mail.outbox = []
            call(anon, "post", R, {"identifier": "zz.pr.amy"})
            uid2, token2 = link_parts(mail.outbox[-1])
            real_now = default_token_generator._now
            default_token_generator._now = lambda: real_now() + timedelta(seconds=3601)
            try:
                r = call(anon, "post", C, {"uid": uid2, "token": token2, "newPassword": "Later-Pass-Word-3"})
            finally:
                default_token_generator._now = real_now
            check("link older than 1 hour -> 400 invalid_reset_link", r.status_code == 400 and code(r) == "invalid_reset_link")
            off_user = User.objects.get(username="zz.pr.off")
            r = call(anon, "post", C, {"uid": __import__("django.utils.http", fromlist=["x"]).urlsafe_base64_encode(str(off_user.pk).encode()),
                                       "token": default_token_generator.make_token(off_user), "newPassword": "Later-Pass-Word-3"})
            check("a valid token for a disabled account is refused", r.status_code == 400 and code(r) == "invalid_reset_link")

            # ---------- 限流 ----------
            cache.clear()
            codes = [call(anon, "post", R, {"identifier": "zz.nobody"}, clear=False).status_code for _ in range(7)]
            check("request is rate limited (5 per minute) -> 429", codes[:5] == [200] * 5 and 429 in codes[5:], codes)
            cache.clear()
        raise Rollback()
except Rollback:
    pass
cache.clear()
fails = [x for x in results if not x[1]]
for n, ok, dd in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {dd}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ PR").count())
