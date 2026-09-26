# 切換演練：擷取各畫面 API 的輸出，並把「這個環境自己」的數字 ID 換成穩定的識別（案件 → case_uid、人員 → 姓名），
# 讓 A（扮演 Alpha）與 B（匯入後的 VM）可以直接比對。對照只用本環境的資料庫，不依賴匯入程式的對照表。
import json, re, sys
sys.path.insert(0, "/tmp/rehearsal")
from common import call, login, months
from cases.models import Case
from personnel.models import Personnel

M1, M2 = months()
CASE = {c.pk: str(c.case_uid) for c in Case.objects.all()}
PERSON = {p.pk: p.name for p in Personnel.objects.all()}
KEY = re.compile(r"([0-9]+)(:.*)\Z", re.S)
ACTOR = re.compile(r"personnel:([0-9]+)\Z")
CASE_KEYS = {"parentCaseId", "caseId", "originalCaseId", "parent_case_id", "case_id", "original_case_id"}
PERSON_KEYS = {"ownerPersonnelId", "personnelId", "accountingPersonnelId", "defaultOwnerId", "owner_personnel_id"}
KEYED = {"id", "key", "reinsurerKey", "installment_key", "reinsurer_key"}

def person(v):
    if isinstance(v, bool) or v is None: return v
    try: return "P<" + PERSON[int(v)] + ">"
    except (KeyError, ValueError, TypeError): return v

def norm(x, parent_key=None):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k == "id" and isinstance(v, int) and not isinstance(v, bool):
                out[k] = CASE.get(v) if "caseUid" in x and CASE.get(v) == x.get("caseUid") else "<id>"
            elif k in CASE_KEYS and isinstance(v, (int, float, str)) and not isinstance(v, bool) and str(v).replace(".0", "").isdigit():
                out[k] = "C<" + CASE.get(int(float(v)), f"?{v}") + ">"
            elif k == "sourceSignature" and isinstance(v, str) and v.startswith("["):
                out[k] = json.dumps([[norm({"key": r[0]})["key"]] + r[1:] for r in json.loads(v)], ensure_ascii=False)
            elif k in PERSON_KEYS:
                out[k] = person(v)
            elif k in KEYED and isinstance(v, str) and KEY.match(v) and int(KEY.match(v).group(1)) in CASE:
                out[k] = "C<" + CASE[int(KEY.match(v).group(1))] + ">" + KEY.match(v).group(2)
            elif k == "confirmedProductionKeys" and isinstance(v, list):
                out[k] = [norm({"key": i})["key"] for i in v]
            else:
                out[k] = norm(v, k)
        return out
    if isinstance(x, list):
        return [norm(v, parent_key) for v in x]
    if isinstance(x, str) and ACTOR.match(x):
        return "actor:" + str(person(ACTOR.match(x).group(1)))
    return x

admin = login("ui.admin")
get = lambda url: norm(call(admin, "get", url).json())
out = {"cases": get("/api/cases"), "accounting": get("/api/accounting"), "dashboard": get("/api/dashboard"),
       "recycle": get("/api/draft-recycle-bin"), "targets": get("/api/dashboard-targets"), "fx": get("/api/fx-rates"),
       "personnelOptions": get("/api/personnel-options"),
       "production": {m: get(f"/api/production-report?month={m}") for m in (M1, M2)}, "perCase": {}}
for c in Case.objects.all():
    u = str(c.case_uid)
    out["perCase"][u] = {"case": get(f"/api/cases?caseUid={u}"), "workflow": get(f"/api/case-workflow?caseUid={u}"),
                         "claims": get(f"/api/claims?caseUid={u}"), "documents": get(f"/api/case-documents?caseUid={u}")}
# fx 列表的 id 與匯率的建立者會因重新編號不同：id 已換成 <id>
print("CAPTURE" + json.dumps(out, ensure_ascii=False, sort_keys=True, default=str))
