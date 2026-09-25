import json
import uuid
from datetime import datetime, timedelta, timezone as dt_tz
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client
from django.utils import timezone
from audit.models import AuditLog, EntitySnapshot
from cases.models import Case, DraftRecycleBin
from cases.recycle_views import add_years_pg
from personnel.models import Personnel

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(role, dept):
    _seq[0] += 1
    return Personnel.objects.create(name=f"ZZ RB {role} {_seq[0]}", department=dept, role_code=role, created_by="t", updated_by="t")
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.rb.{tag}", password="Bin-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Bin-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c
def code(r):
    try: return r.json().get("error")
    except Exception: return None
URL = "/api/draft-recycle-bin"

try:
    with transaction.atomic():
        admin_p, sales_p, gm_p = person("admin", "admin"), person("sales", "reinsurance"), person("general_manager", "reinsurance")
        admin, sales, gm = account(admin_p, "admin"), account(sales_p, "sales"), account(gm_p, "gm")
        def new_case(insured="ZZ RB Insured"):
            r = call(sales, "post", "/api/cases", {"case": {"originalInsured": insured, "currency": "USD"}}); assert r.status_code == 201, r.content
            return Case.objects.get(case_uid=r.json()["case"]["caseUid"])
        def recycle(case, c=admin, **over):
            body = {"action": "recycle", "caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version}
            body.update(over); return call(c, "post", URL, body)
        def restore(rid, c=admin): return call(c, "post", URL, {"action": "restore", "recycleId": rid})
        def items(): return call(admin, "get", URL).json()["items"]

        # --- 權限 ---
        check("anonymous -> 401", call(new_client(), "get", URL).status_code == 401)
        check("sales / GM have no recycle permissions -> 403", call(sales, "get", URL).status_code == 403 and call(gm, "get", URL).status_code == 403
              and call(sales, "post", URL, {"action": "recycle"}).status_code == 403)
        j = call(admin, "get", URL).json()
        check("admin list: ok, retention 5 years, permanent delete not allowed", j["ok"] is True and j["retentionYears"] == 5 and j["permanentDeleteAllowed"] is False and isinstance(j["items"], list))

        # --- 丟進回收桶 ---
        c1 = new_case()
        for label, over in (("no caseUid", {"caseUid": ""}), ("rowVersion 0", {"rowVersion": 0}), ("rowVersion text", {"rowVersion": "x"}), ("rowVersion 1.5", {"rowVersion": 1.5})):
            check(f"recycle: {label} -> 400 case_version_required", code(recycle(c1, **over)) == "case_version_required")
        check("recycle: unknown / malformed case -> 404", code(recycle(c1, caseUid=str(uuid.uuid4()))) == "case_not_found" and code(recycle(c1, caseUid="nope")) == "case_not_found")
        r = recycle(c1, rowVersion=9); check("recycle: stale version -> 409 version_conflict + currentRowVersion", code(r) == "version_conflict" and r.json()["currentRowVersion"] == 1)
        posted = new_case(); Case.objects.filter(pk=posted.pk).update(status="posted", tw_ref="ZZ-RB-1")
        check("recycle a non-Draft -> 409 draft_required", code(recycle(posted)) == "draft_required")
        before_row = Case.objects.get(pk=c1.pk)
        t0 = timezone.now()
        r = recycle(c1); j = r.json(); c1.refresh_from_db()
        check("recycle -> 200 with recycleId, restoreDeadline, rowVersion 2", r.status_code == 200 and j["ok"] is True and j["rowVersion"] == 2 and isinstance(j["recycleId"], int), (r.status_code, j))
        item = DraftRecycleBin.objects.get(pk=j["recycleId"])
        check("case marked recycled (not deleted), version +1, recycled_by = actor", c1.recycled_at is not None and c1.recycled_by == f"personnel:{admin_p.pk}" and c1.row_version == 2 and c1.status == "draft")
        check("bin row: original version, actor, deadline = deleted_at + 5 years", item.original_case_version == 1 and item.deleted_by == f"personnel:{admin_p.pk}"
              and item.restore_deadline == add_years_pg(item.deleted_at, 5) and item.deleted_at >= t0 and item.restored_at is None)
        snap = item.case_snapshot
        check("bin keeps the whole case row as it was (column names, payload, version 1, not yet recycled)",
              snap["case_uid"] == str(c1.case_uid) and snap["row_version"] == 1 and snap["recycled_at"] is None and snap["payload"]["originalInsured"] == "ZZ RB Insured"
              and {"id", "status", "owner_personnel_id", "class_master_id", "created_at"} <= set(snap), sorted(snap)[:6])
        a = AuditLog.objects.filter(entity_type="case", entity_id=str(c1.case_uid), action="recycle_draft").first()
        check("audit recycle_draft: before = full row, after = policy, metadata", a and a.before_data["row_version"] == 1
              and a.after_data == {"caseUid": str(c1.case_uid), "status": "draft", "recycled": True, "retentionYears": 5, "permanentDeleteAllowed": False}
              and a.metadata == {"retentionYears": 5, "permanentDeleteAllowed": False})
        s = EntitySnapshot.objects.filter(entity_type="case", entity_id=str(c1.case_uid), snapshot_reason="draft_recycled").first()
        check("snapshot draft_recycled at version 2 (VM addition)", s and s.entity_version == 2 and s.snapshot_data["recycled_at"] is not None)
        check("recycled Draft disappears from the case list and cannot be opened", str(c1.case_uid) not in [x["caseUid"] for x in call(sales, "get", "/api/cases").json()["cases"]]
              and call(sales, "get", f"/api/cases?caseUid={c1.case_uid}").status_code == 404)
        check("a recycled Draft cannot be edited", call(sales, "put", "/api/cases", {"caseUid": str(c1.case_uid), "rowVersion": 2, "case": {}}).status_code == 404)
        check("recycle again -> 409 already_recycled", code(recycle(c1)) == "already_recycled")

        # --- 列表 ---
        c2 = new_case("ZZ RB Second"); recycle(c2)
        it = items()
        mine = [x for x in it if x["caseUid"] in (str(c1.case_uid), str(c2.case_uid))]
        check("list: newest first", [x["caseUid"] for x in mine] == [str(c2.case_uid), str(c1.case_uid)], [x["caseUid"] for x in mine])
        x = next(x for x in mine if x["caseUid"] == str(c1.case_uid))
        check("list item fields", x["id"] == item.pk and x["originalCaseId"] == c1.pk and x["rowVersion"] == 2 and x["originalCaseVersion"] == 1
              and x["originalInsured"] == "ZZ RB Insured" and x["caseKind"] == "original" and x["deletedBy"] == f"personnel:{admin_p.pk}" and x["canRestore"] is True, x)

        # --- 還原 ---
        for bad in (None, 0, "x", -3, 1.5):
            check(f"restore: recycleId {bad!r} -> 400", code(restore(bad)) == "recycle_id_required")
        check("restore: unknown id -> 404", code(restore(99999999)) == "recycle_item_not_found")
        r = restore(item.pk); j = r.json(); c1.refresh_from_db(); item.refresh_from_db()
        check("restore -> 200, case back (not recycled), version 3", r.status_code == 200 and j["caseUid"] == str(c1.case_uid) and j["rowVersion"] == 3
              and c1.recycled_at is None and c1.recycled_by is None and c1.row_version == 3, (r.status_code, j))
        check("bin row marked restored by the actor", item.restored_at is not None and item.restored_by == f"personnel:{admin_p.pk}")
        a = AuditLog.objects.filter(entity_type="case", entity_id=str(c1.case_uid), action="restore_draft").first()
        check("audit restore_draft: before recycled, after not, metadata recycleId", a and a.before_data["recycled_at"] is not None and a.after_data["recycled_at"] is None
              and a.after_data["row_version"] == 3 and a.metadata == {"recycleId": item.pk, "retentionYears": 5, "permanentDeleteAllowed": False})
        check("snapshot draft_restored at version 3", EntitySnapshot.objects.filter(entity_type="case", entity_id=str(c1.case_uid), snapshot_reason="draft_restored", entity_version=3).exists())
        check("every version of the case has exactly one snapshot (1 created, 2 recycled, 3 restored)",
              sorted(EntitySnapshot.objects.filter(entity_type="case", entity_id=str(c1.case_uid)).values_list("entity_version", flat=True)) == [1, 2, 3])
        check("restored Draft is back in the case list and editable again", str(c1.case_uid) in [x["caseUid"] for x in call(sales, "get", "/api/cases").json()["cases"]])
        check("restored item leaves the recycle-bin list", item.pk not in [x["id"] for x in items()])
        check("restore the same item again -> 409 already_restored", code(restore(item.pk)) == "already_restored")

        # 再丟一次：新的一筆；舊的那筆仍然是「已還原」
        r = recycle(c1); second = r.json()["recycleId"]
        check("recycling it again creates a new entry", r.status_code == 200 and second != item.pk and DraftRecycleBin.objects.filter(original_case=c1).count() == 2)
        check("...the old entry still says already_restored; the new one restores", code(restore(item.pk)) == "already_restored" and restore(second).status_code == 200)

        # 案件已經不在回收桶（例如資料被修正過）：拒絕
        r = recycle(c2); e = DraftRecycleBin.objects.filter(original_case=c2, restored_at__isnull=True).first()
        Case.objects.filter(pk=c2.pk).update(recycled_at=None, recycled_by=None)
        check("entry whose case is no longer recycled -> 409 case_not_recycled and not listed", code(restore(e.pk)) == "case_not_recycled" and e.pk not in [x["id"] for x in items()])
        Case.objects.filter(pk=c2.pk).update(recycled_at=timezone.now(), recycled_by="t")

        # 5 年期限
        DraftRecycleBin.objects.filter(pk=e.pk).update(restore_deadline=timezone.now() - timedelta(seconds=1))
        x = next(x for x in items() if x["id"] == e.pk)
        check("after the deadline: listed with canRestore false", x["canRestore"] is False)
        n = AuditLog.objects.count()
        check("after the deadline: restore -> 409 restore_window_expired, nothing written", code(restore(e.pk)) == "restore_window_expired" and AuditLog.objects.count() == n
              and Case.objects.get(pk=c2.pk).recycled_at is not None)
        check("5 years from 2028-02-29 is 2033-02-28 (PostgreSQL interval rule, as Alpha)",
              add_years_pg(datetime(2028, 2, 29, 12, tzinfo=dt_tz.utc), 5) == datetime(2033, 2, 28, 12, tzinfo=dt_tz.utc)
              and add_years_pg(datetime(2026, 9, 25, tzinfo=dt_tz.utc), 5) == datetime(2031, 9, 25, tzinfo=dt_tz.utc))

        # 永久刪除一律不行
        for act in ("delete", "purge", "permanent_delete", ""):
            r = call(admin, "post", URL, {"action": act, "recycleId": e.pk})
            check(f"action {act!r} -> 400 unsupported_action (permanent deletion prohibited)", code(r) == "unsupported_action" and "Permanent deletion is prohibited" in r.json()["message"])
        try:
            with transaction.atomic():
                DraftRecycleBin.objects.filter(pk=e.pk).update(permanently_deleted_at=timezone.now(), permanently_deleted_by="x")
            check("database CHECK refuses marking an entry permanently deleted", False)
        except IntegrityError:
            check("database CHECK refuses marking an entry permanently deleted", True)
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("DELETE FROM ri_draft_recycle_bin WHERE id = %s", [e.pk])
            check("the web database account cannot DELETE from the recycle bin", False)
        except DatabaseError as exc:
            check("the web database account cannot DELETE from the recycle bin", "DELETE command denied" in str(exc), str(exc)[:120])
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute("DELETE FROM ri_cases WHERE id = %s", [c2.pk])
            check("...nor from ri_cases", False)
        except DatabaseError as exc:
            check("...nor from ri_cases", "DELETE command denied" in str(exc))

        # 批單草稿丟進回收桶後，案件鏈的「最新一筆」回到前一筆
        root = new_case("ZZ RB Root"); Case.objects.filter(pk=root.pk).update(status="posted", tw_ref="ZZ-RB-ROOT")
        root.refresh_from_db()
        r = call(sales, "post", "/api/case-workflow", {"action": "create_endorsement", "caseUid": str(root.case_uid), "rowVersion": root.row_version})
        endo = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
        check("with a Draft endorsement, the root cannot be endorsed again", call(sales, "get", f"/api/case-workflow?caseUid={root.case_uid}").json()["workflow"]["actions"]["canCreateEndorsement"] is False)
        recycle(endo)
        check("after recycling the endorsement Draft, the root is the latest again", call(sales, "get", f"/api/case-workflow?caseUid={root.case_uid}").json()["workflow"]["actions"]["canCreateEndorsement"] is True)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ").count(), "| recycle rows =", DraftRecycleBin.objects.count())
