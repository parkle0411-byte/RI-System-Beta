import json
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case, CaseDocument, ReferenceSequence
from fxrates.models import FxRate
from masterdata.models import MasterRecord
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept, **kw):
    _seq[0] += 1
    return Personnel.objects.create(name=f"ZZ AD {role} {_seq[0]}", department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def account(p, tag, **flags):
    u = User.objects.create_user(username=f"zz.ad.{tag}", password="Admin-View-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"
    for k, v in flags.items(): setattr(p, k, v)
    p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Admin-View-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def csrf_post(c, url, data=None):
    c.get("/api/auth/csrf"); return c.post(url, data=data or {}, HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)

try:
    with transaction.atomic():
        admin_p = person("admin", "admin")
        sales_p, gm_p, view_p, acct_p = person("sales", "reinsurance"), person("general_manager", "reinsurance"), person("viewer", "business_1"), person("accounting", "finance")
        forced_p = person("admin", "admin")
        adm = account(admin_p, "admin")
        others = {"sales": account(sales_p, "sales"), "general_manager": account(gm_p, "gm"), "viewer": account(view_p, "view"), "accounting": account(acct_p, "acct")}
        forced = account(forced_p, "forced", must_change_password=True)

        # 合成資料：每一種模型至少一筆
        case = Case.objects.create(case_kind="original", status="draft", tw_ref="ZZ-AD-1", reinsured_name_snapshot="ZZ Cedant", currency="USD",
                                   payload={"originalInsured": "ZZ 中文 Insured", "reinsurers": [{"name": "ZZ Re"}]}, created_by="t", updated_by="t", owner_personnel=sales_p)
        CaseDocument.objects.create(case=case, kind="offer", filename="zz.pdf", content_type="application/pdf", byte_size=10, sha256="0" * 64, storage_key="zz-ad-key", uploaded_by="t")
        seq, _ = ReferenceSequence.objects.get_or_create(prefix="ZZ-AD", defaults={"last_value": 1})
        master = MasterRecord.objects.create(entity_type="ae", name="ZZ AD Master", created_by="t", updated_by="t", payload={"abbreviation": "ZM"})
        fx = FxRate.objects.create(year_month="1999-01", currency="USD", rate="30.5", created_by="t", updated_by="t")
        audit = AuditLog.objects.create(entity_type="case", entity_id="zz-ad", action="create_draft", after_data={"k": "中文"}, actor_id="t", retention_until="2100-01-01T00:00:00Z")
        snap = EntitySnapshot.objects.create(entity_type="case", entity_id="zz-ad", entity_version=1, snapshot_reason="draft_created", snapshot_data={"k": 1}, created_by="t")

        # --- 進入條件 ---
        r = Client(HTTP_HOST="localhost").get("/admin/")
        check("anonymous /admin/ -> redirect to /admin/login/", r.status_code == 302 and r["Location"].startswith("/admin/login/"), (r.status_code, r.get("Location")))
        r = Client(HTTP_HOST="localhost").get("/admin/login/?next=/admin/cases/case/")
        check("anonymous /admin/login/ -> the SPA login page, remembering the target", r.status_code == 302 and r["Location"] == "/login?redirect=/admin/cases/case/", r.get("Location"))
        r = Client(HTTP_HOST="localhost").get("/admin/login/?next=https://evil.example/x")
        check("login redirect target must stay under /admin/ (no open redirect)", r["Location"] == "/login?redirect=/admin/", r.get("Location"))
        for role, c in others.items():
            r = c.get("/admin/", follow=True)
            check(f"{role} cannot use the admin site (final status 403)", r.status_code == 403, r.status_code)
            check(f"{role}: a data page is refused too", c.get("/admin/cases/case/", follow=True).status_code == 403)
        r = forced.get("/admin/", follow=True); check("admin who must change the password first -> refused", r.status_code == 403, r.status_code)
        r = adm.get("/admin/"); check("System Administrator -> 200", r.status_code == 200, r.status_code)
        Personnel.objects.filter(pk=admin_p.pk).update(is_active=False, deactivated_by="t", deactivated_at="2026-01-01T00:00:00Z")
        check("admin whose Personnel record became inactive -> refused", adm.get("/admin/", follow=True).status_code == 403)
        Personnel.objects.filter(pk=admin_p.pk).update(is_active=True, deactivated_by=None, deactivated_at=None)
        Personnel.objects.filter(pk=admin_p.pk).update(account_status="disabled")
        check("admin whose account is disabled -> refused", adm.get("/admin/", follow=True).status_code == 403)
        Personnel.objects.filter(pk=admin_p.pk).update(account_status="active")
        check("...and allowed again once restored", adm.get("/admin/").status_code == 200)

        # --- 註冊了什麼 ---
        registered = {m.__name__ for m in admin.site._registry}
        check("exactly the 9 RI models are registered", registered == {"Case", "CaseDocument", "ReferenceSequence", "DraftRecycleBin", "Personnel", "MasterRecord", "FxRate", "AuditLog", "EntitySnapshot"}, registered)
        check("Django User / Group (password hashes) are NOT registered", User not in admin.site._registry and "Group" not in registered)
        try: admin.site.register(User, admin.ModelAdmin)
        except Exception: pass
        check("registering a writable ModelAdmin is ignored", User not in admin.site._registry and LogEntry not in admin.site._registry)
        check("every registered admin is read-only class", all(type(a).__mro__[1].__name__ == "ReadOnlyModelAdmin" for a in admin.site._registry.values()))
        check("/admin/auth/user/ and /admin/auth/group/ do not exist", adm.get("/admin/auth/user/").status_code == 404 and adm.get("/admin/auth/group/").status_code == 404)
        page = adm.get("/admin/").content.decode()
        check("index lists the data areas, not the user/group area", "Cases" in page and "Audit" in page and "/admin/auth/" not in page, page[:200])

        # --- 可以看 ---
        lists = ["cases/case", "cases/casedocument", "cases/referencesequence", "cases/draftrecyclebin", "personnel/personnel", "masterdata/masterrecord", "fxrates/fxrate", "audit/auditlog", "audit/entitysnapshot"]
        for l in lists:
            r = adm.get(f"/admin/{l}/"); check(f"list page /admin/{l}/ -> 200", r.status_code == 200, r.status_code)
        for label, url, needle in [("case", f"/admin/cases/case/{case.pk}/change/", "ZZ 中文 Insured"), ("personnel", f"/admin/personnel/personnel/{sales_p.pk}/change/", sales_p.name),
                                   ("master", f"/admin/masterdata/masterrecord/{master.pk}/change/", "ZZ AD Master"), ("fx rate", f"/admin/fxrates/fxrate/{fx.pk}/change/", "30.5"),
                                   ("audit", f"/admin/audit/auditlog/{audit.pk}/change/", "中文"), ("snapshot", f"/admin/audit/entitysnapshot/{snap.pk}/change/", "draft_created"),
                                   ("document", f"/admin/cases/casedocument/{CaseDocument.objects.get(case=case).pk}/change/", "zz.pdf"), ("sequence", f"/admin/cases/referencesequence/{seq.pk}/change/", "ZZ-AD")]:
            r = adm.get(url); body = r.content.decode()
            check(f"detail page ({label}) -> 200 and shows the data", r.status_code == 200 and needle in body, (r.status_code, needle))
        body = adm.get(f"/admin/cases/case/{case.pk}/change/").content.decode()
        check("case detail: JSON shown pretty-printed, and there is no input to edit / no Save button", '<pre' in body and '&quot;reinsurers&quot;: [' in body and "_save" not in body and '<input type="text"' not in body
              and "<textarea" not in body and "<select" not in body)
        check("list: search + filters work", adm.get("/admin/cases/case/?q=ZZ-AD-1").status_code == 200 and "ZZ-AD-1" in adm.get("/admin/cases/case/?q=ZZ-AD-1").content.decode()
              and adm.get("/admin/cases/case/?status__exact=draft").status_code == 200 and adm.get("/admin/audit/auditlog/?entity_type=case&action=create_draft").status_code == 200
              and adm.get("/admin/audit/auditlog/?q=zz-ad").status_code == 200)
        pw_hash = User.objects.get(username="zz.ad.admin").password
        every = "".join(adm.get(f"/admin/{l}/").content.decode() for l in lists) + adm.get(f"/admin/personnel/personnel/{admin_p.pk}/change/").content.decode()
        check("no password hash appears on any page", pw_hash not in every and "pbkdf2_sha256" not in every)

        # --- 不能改 ---
        snap_case = (Case.objects.get(pk=case.pk).row_version, Case.objects.get(pk=case.pk).payload)
        counts = lambda: (Case.objects.count(), Personnel.objects.count(), MasterRecord.objects.count(), FxRate.objects.count(), AuditLog.objects.count(), EntitySnapshot.objects.count(), User.objects.count(), LogEntry.objects.count())
        before = counts()
        for l in lists:
            r = adm.get(f"/admin/{l}/add/"); check(f"GET /admin/{l}/add/ -> 403", r.status_code == 403, r.status_code)
        for url in (f"/admin/cases/case/{case.pk}/delete/", f"/admin/audit/auditlog/{audit.pk}/delete/", f"/admin/personnel/personnel/{sales_p.pk}/delete/"):
            r = adm.get(url); check(f"GET {url} (delete confirmation) -> 403", r.status_code == 403, r.status_code)
        posts = [f"/admin/cases/case/{case.pk}/change/", "/admin/cases/case/add/", f"/admin/cases/case/{case.pk}/delete/", "/admin/cases/case/",
                 f"/admin/personnel/personnel/{sales_p.pk}/change/", f"/admin/audit/auditlog/{audit.pk}/delete/", f"/admin/fxrates/fxrate/{fx.pk}/change/", f"/admin/masterdata/masterrecord/{master.pk}/change/"]
        for url in posts:
            r = csrf_post(adm, url, {"payload": "{}", "status": "closed", "post": "yes", "action": "delete_selected", "_selected_action": str(case.pk), "index": "0"})
            check(f"POST {url} -> 403", r.status_code == 403, r.status_code)
        for method in ("put", "patch", "delete"):
            adm.get("/api/auth/csrf"); r = getattr(adm, method)(f"/admin/cases/case/{case.pk}/change/", HTTP_X_CSRFTOKEN=adm.cookies["csrftoken"].value)
            check(f"{method.upper()} on an admin page -> 403", r.status_code == 403, r.status_code)
        c2 = Case.objects.get(pk=case.pk)
        check("nothing changed in the database after all those attempts", counts() == before and (c2.row_version, c2.payload) == snap_case and c2.status == "draft")

        # --- 登出 / 改密碼 ---
        r = adm.get("/admin/password_change/"); check("admin 'change password' sends you to the main app", r.status_code == 302 and r["Location"] == "/")
        r = csrf_post(adm, "/admin/logout/"); check("POST /admin/logout/ logs out and goes to the SPA login", r.status_code == 302 and r["Location"] == "/login", (r.status_code, r.get("Location")))
        check("after logout the session is gone (API 401, admin refused)", adm.get("/api/app-context").status_code == 401 and adm.get("/admin/").status_code == 302)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| ZZ cases =", Case.objects.filter(tw_ref="ZZ-AD-1").count())
