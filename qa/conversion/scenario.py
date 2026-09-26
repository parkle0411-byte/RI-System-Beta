# 切換演練：在環境 A（扮演 Alpha）用 VM 自己的 API 建出各種情境的合成資料，再補幾個 API 做不出來、但 Alpha 資料可能有的形狀。
import base64, copy, sys
sys.path.insert(0, "/tmp/rehearsal")
from common import call, login, months
from cases.models import Case
from fxrates.models import FxRate
from masterdata.models import MasterRecord
from personnel.models import Personnel

M1, M2 = months()
PDF = b"%PDF-1.7\nrehearsal synthetic document "
admin, sales = login("ui.admin"), login("ui.sales")
P = {p.name: p for p in Personnel.objects.all()}
ok = lambda r, want=(200, 201): (r.status_code in want) or sys.exit(f"FAILED {r.status_code} {r.content[:300]}")

for ym in (M1, M2):
    FxRate.objects.create(year_month=ym, currency="USD", rate="31.5" if ym == M1 else "31.2", created_by=f"personnel:{P['UI Admin'].pk}", updated_by=f"personnel:{P['UI Admin'].pk}")
MasterRecord.objects.create(entity_type="reinsurer", name="UI Re Gamma (A only)", payload={}, created_by="seed", updated_by="seed")

def body(**over):
    b = dict(reinsuranceStructure="QS", ae="UI AE One", currency="USD", classOfBusiness="Property", classCode="PAR", newOrRenew="New",
             typePrefix="Fac", reinsured="UI Cedant Insurance", originalInsured="Rehearsal Insured", policyFrom=f"{M1}-01", policyTo=f"{int(M1[:4]) + 1}{M1[4:]}-01",
             interest="Buildings", situations=[dict(address="1 Rehearsal Road", postcode="100")],
             reinsurers=[dict(name="UI Re Alpha", sharePct=60, premium=600000, riCommPct=5, taxPct=0),
                         dict(name="UI Re Beta (Facility)", sharePct=40, premium=400000, riCommPct=5, taxPct=0, foreignBroker="UI Broker")],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=100000000)], lossAdvisedDate=f"{M1}-01", lossRecordYears=5,
             originalPremium=1000000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b

def create(**over):
    r = call(sales, "post", "/api/cases", {"case": body(**over)}); ok(r)
    return r.json()["case"]["caseUid"]

def announce(uid):
    for kind, reins, name in (("offer", [], "offer.pdf"), ("signed", ["UI Re Alpha"], "signed-alpha.pdf"), ("confirmation", ["UI Re Beta (Facility)"], "conf-beta.pdf")):
        ok(call(sales, "post", "/api/case-documents", {"caseUid": uid, "kind": kind, "filename": name, "reinsurers": reins,
                                                        "base64": base64.b64encode(PDF + name.encode()).decode()}))
    docs = call(sales, "get", f"/api/case-documents?caseUid={uid}").json()
    v = Case.objects.get(case_uid=uid).row_version
    ok(call(sales, "post", "/api/case-announce", {"caseUid": uid, "rowVersion": v, "confirmed": True, "documentIds": docs["coverage"]["selected"]}))

def rv(uid): return Case.objects.get(case_uid=uid).row_version

# c1：USD，分績（人員 ID 是數字），Announce、通知會計、記付款＋沖銷、理賠＋負數付款、批單
c1 = create(splitEnabled=True, splitParties=[dict(personnelId=P["UI Sales"].pk, name="UI Sales", pct=60), dict(personnelId=P["UI Partner"].pk, name="UI Partner", pct=40)])
announce(c1)
ok(call(sales, "post", "/api/case-workflow", {"action": "notify_accounting", "caseUid": c1, "rowVersion": rv(c1), "accountingPersonnelId": P["UI Finance"].pk, "note": "rehearsal"}))
led = [x for x in call(admin, "get", "/api/accounting").json()["rows"] if x["caseUid"] == c1 and x.get("partyType") == "cedant"][0]
ok(call(admin, "post", "/api/accounting", {"action": "record_payment", "caseUid": c1, "rowVersion": rv(c1), "scheduleKey": led["scheduleKey"], "amount": 1000, "paymentDate": f"{M1}-05"}))
ok(call(admin, "post", "/api/accounting", {"action": "record_payment", "caseUid": c1, "rowVersion": rv(c1), "scheduleKey": led["scheduleKey"], "amount": 250.5, "paymentDate": f"{M1}-06"}))
first = Case.objects.get(case_uid=c1).payload["paymentEntries"][0]["id"]
ok(call(admin, "post", "/api/accounting", {"action": "reverse_payment", "caseUid": c1, "rowVersion": rv(c1), "entryId": first, "paymentDate": f"{M1}-07"}))
ok(call(sales, "post", "/api/claims", {"action": "create_claim", "caseUid": c1, "rowVersion": rv(c1), "claim": {"lossNo": "RH-LOSS-1", "dateOfLoss": f"{M1}-02", "outstandingReserve": 5000}}))
ok(call(sales, "post", "/api/claims", {"action": "record_payment", "caseUid": c1, "rowVersion": rv(c1), "claimId": 1, "payment": {"amount": 1200, "date": f"{M1}-03"}}))
ok(call(sales, "post", "/api/claims", {"action": "record_payment", "caseUid": c1, "rowVersion": rv(c1), "claimId": 1, "payment": {"amount": -200, "date": f"{M1}-04"}}))
ok(call(sales, "post", "/api/case-workflow", {"action": "create_endorsement", "caseUid": c1, "rowVersion": rv(c1)}))

# c2：TWD，分期（本月與下月）
c2 = create(currency="TWD", installmentEnabled=True, performanceInstallments=[
    dict(id="I1", performanceMonth=M1, paymentBaseDate=f"{M1}-01", premium=600000), dict(id="I2", performanceMonth=M2, paymentBaseDate=f"{M2}-01", premium=400000)])
announce(c2)

# c3：Draft，分績的人員 ID 是文字（Alpha 的舊資料可能是這樣；API 會轉成數字，所以直接寫入）
c3 = create(originalInsured="Rehearsal Draft")
p = copy.deepcopy(Case.objects.get(case_uid=c3).payload); p.update(splitEnabled=True, splitParties=[dict(personnelId=str(P["UI Partner"].pk), name="UI Partner", pct=100)])
Case.objects.filter(case_uid=c3).update(payload=p, updated_by="hatchable:collaborator-1")   # 非 personnel 的操作者要原樣保留

# c4：Draft 丟進回收桶
c4 = create(originalInsured="Rehearsal Recycled")
ok(call(admin, "post", "/api/draft-recycle-bin", {"action": "recycle", "caseUid": c4, "rowVersion": rv(c4)}))

# c5：Reverse 過、待沖銷（直接寫入 Reverse 之後的形狀；API 流程需要跨月關帳）
c5 = create(currency="TWD", originalInsured="Rehearsal Reversed")
announce(c5)
p = copy.deepcopy(Case.objects.get(case_uid=c5).payload)
p.update(reversalCycle=1, pendingReversalOffset=True, transactions=[
    dict(txNo="RH-OLD-R1-TX1", amount=500, legType="Leg 1", reversed=True, settlement="settled", source="premium"),
    dict(txNo="RH-OLD-R1-TX2", amount=450, legType="Leg 2", reversed=True, reversalOffsetApplied=True, source="premium")])
Case.objects.filter(case_uid=c5).update(payload=p, status="reversed")

# Production：本月排除 c1 的 R1（延到下月）→ 產生 → 關帳；下月只產生（留一份 valid 的版本到切換後再關）
pr = call(admin, "get", f"/api/production-report?month={M1}").json()
row = [x for x in pr["rows"] if x["caseUid"] == c1 and x["reinsurerKey"].endswith(":R1")][0]
ok(call(admin, "post", "/api/production-report", {"action": "exclude", "month": M1, "scope": "reinsurer", "reason": "waiting for signed slip", "rowId": row["id"]}))
sig = call(admin, "get", f"/api/production-report?month={M1}").json()["sourceSignature"]
rep = call(admin, "post", "/api/production-report", {"action": "generate", "month": M1, "sourceSignature": sig}); ok(rep)
rep = rep.json()["report"]
ok(call(admin, "post", "/api/production-report", {"action": "close", "month": M1, "reportUid": rep["reportUid"], "rowVersion": rep["rowVersion"], "sourceSignature": sig}))
sig2 = call(admin, "get", f"/api/production-report?month={M2}").json()["sourceSignature"]
ok(call(admin, "post", "/api/production-report", {"action": "generate", "month": M2, "sourceSignature": sig2}))

# 目標
ok(call(admin, "post", "/api/dashboard-targets", {"periodType": "annual", "periodKey": M1[:4], "amount": 5000000}))
ok(call(admin, "post", "/api/dashboard-targets", {"periodType": "monthly", "periodKey": M1, "amount": 400000}))
ok(call(admin, "post", "/api/dashboard-targets", {"periodType": "monthly", "periodKey": M2, "amount": 300000, "isActive": False}))
print("scenario done:", Case.objects.count(), "cases; statuses", sorted(Case.objects.values_list("status", flat=True)))
