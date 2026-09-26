import json
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import Client
from masterdata.models import MasterRecord
from personnel.models import Personnel

# Alpha 的主檔畫面把 payload 以 JSON 字串送出；API 必須與 Alpha 的 masterPayload() 相同地接受
User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
def call(c, m, body):
    c.get("/api/auth/csrf")
    return getattr(c, m)("/api/master-data", data=json.dumps(body), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
def code(r):
    try: return r.json().get("error")
    except Exception: return None
try:
    with transaction.atomic():
        p = Personnel.objects.create(name="ZZ MP admin", department="admin", role_code="admin", created_by="t", updated_by="t")
        u = User.objects.create_user(username="zz.mp.admin", password="Master-Pay-Pass-1"); p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
        c = Client(enforce_csrf_checks=True, HTTP_HOST="localhost"); cache.clear(); c.get("/api/auth/csrf")
        assert c.post("/api/auth/login", data=json.dumps({"username": "zz.mp.admin", "password": "Master-Pay-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value).status_code == 200
        base = {"entityType": "reinsurer", "name": "ZZ MP Re"}
        r = call(c, "post", {**base, "payload": json.dumps({"abbreviation": "ZMP", "fixedClauses": [{"code": "lma 1", "title": "T"}]})})
        rec = r.json().get("record", {})
        check("POST with payload as a JSON string (what Alpha's screen sends) -> 201, parsed", r.status_code == 201 and rec["payload"]["abbreviation"] == "ZMP" and rec["payload"]["fixedClauses"][0]["code"] == "LMA_1", r.content[:200])
        r = call(c, "post", {**base, "name": "ZZ MP Obj", "payload": {"abbreviation": "OBJ"}}); check("POST with payload as an object still works", r.status_code == 201 and r.json()["record"]["payload"]["abbreviation"] == "OBJ")
        r = call(c, "post", {**base, "name": "ZZ MP None"}); check("POST without payload -> stored as {} (Alpha returns the fallback unchanged)", r.status_code == 201 and r.json()["record"]["payload"] == {}, r.content[:200])
        for label, bad in (("null", None), ("array", []), ("number", 5), ("not JSON", "{abc"), ("JSON array string", "[1]"), ("JSON null string", "null"), ("NaN string", '{"a": NaN}')):
            r = call(c, "post", {**base, "name": f"ZZ MP bad {label}", "payload": bad})
            check(f"POST payload {label} -> 400 'must be an object' (same as Alpha)", r.status_code == 400 and r.json()["message"] == "Master-data payload must be an object.", (r.status_code, r.content[:120]))
        m = MasterRecord.objects.get(name="ZZ MP Re")
        r = call(c, "put", {"id": m.pk, "rowVersion": m.row_version, "entityType": "reinsurer", "name": "ZZ MP Re", "payload": json.dumps({"abbreviation": "NEW"})})
        check("PUT with payload as a JSON string -> updated", r.status_code == 200 and r.json()["record"]["payload"]["abbreviation"] == "NEW", r.content[:200])
        m.refresh_from_db()
        r = call(c, "put", {"id": m.pk, "rowVersion": m.row_version, "entityType": "reinsurer", "name": "ZZ MP Re", "isActive": False})
        check("PUT without payload keeps the stored payload", r.status_code == 200 and r.json()["record"]["payload"]["abbreviation"] == "NEW")
        m.refresh_from_db()
        r = call(c, "put", {"id": m.pk, "rowVersion": m.row_version, "entityType": "reinsurer", "name": "ZZ MP Re", "payload": None})
        check("PUT with payload null -> 400 (Alpha: null is not an object)", r.status_code == 400, r.content[:120])
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, d in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {d}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
