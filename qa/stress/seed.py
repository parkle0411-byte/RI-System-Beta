"""壓力測試造資料（只能在 scripts/run_stress.sh 建立的獨立壓測環境執行；python manage.py shell < seed.py）。

預設資料量（可用環境變數調整）：10,000 件案件、18,000 筆 SoA 交易列
  已確認（Confirmed／closed）原保單 5,000 件：4,400 件單一再保人（3 筆交易）＋ 600 件兩家再保人（6 筆交易）
  已確認的批單 400 件（各 3 筆交易）
  已公布（Announced／posted）1,500 件（尚未關帳，所以還沒有交易，但付款排程會出現在 Accounting）
  草稿 3,100 件
其中約 1/3 的已確認案件有收款紀錄（用真正的 API 記帳），一部分已人工確認結清。
案件內容走真正的 normalize_draft 與 build_premium_transactions／confirm_case（關帳邏輯），形狀和正式相同。
"""
import json
import os
import random
import time
import uuid
from datetime import date, datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import Client

assert os.environ.get("STRESS_STACK") == "true", "只能在壓測環境執行"

from cases.calc.accounting import build_premium_transactions  # noqa: E402
from cases.draft import normalize_draft  # noqa: E402
from cases.models import Case  # noqa: E402
from masterdata.models import MasterRecord  # noqa: E402
from personnel.models import Personnel  # noqa: E402
from production.calc import production_keys_for_case  # noqa: E402
from production.closing import confirm_case  # noqa: E402

assert Case.objects.count() == 0, "資料庫不是空的"

N_CLOSED_1 = int(os.environ.get("STRESS_CLOSED_1", 4400))
N_CLOSED_2 = int(os.environ.get("STRESS_CLOSED_2", 600))
N_ENDO = int(os.environ.get("STRESS_ENDO", 400))
N_POSTED = int(os.environ.get("STRESS_POSTED", 1500))
N_DRAFT = int(os.environ.get("STRESS_DRAFT", 3100))
PAID_FRACTION = float(os.environ.get("STRESS_PAID_FRACTION", 0.33))
PASSWORD = "Stress-Load-Test-9!"
random.seed(20261015)
T0 = time.time()
User = get_user_model()

# ------------------------------------------------------------ 人員與帳號
USERS = [("sales1", "sales", "reinsurance"), ("sales2", "sales", "reinsurance"), ("sales3", "sales", "reinsurance"),
         ("gm", "general_manager", "reinsurance"), ("fin1", "accounting", "finance"), ("fin2", "accounting", "finance"),
         ("finmgr", "accounting_manager", "finance")]
people = {}
for name, role, dept in USERS:
    u = User.objects.create_user(username="stress." + name, password=PASSWORD)
    people[name] = Personnel.objects.create(name="Stress " + name, department=dept, role_code=role, auth_user_id=str(u.pk),
                                            account_status="active", email=f"stress.{name}@example.invalid",
                                            created_by="stress", updated_by="stress")
OWNERS = [people[n] for n in ("sales1", "sales2", "sales3", "gm")]

# ------------------------------------------------------------ 主檔
CLASSES = [("PAR", "Property All Risks"), ("FIR", "Fire"), ("CAR", "Contractors All Risks"), ("EAR", "Erection All Risks"),
           ("MAR", "Marine Cargo"), ("MBD", "Machinery Breakdown"), ("LIA", "General Liability"),
           ("PIN", "Professional Indemnity"), ("CYB", "Cyber"), ("ENG", "Engineering")]
masters = {"reinsurer": [], "reinsured": [], "class": [], "ae": []}
for n in range(1, 41):
    masters["reinsurer"].append(MasterRecord.objects.create(entity_type="reinsurer", code=f"R{n:03d}", name=f"Stress Reinsurer {n:02d}", payload={"abbreviation": f"SR{n:02d}"}, created_by="stress", updated_by="stress"))
for n in range(1, 91):
    masters["reinsured"].append(MasterRecord.objects.create(entity_type="reinsured", code=f"C{n:03d}", name=f"Stress Cedant {n:02d}", payload={"abbreviation": f"SC{n:02d}"}, created_by="stress", updated_by="stress"))
for code, label in CLASSES:
    masters["class"].append(MasterRecord.objects.create(entity_type="class", code=code, name=label, created_by="stress", updated_by="stress"))
for n in range(1, 11):
    masters["ae"].append(MasterRecord.objects.create(entity_type="ae", code=f"A{n:02d}", name=f"Stress AE {n:02d}", created_by="stress", updated_by="stress"))

WORDS = ("the insured property shall be covered against loss or damage caused by fire lightning explosion aircraft impact "
         "windstorm flood earthquake typhoon subject to the deductibles sublimits and exclusions stated in the original policy "
         "wording reinsurers liability follows the original insurer settlements claims notified within thirty days survey "
         "report warranty sprinkler protection maintained in good working order security alarm watchman premises").split()


def sentence(n):
    return " ".join(random.choice(WORDS) for _ in range(n)).capitalize() + "."


def paragraph(chars):
    out = []
    while sum(len(x) + 1 for x in out) < chars:
        out.append(sentence(random.randint(8, 22)))
    return " ".join(out)


CURRENCIES = ["TWD"] * 50 + ["USD"] * 38 + ["EUR"] * 6 + ["JPY"] * 4 + ["GBP"] * 2


def policy_dates(start_lo, start_hi):
    start = start_lo + timedelta(days=random.randint(0, (start_hi - start_lo).days))
    end = date(start.year + 1, start.month, min(start.day, 28))
    return start.isoformat(), end.isoformat()


def build_body(n_reinsurers, start_lo, start_hi, endorsement_of=None):
    cls_code, cls_name = random.choice(CLASSES)
    cedant = random.choice(masters["reinsured"]).name
    currency = random.choice(CURRENCIES)
    premium = round(random.lognormvariate(11.5 if currency in ("TWD", "JPY") else 9.5, 0.9), 0 if currency == "TWD" else 2)   # 2026-10-20：TWD 保費只准整數
    pf, pt = policy_dates(start_lo, start_hi)
    chosen = random.sample(masters["reinsurer"], n_reinsurers)
    share = round(100 / n_reinsurers, 2)
    owner = random.choice(OWNERS)
    rows = [{"name": m.name, "sharePct": share if i < n_reinsurers - 1 else round(100 - share * (n_reinsurers - 1), 2),
             "premium": premium, "riCommPct": random.choice([5, 7.5, 10]), "taxPct": 0, "paymentTermsDays": random.choice([30, 45, 60]),
             "foreignBroker": "", "settlementRef": ""} for i, m in enumerate(chosen)]
    return {
        "ownerPersonnelId": owner.pk, "ownerPersonnelName": owner.name, "type": "Facultative", "typePrefix": "F",
        "originalInsured": f"{random.choice(['Formosa','Pacific','Taipei','Hsinchu','Kaohsiung','Taichung','Eastern'])} {random.choice(['Plastics','Semiconductor','Logistics','Textile','Foods','Steel','Electronics','Chemical'])} Co., Ltd. #{random.randint(1,99999)}",
        "originalInsuredCn": "壓力測試被保險人", "reinsured": cedant,
        "situations": [{"address": f"No. {random.randint(1,300)}, Section {random.randint(1,5)}, Zhongshan Rd, District {random.randint(1,12)}, Taiwan", "postcode": str(random.randint(100, 999))}
                       for _ in range(random.choice([1, 1, 2, 3]))],
        "classOfBusiness": cls_name, "classCode": cls_code, "reinsuranceStructure": "FACULTATIVE",
        "policyFrom": pf, "policyTo": pt, "currency": currency, "originalPremium": premium,
        "riCommPct": random.choice([5, 10, 12.5, 15]), "taxPct": 0, "paymentTermsDays": random.choice([30, 45, 60]),
        "reinsurers": rows,
        "sumInsured": [{"category": random.choice(["Building", "Machinery", "Stock", "Business Interruption", "Contents"]),
                        "amount": round(random.lognormvariate(16, 1), 0), "locationIndex": 0} for _ in range(random.randint(2, 6))],
        "lossAdvisedDate": "2026-01-01", "lossRecordYears": 5, "lossRecordText": "No loss recorded in the last five years.",
        "interest": paragraph(random.randint(200, 500)), "limitOfLiability": round(premium * 80, 0),
        "deductibles": paragraph(random.randint(120, 300)), "underlyingLimits": paragraph(150),
        "subLimits": paragraph(random.randint(150, 400)), "originalExclusions": paragraph(random.randint(800, 1800)),
        "originalConditions": paragraph(random.randint(1000, 2400)), "expressWarranties": paragraph(random.randint(300, 900)),
        "conditionsPrecedent": paragraph(random.randint(200, 600)), "subjectivities": paragraph(random.randint(200, 700)),
        "specialAgreement": paragraph(random.randint(300, 900)), "notices": paragraph(200), "lossPayee": paragraph(80),
        "occupation": paragraph(120), "construction": paragraph(120),
        "ae": random.choice(masters["ae"]).name, "newOrRenew": random.choice(["New", "Renew"]), "exchRate": None,
        "remark": paragraph(random.randint(100, 400)),
    }


def blank_draft_body():
    b = build_body(1, date(2026, 8, 1), date(2026, 12, 1))
    for key in random.sample(["interest", "ae", "originalConditions", "subjectivities", "classCode"], random.randint(0, 3)):
        b[key] = ""
    return b


# ------------------------------------------------------------ 匯率（2025-10 ~ 2026-10；Dashboard／Production Report 需要）
from fxrates.models import FxRate  # noqa: E402
for y, m in [(2025, 10), (2025, 11), (2025, 12)] + [(2026, i) for i in range(1, 11)]:
    for cur, rate in (("USD", 32.1), ("EUR", 35.4), ("JPY", 0.213), ("GBP", 41.2)):
        FxRate.objects.get_or_create(year_month=f"{y}-{m:02d}", currency=cur, defaults={"rate": rate, "created_by": "stress", "updated_by": "stress"})

# ------------------------------------------------------------ 建立案件
now_utc = datetime.now(tz.utc)
seq = {}
cases_to_insert = []
next_id = [1]
closed_ids, posted_ids, draft_ids, root_ids = [], [], [], []


def make_case(kind, status, n_reinsurers=1, parent=None, announced=None):
    cid = next_id[0]
    next_id[0] += 1
    if kind == "draft":
        body, start_lo, start_hi = blank_draft_body(), date(2026, 8, 1), date(2026, 12, 1)
    elif status == "closed":
        start_lo, start_hi = date(2025, 10, 1), date(2026, 6, 15)
    else:
        start_lo, start_hi = date(2026, 7, 1), date(2026, 10, 12)
    if kind != "draft":
        body = build_body(n_reinsurers, start_lo, start_hi)
    result = normalize_draft(body)
    assert not result["errors"], result["errors"]
    payload = result["value"]
    tw_ref, announced_at = None, None
    if kind != "draft":
        announced = announced or datetime.combine(date.fromisoformat(payload["policyFrom"]) + timedelta(days=random.randint(0, 5)), datetime.min.time(), tzinfo=tz.utc) + timedelta(hours=random.randint(1, 9))
        announced = min(announced, now_utc - timedelta(hours=1))
        announced_at = announced
        if kind == "endorsement":
            tw_ref = f"{parent['tw_ref']}-E01"
            payload.update(parentTwRef=parent["tw_ref"], endorsementSeq=1, endoEffectiveDate=payload["policyFrom"], endoTypes=["Premium adjustment"],
                           endoText=paragraph(200), endorsementAnnouncedAt=announced.isoformat())
            payload["originalPremium"] = round(payload["originalPremium"] * random.choice([0.1, 0.2, -0.1, 0.3]), 2)
            for r in payload["reinsurers"]:
                r["premium"] = payload["originalPremium"]
        else:
            prefix = f"TW{payload['classCode']}{announced.year % 100:02d}{announced.month:02d}"
            seq[prefix] = seq.get(prefix, 0) + 1
            tw_ref = f"{prefix}{seq[prefix]:03d}"
        payload["twRef"] = tw_ref
        payload["status"] = "posted"
        payload["postedAt"] = announced.isoformat()
        payload["statementNo"] = f"SOA-{tw_ref}" if status == "closed" else ""
        if status == "closed":
            source = {"id": cid, "case_uid": "", "parent_case_id": parent["id"] if parent else None, "tw_ref": tw_ref, "status": "posted",
                      "row_version": 1, "payload": payload, "announced_at": announced.isoformat(), "created_at": announced.isoformat()}
            keys = production_keys_for_case(source)
            done = confirm_case(source, [{"reinsurerKey": k} for k in keys])
            payload, status = done["payload"], done["nextStatus"]
            assert status == "closed", (status, keys)
            payload["status"] = "closed"
    owner = next(p for p in OWNERS if p.pk == payload["ownerPersonnelId"])
    cls = next(m for m in masters["class"] if m.code == payload["classCode"]) if payload["classCode"] else None
    case = Case(
        id=cid, case_uid=uuid.uuid4(), tw_ref=tw_ref, case_kind="endorsement" if kind == "endorsement" else "original", status=status,
        parent_case_id=parent["id"] if parent else None, reinsurance_structure="FACULTATIVE", class_master=cls,
        class_code_snapshot=payload["classCode"] or None, class_name_snapshot=payload["classOfBusiness"] or None,
        reinsured_name_snapshot=payload["reinsured"], ae_name_snapshot=payload["ae"] or None, owner_personnel=owner,
        currency=payload["currency"], effective_date=date.fromisoformat(payload["policyFrom"]), expiration_date=date.fromisoformat(payload["policyTo"]),
        payload=payload, row_version=2 if kind != "draft" else 1, created_by="stress", updated_by="stress",
        announced_by=f"personnel:{owner.pk}" if announced_at else None, announced_at=announced_at)
    cases_to_insert.append(case)
    return {"id": cid, "tw_ref": tw_ref, "uid": str(case.case_uid)}


print("產生案件內容…", flush=True)
closed_roots = []
for i in range(N_CLOSED_1 + N_CLOSED_2):
    info = make_case("original", "closed", 2 if i >= N_CLOSED_1 else 1)
    closed_roots.append(info)
    closed_ids.append(info["uid"])
for i in range(N_ENDO):
    parent = closed_roots[i * 7 % len(closed_roots)]
    closed_ids.append(make_case("endorsement", "closed", 1, parent=parent)["uid"])
for _ in range(N_POSTED):
    posted_ids.append(make_case("original", "posted", random.choice([1, 1, 2]))["uid"])
for _ in range(N_DRAFT):
    draft_ids.append(make_case("draft", "draft")["uid"])
# 插入順序與狀態混在一起（批單排在最後，父案件一定先存在）；id 是事先指定的
parents_first = [c for c in cases_to_insert if c.parent_case_id is None]
children = [c for c in cases_to_insert if c.parent_case_id is not None]
random.shuffle(parents_first)
cases_to_insert = parents_first + children
print(f"  產生完成 {len(cases_to_insert)} 件（{time.time() - T0:.0f} 秒）", flush=True)

print("寫入資料庫…", flush=True)
Case.objects.bulk_create(cases_to_insert, batch_size=400)
print(f"  寫入完成（{time.time() - T0:.0f} 秒）", flush=True)

# ------------------------------------------------------------ 用真正的 API 記一部分收款與人工確認
client = Client(HTTP_HOST="localhost")
client.force_login(User.objects.get(username="stress.fin1"))


def post(body):
    return client.post("/api/accounting", data=json.dumps(body), content_type="application/json")


# 2026-10-20：退保批單須先收齊並銷帳再保人退款才能退 Cedant；造資料只對正保費案件記收款
closed_cases = [c for c in Case.objects.filter(status="closed").order_by("id") if (c.payload.get("originalPremium") or 0) >= 0]
random.shuffle(closed_cases)
n_pay = int(len(closed_cases) * PAID_FRACTION)
print(f"用 API 記 {n_pay} 件案件的收款…", flush=True)
paid_calls = settled_calls = 0
unpaid_samples = []
for index, case in enumerate(closed_cases):
    txs = [t for t in case.payload["transactions"] if t.get("legType") == "Leg 1"]
    if index >= n_pay:
        if txs and len(unpaid_samples) < 600:
            unpaid_samples.append({"caseUid": str(case.case_uid), "txNo": txs[0]["txNo"], "amount": abs(txs[0]["amount"]), "currency": case.currency})
        continue
    for leg_no, tx in enumerate(txs):
        r = post({"action": "record_transaction_payments", "paymentDate": "2026-10-08", "amount": abs(tx["amount"]), "reference": f"STRESS-{case.pk}",
                  "allocations": [{"caseUid": str(case.case_uid), "txNo": tx["txNo"], "rowVersion": Case.objects.get(pk=case.pk).row_version, "amount": abs(tx["amount"])}]})
        if r.status_code != 200:
            print("  收款失敗", r.status_code, r.content[:200]); raise SystemExit(1)
        paid_calls += 1
        if index < n_pay // 2:
            r = post({"action": "confirm_facility_settlement", "caseUid": str(case.case_uid), "rowVersion": Case.objects.get(pk=case.pk).row_version,
                      "txNo": tx["txNo"], "note": "STRESS reconciled"})
            if r.status_code != 200:
                print("  確認失敗", r.status_code, r.content[:200]); raise SystemExit(1)
            settled_calls += 1
    if index % 200 == 0:
        print(f"  …{index}/{n_pay} ({time.time() - T0:.0f} 秒)", flush=True)

# ------------------------------------------------------------ 範例清單（給負載產生器）與統計
rv = {str(c.case_uid): c.row_version for c in Case.objects.filter(status="draft")[:600]}
samples = {
    "password": PASSWORD, "users": [{"username": "stress." + n, "role": r} for n, r, _ in USERS],
    "ledger": random.sample(closed_ids, min(800, len(closed_ids))) + random.sample(posted_ids, min(200, len(posted_ids))),
    "unpaid": unpaid_samples, "drafts": [{"caseUid": k, "rowVersion": v} for k, v in rv.items()],
    "months": ["2026-10", "2026-09", "2026-08"],
}
with open("/tmp/stress_samples.json", "w") as f:
    json.dump(samples, f)

from django.db import connection  # noqa: E402
with connection.cursor() as cur:
    cur.execute("SELECT status, COUNT(*), ROUND(AVG(LENGTH(payload))), ROUND(SUM(LENGTH(payload))/1048576,1) FROM ri_cases GROUP BY status")
    stats = cur.fetchall()
    cur.execute("SELECT table_name, ROUND((data_length+index_length)/1048576,1) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('ri_cases','ri_entity_snapshots')")
    sizes = cur.fetchall()
print("\n=== 資料集 ===")
print("案件總數", Case.objects.count(), "| 狀態 / 件數 / 平均 payload bytes / payload 總 MB:", stats)
print("資料表大小 MB:", sizes)
print(f"收款 API {paid_calls} 次、人工確認 {settled_calls} 次；總耗時 {time.time() - T0:.0f} 秒")
