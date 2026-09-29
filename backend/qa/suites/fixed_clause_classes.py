import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from audit.models import AuditLog
from masterdata.models import MasterRecord
from personnel.models import Personnel

# VM 才有（2026-09-29 決定）：再保人 Fixed Clause 的適用 Class（classIds；沒有 = All classes）與 Class 自己的 Fixed Clause
User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
def call(c, m, body):
    c.get("/api/auth/csrf")
    return getattr(c, m)("/api/master-data", data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
def msg(r):
    try: return r.json().get("message")
    except Exception: return None
try:
    with transaction.atomic():
        p = Personnel.objects.create(name="ZZ FCC admin", department="admin", role_code="admin", created_by="t", updated_by="t")
        u = User.objects.create_user(username="zz.fcc.admin", password="Fixed-Clause-Pass-1"); p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
        c = Client(enforce_csrf_checks=True, HTTP_HOST="localhost"); cache.clear(); c.get("/api/auth/csrf")
        assert c.post("/api/auth/login", data=json.dumps({"username": "zz.fcc.admin", "password": "Fixed-Clause-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value).status_code == 200

        # Class 主檔
        r = call(c, "post", {"entityType": "class", "code": "ZZP", "name": "ZZ FCC Property"}); prop = r.json()["record"]
        check("class without fixed clauses keeps payload {} (same as Alpha)", r.status_code == 201 and prop["payload"] == {}, r.content[:200])
        marine = call(c, "post", {"entityType": "class", "code": "ZZM", "name": "ZZ FCC Marine"}).json()["record"]
        r = call(c, "post", {"entityType": "class", "code": "ZZL", "name": "ZZ FCC Liability", "payload": {"fixedClauses": [{"code": "nma 1", "title": " Class clause "}]}})
        cls = r.json().get("record", {})
        check("class with a fixed clause -> stored normalised (code upper/underscore, title trimmed), no classIds",
              r.status_code == 201 and cls["payload"] == {"fixedClauses": [{"code": "NMA_1", "title": "Class clause"}]}, r.content[:200])
        r = call(c, "post", {"entityType": "class", "name": "ZZ FCC empty list", "payload": {"fixedClauses": []}})
        check("class with an empty fixed clause list -> payload {}", r.status_code == 201 and r.json()["record"]["payload"] == {}, r.content[:200])
        r = call(c, "post", {"entityType": "class", "name": "ZZ FCC classIds ignored", "payload": {"fixedClauses": [{"code": "X1", "title": "T", "classIds": [prop["id"]]}]}})
        check("classIds on a Class's own clause are ignored", r.status_code == 201 and r.json()["record"]["payload"].get("fixedClauses") == [{"code": "X1", "title": "T"}], r.content[:200])
        r = call(c, "post", {"entityType": "class", "name": "ZZ FCC universal", "payload": {"fixedClauses": [{"code": "LMA3333", "title": "T"}]}})
        check("universal clause on a class -> 400", r.status_code == 400 and msg(r) == "LMA3333 is universal and must not be added to a class.", r.content[:200])
        r = call(c, "post", {"entityType": "class", "name": "ZZ FCC dup", "payload": {"fixedClauses": [{"code": "A", "title": "T"}, {"code": "a", "title": "U"}]}})
        check("duplicate clause on a class -> 400", r.status_code == 400 and msg(r) == "Fixed clause A is duplicated.", r.content[:200])
        r = call(c, "post", {"entityType": "class", "name": "ZZ FCC many", "payload": {"fixedClauses": [{"code": f"C{i}", "title": "T"} for i in range(101)]}})
        check("more than 100 clauses on a class -> 400", r.status_code == 400 and msg(r) == "A class cannot contain more than 100 fixed clauses.", r.content[:200])
        r = call(c, "post", {"entityType": "class", "name": "ZZ FCC missing title", "payload": {"fixedClauses": [{"code": "B"}]}})
        check("class clause without a title -> 400", r.status_code == 400 and msg(r) == "Every fixed clause requires both a code and full name.", r.content[:200])

        # 再保人
        r = call(c, "post", {"entityType": "reinsurer", "name": "ZZ FCC Re", "payload": {"abbreviation": "ZFR", "fixedClauses": [
            {"code": "LMA5401", "title": "All"},
            {"code": "LMA5018", "title": "Some", "classIds": [marine["id"], prop["id"], prop["id"]]},
            {"code": "NMA2919", "title": "Null means all", "classIds": None}]}})
        re_ = r.json().get("record", {})
        fc = re_.get("payload", {}).get("fixedClauses", [])
        check("reinsurer clause without classIds -> stored exactly as Alpha {code,title}", r.status_code == 201 and fc[0] == {"code": "LMA5401", "title": "All"}, r.content[:300])
        check("classIds -> stored sorted and de-duplicated", fc[1:2] == [{"code": "LMA5018", "title": "Some", "classIds": sorted([prop["id"], marine["id"]])}], fc)
        check("classIds null -> All classes (key omitted)", fc[2:3] == [{"code": "NMA2919", "title": "Null means all"}], fc)
        for label, bad, expected in (
            ("empty list", [], "Fixed clause X must apply to All classes or to at least one Class."),
            ("string", "1", "Fixed clause X must apply to All classes or to at least one Class."),
            ("zero", [0], "Fixed clause X has an invalid Class."),
            ("boolean", [True], "Fixed clause X has an invalid Class."),
            ("text id", [str(prop["id"])], "Fixed clause X has an invalid Class."),
            ("float", [1.5], "Fixed clause X has an invalid Class."),
            ("unknown id", [999999999], "A fixed clause refers to a Class that does not exist."),
            ("id of a non-class master", [re_["id"]], "A fixed clause refers to a Class that does not exist."),
        ):
            r = call(c, "post", {"entityType": "reinsurer", "name": f"ZZ FCC bad {label}", "payload": {"fixedClauses": [{"code": "X", "title": "T", "classIds": bad}]}})
            check(f"classIds {label} -> 400", r.status_code == 400 and msg(r) == expected, (r.status_code, r.content[:200]))
        for label, body, expected in (
            ("fixedClauses null on a reinsurer", {"fixedClauses": None}, "Fixed clauses must be a list."),
            ("ratings null on a reinsurer", {"ratings": None}, "Ratings must be a list."),
        ):
            r = call(c, "post", {"entityType": "reinsurer", "name": f"ZZ FCC {label}", "payload": body})
            check(f"{label} -> 400 (same as Alpha: null is not a list)", r.status_code == 400 and msg(r) == expected, r.content[:200])
        r = call(c, "post", {"entityType": "class", "name": "ZZ FCC null class clauses", "payload": {"fixedClauses": None}})
        check("fixedClauses null on a class -> 400", r.status_code == 400 and msg(r) == "Fixed clauses must be a list.", r.content[:200])
        r = call(c, "post", {"entityType": "reinsurer", "name": "ZZ FCC float id", "payload": json.dumps({"fixedClauses": [{"code": "X", "title": "T", "classIds": [float(prop["id"])]}]})})   # JSON 文字是 "92.0"
        check("classIds 84.0 counts as the integer 84 (JavaScript numbers, same as Alpha)", r.status_code == 201 and r.json()["record"]["payload"]["fixedClauses"][0]["classIds"] == [prop["id"]], r.content[:200])
        r = call(c, "post", {"entityType": "reinsurer", "name": "ZZ FCC universal", "payload": {"fixedClauses": [{"code": "INTERMEDIARY", "title": "T"}]}})
        check("universal clause on a reinsurer -> Alpha's message unchanged", r.status_code == 400 and msg(r) == "INTERMEDIARY is universal and must not be added to a reinsurer.", r.content[:200])
        r = call(c, "post", {"entityType": "reinsurer", "name": "ZZ FCC many", "payload": {"fixedClauses": [{"code": f"C{i}", "title": "T"} for i in range(101)]}})
        check("more than 100 clauses on a reinsurer -> Alpha's message unchanged", r.status_code == 400 and msg(r) == "A reinsurer cannot contain more than 100 fixed clauses.", r.content[:200])
        inactive = MasterRecord.objects.get(pk=marine["id"])
        r = call(c, "put", {"id": marine["id"], "rowVersion": inactive.row_version, "entityType": "class", "code": "ZZM", "name": "ZZ FCC Marine", "isActive": False})
        r = call(c, "post", {"entityType": "reinsurer", "name": "ZZ FCC inactive class", "payload": {"fixedClauses": [{"code": "X", "title": "T", "classIds": [marine["id"]]}]}})
        check("an inactive Class can still be referenced (kept for history)", r.status_code == 201, r.content[:200])

        # 其他類型不受影響
        r = call(c, "post", {"entityType": "reinsured", "name": "ZZ FCC Cedant", "payload": {"abbreviation": "ZC", "fixedClauses": [{"code": "X", "title": "T"}]}})
        check("cedant payload ignores fixedClauses (as before)", r.status_code == 201 and "fixedClauses" not in r.json()["record"]["payload"], r.content[:200])

        # PUT：沿用、更新、啟停用都保留 classIds；Audit 記下前後內容
        m = MasterRecord.objects.get(pk=re_["id"])
        r = call(c, "put", {"id": m.pk, "rowVersion": m.row_version, "entityType": "reinsurer", "name": "ZZ FCC Re", "isActive": False})
        check("PUT without payload (deactivate) keeps classIds", r.status_code == 200 and r.json()["record"]["payload"]["fixedClauses"] == fc, r.content[:300])
        m.refresh_from_db()
        r = call(c, "put", {"id": m.pk, "rowVersion": m.row_version, "entityType": "reinsurer", "name": "ZZ FCC Re", "isActive": True, "payload": json.dumps(m.payload)})
        check("reactivate with the stored payload sent back as a JSON string (what the screen does) keeps classIds", r.status_code == 200 and r.json()["record"]["payload"]["fixedClauses"] == fc, r.content[:300])
        m.refresh_from_db()
        new_payload = {**m.payload, "fixedClauses": [{"code": "LMA5401", "title": "All", "classIds": [prop["id"]]}]}
        r = call(c, "put", {"id": m.pk, "rowVersion": m.row_version, "entityType": "reinsurer", "name": "ZZ FCC Re", "payload": json.dumps(new_payload)})
        check("PUT changes the class scope", r.status_code == 200 and r.json()["record"]["payload"]["fixedClauses"] == [{"code": "LMA5401", "title": "All", "classIds": [prop["id"]]}], r.content[:300])
        ev = AuditLog.objects.filter(entity_type="master_record", entity_id=str(m.pk), action="update_master").order_by("-id").first()
        check("Audit keeps the before/after class scope",
              ev is not None and ev.before_data["payload"]["fixedClauses"] == fc and ev.after_data["payload"]["fixedClauses"][0].get("classIds") == [prop["id"]])
        k = MasterRecord.objects.get(pk=cls["id"])
        r = call(c, "put", {"id": k.pk, "rowVersion": k.row_version, "entityType": "class", "code": "ZZL", "name": "ZZ FCC Liability", "payload": json.dumps({})})
        check("PUT a class with payload {} removes its fixed clauses", r.status_code == 200 and r.json()["record"]["payload"] == {}, r.content[:200])
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
