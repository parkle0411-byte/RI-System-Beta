import json
from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import transaction
from django.test import Client, override_settings
from django.utils import timezone
from audit.models import AuditLog
from cases.calc.payment_terms import build_payment_schedule
from cases.calc.accounting import build_premium_transactions
from cases.cash_ledger import transaction_details
from cases.models import Case, CaseDocument
from personnel.models import Personnel
from reminders import runner
from reminders.models import PaymentAlert, SignedSlipAlert

User = get_user_model()
results = []
def check(n, ok, d=""): results.append((n, bool(ok), d))
class Rollback(Exception): pass
_seq = [0]
def person(name, role="sales", dept="reinsurance", **kw):
    return Personnel.objects.create(name=name, department=dept, role_code=role, created_by="t", updated_by="t", **kw)
def new_client(): return Client(enforce_csrf_checks=True, HTTP_HOST="localhost", raise_request_exception=False)
def call(c, m, url, body=None):
    c.get("/api/auth/csrf"); kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    return getattr(c, m)(url, data=json.dumps(body), content_type="application/json", **kw) if body is not None else getattr(c, m)(url, **kw)
def account(p, tag):
    u = User.objects.create_user(username=f"zz.rem.{tag}", password="Rem-Test-Pass-1")
    p.auth_user_id = str(u.pk); p.account_status = "active"; p.save()
    c = new_client(); cache.clear(); c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": u.username, "password": "Rem-Test-Pass-1"}), content_type="application/json", HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c

def ready(**over):
    b = dict(reinsuranceStructure="QS", ae="ZZ REM AE", currency="USD", classOfBusiness="ZZ Class", classCode="PAR", newOrRenew="New", typePrefix="ZZ Type",
             reinsured="ZZ Rem Cedant", originalInsured="ZZ Rem Insured", policyFrom="2026-03-01", policyTo="2027-03-01", interest="Buildings",
             situations=[dict(address="1 ZZ Road", postcode="100")],
             # 2026-10-16 92 項規則（第 31 項）：每家普通再保人天數須明確填寫，沒有預設值
             reinsurers=[dict(name="ZZ Re A", sharePct=60, premium=600, riCommPct=5, taxPct=0, paymentTermsDays=30), dict(name="ZZ Re B", sharePct=40, premium=400, riCommPct=5, taxPct=0, paymentTermsDays=30)],
             limitOfLiability=1000000, deductibles="10%", originalConditions="As original", occupation="Office", construction="Concrete",
             sumInsured=[dict(category="Building", amount=1000000)], lossAdvisedDate="2026-02-01", lossRecordYears=5,
             originalPremium=1000, paymentTermsDays=30, riCommPct=10, taxPct=0)
    b.update(over); return b
_ref = [0]
def make_case(c, status="posted", **over):
    r = call(c, "post", "/api/cases", {"case": ready(**over)}); assert r.status_code == 201, r.content
    case = Case.objects.get(case_uid=r.json()["case"]["caseUid"])
    if status != "draft":
        _ref[0] += 1
        # 2026-10-16 92 項規則：財務提醒依正式帳款（已建立的保費交易）；合成案件直接建立對應交易
        ref = f"ZZ-REM-{_ref[0]:04d}"
        Case.objects.filter(pk=case.pk).update(status=status, tw_ref=ref, announced_at=timezone.now(),
                                               payload={**case.payload, "transactions": build_premium_transactions({**case.payload, "twRef": ref})})
    case.refresh_from_db(); return case
def d(s, n=0): return (date.fromisoformat(s) + timedelta(days=n)).isoformat()
def slips(case): return list(SignedSlipAlert.objects.filter(case=case).order_by("alert_on"))
def pays(case): return list(PaymentAlert.objects.filter(case=case).order_by("alert_date", "alert_kind"))
def audits(action, entity=None): q = AuditLog.objects.filter(action=action); return q.filter(entity_id=str(entity)) if entity else q
def signed_doc(case, names):
    import uuid, hashlib
    CaseDocument.objects.create(id=uuid.uuid4(), case=case, kind="signed", reinsurers=names, filename="s.pdf", content_type="application/pdf",
                                byte_size=4, sha256=hashlib.sha256(b"%PDF").hexdigest(), storage_key=f"zz/{uuid.uuid4()}.pdf", is_selected=True, uploaded_by="t")
PDF_FROM = "2026-03-01"
DAY60 = d(PDF_FROM, 60)   # 2026-04-30

try:
    # 2026-10-16：財務提醒信獨立由 RI_PAYMENT_REMINDER_ENABLED（PAYMENT_REMINDER_EMAIL_ENABLED）控制，不連動 Signed Slip 開關
    with transaction.atomic(), override_settings(REMINDER_EMAIL_ENABLED=False, PAYMENT_REMINDER_EMAIL_ENABLED=False, REMINDER_LINK_URL="http://vm.example/ri", REMINDER_LINK_TEXT="開啟 VM"):
        ae = person("ZZ REM AE", email="ZZ.AE@tw-insure.com", supervisor_name="ZZ Boss", supervisor_email="zz.boss@tw-insure.com")
        person("ZZ REM Finance", role="accounting", dept="finance", email="zz.fin@tw-insure.com")
        sales_p = person("ZZ REM Sales")
        sales = account(sales_p, "sales")
        viewer_p = person("ZZ REM Viewer", role="viewer", dept="business_1")
        viewer = account(viewer_p, "viewer")
        fin_p = person("ZZ REM Fin2", role="accounting", dept="finance")
        fin = account(fin_p, "fin")

        # ================= Signed Slip =================
        a = make_case(sales)
        draft = make_case(sales, "draft")
        signed_doc(a, ["ZZ Re A"])
        r = runner.run_signed_slip(d(DAY60, -1))
        check("day 59: nothing due for our case", not slips(a))
        r = runner.run_signed_slip(DAY60)
        al = slips(a)
        check("day 60: one alert, status suppressed (e-mail not enabled)", len(al) == 1 and al[0].status == "suppressed" and al[0].sent_at, [(x.status) for x in al])
        check("alert data: missing only the reinsurer without a Signed Slip (original name, VM), days 60, policy_from", al and al[0].missing_reinsurers == ["ZZ Re B"]
              and al[0].days_since_effective == 60 and al[0].policy_from.isoformat() == PDF_FROM, al and (al[0].missing_reinsurers, al[0].days_since_effective))
        check("recipients: AE and supervisor e-mails as stored (Signed Slip does not lower-case)", al and al[0].recipients == ["ZZ.AE@tw-insure.com", "zz.boss@tw-insure.com"], al and al[0].recipients)
        check("preview stored: subject, text and HTML with the VM link", al and al[0].subject.startswith("[Signed Slip 逾期警示] ZZ-REM-")
              and "尚缺 1 家" in al[0].subject and "• ZZ Re B" in al[0].body_text and "<li>ZZ Re B</li>" in al[0].body_html and '<a href="http://vm.example/ri">開啟 VM</a>' in al[0].body_html, al and al[0].subject)
        check("result counts suppressed and moreWork false", r["suppressed"] >= 1 and r["moreWork"] is False and r["today"] == DAY60, r)
        au = audits("suppress_signed_slip_reminder", al[0].pk if al else None).first()
        check("audit suppress_signed_slip_reminder (scheduler actor, reason)", au and au.actor_id == "scheduler:signed-slip-reminders" and au.source == "scheduler"
              and au.after_data["status"] == "suppressed" and "not enabled" in au.after_data["reason"], au and au.after_data)
        check("draft cases are never reminded", not slips(draft))
        r = runner.run_signed_slip(DAY60)
        check("same day again: not due any more (next one is 7 days later), still one alert", len(slips(a)) == 1
              and not any(e["caseUid"] == str(a.case_uid) for e in r["configurationErrors"]))
        runner.run_signed_slip(d(DAY60, 6))
        check("suppressed counts as reminded: day 66 nothing new", len(slips(a)) == 1)
        runner.run_signed_slip(d(DAY60, 7))
        check("day 67: weekly reminder again", len(slips(a)) == 2)

        b = make_case(sales)
        Personnel.objects.filter(pk=ae.pk).update(supervisor_email="boss@example.com")
        runner.run_signed_slip(DAY60)
        al = slips(b)
        check("reserved test domain in recipients -> simulated (Alpha), not suppressed", len(al) == 1 and al[0].status == "simulated")
        check("audit simulate_signed_slip_reminder", audits("simulate_signed_slip_reminder", al[0].pk if al else None).exists())
        Personnel.objects.filter(pk=ae.pk).update(supervisor_email="zz.boss@tw-insure.com")

        c = make_case(sales, ae="ZZ REM Nobody")
        runner.run_signed_slip(DAY60)
        err = audits("signed_slip_configuration_error", c.case_uid).first()
        check("AE without a Personnel record -> configuration error audit, no alert", not slips(c) and err and err.after_data["error"] == "AE does not match one active Personnel record."
              and err.metadata == {"alertOn": DAY60}, err and err.after_data)

        signed_doc(a, ["ZZ Re B"])
        runner.run_signed_slip(d(DAY60, 14))
        check("all Signed Slips uploaded -> no more reminders", len(slips(a)) == 2)

        # 真的寄出（寄信啟用；locmem 郵件）
        e = make_case(sales)
        with override_settings(REMINDER_EMAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", DEFAULT_FROM_EMAIL="ri@tw-insure.com"):
            mail.outbox = []
            runner.run_signed_slip(DAY60)
            al = slips(e)
            sent = [m for m in mail.outbox if e.tw_ref in m.subject]
            check("e-mail enabled: status sent with a Message-ID", len(al) == 1 and al[0].status == "sent" and al[0].message_id and al[0].message_id.startswith("<"), al and (al[0].status, al[0].message_id))
            check("e-mail enabled: one message to AE + supervisor with text and HTML parts", len(sent) == 1 and sent[0].to == ["ZZ.AE@tw-insure.com", "zz.boss@tw-insure.com"]
                  and sent[0].alternatives and sent[0].alternatives[0][0] == al[0].body_html and sent[0].body == al[0].body_text
                  and sent[0].body.startswith("Account Executive ") and sent[0].alternatives[0][0].startswith("<p>Account Executive "), sent and sent[0].to)
            check("audit send_signed_slip_reminder with messageId", audits("send_signed_slip_reminder", al[0].pk).filter(after_data__messageId=al[0].message_id).exists())
            f = make_case(sales)
            real_send = runner._send
            runner._send = lambda *a_, **k: (_ for _ in ()).throw(OSError("smtp down"))
            try:
                runner.run_signed_slip(DAY60)
                al = slips(f)
                check("send failure -> failed with the error, audit fail_signed_slip_reminder", len(al) == 1 and al[0].status == "failed" and al[0].error == "smtp down"
                      and audits("fail_signed_slip_reminder", al[0].pk).exists())
                runner.run_signed_slip(DAY60)
                check("failed: same day is not retried (Alpha: ON CONFLICT DO NOTHING)", len(slips(f)) == 1)
            finally:
                runner._send = real_send
            runner.run_signed_slip(d(DAY60, 1))
            check("failed does not count as reminded: next day sends again", [x.status for x in slips(f)] == ["failed", "sent"], [x.status for x in slips(f)])

        # ================= 付款提醒 =================
        p = make_case(sales, policyFrom="2026-08-01", policyTo="2027-08-01")
        # 2026-10-16 92 項規則（第 83、84 項）：提醒以正式帳款的「實際約定到期日」前 7 日、到期日、其後每 7 日（不再用提前 15／10 日的會計日）
        details = transaction_details({**p.payload, "id": p.pk})
        items = [{**x, "scheduleKey": "transaction:" + no} for no, x in details.items()]
        due = sorted({i["contractDueDate"] for i in items if i.get("contractDueDate")})
        check("synthetic case has posted transactions with an actual due date", len(due) >= 1, items[:2])
        first = min((i for i in items if i.get("contractDueDate")), key=lambda i: i["contractDueDate"])
        D, K = first["contractDueDate"], first["scheduleKey"]
        check("actual due date is policy date + 30 days, not the 15-day-earlier screen date", D == "2026-08-31", D)
        kinds = lambda case: [x.alert_kind for x in pays(case) if K in x.schedule_keys]   # 只追蹤同一個付款項目
        runner.run_payment(d(D, -8))
        check("8 days before: nothing", not pays(p))
        runner.run_payment(d(D, -7))
        al = pays(p)
        check("7 days before: seven_days_before suppressed", [x.alert_kind for x in al] == ["seven_days_before"] and al[0].status == "suppressed", [(x.alert_kind, x.status) for x in al])
        rec = al[0].recipients if al else []
        check("recipients: AE and supervisor lower-cased, then every Finance e-mail, no duplicates",
              rec[:2] == ["zz.ae@tw-insure.com", "zz.boss@tw-insure.com"] and "zz.fin@tw-insure.com" in rec and len(rec) == len(set(rec)), rec)
        check("schedule keys stored for the reminded items", al and al[0].schedule_keys and all(k in {i["scheduleKey"] for i in items} for k in al[0].schedule_keys))
        # 2026-10-16 92 項規則：逾期改以實際約定到期「日」判斷，帳款不再有 12:00 時點，信件不再寫 12:00；改驗信件列出實際到期日
        check("preview: subject '[Payment 7 天後到期] <TW Ref>' and VM link", al and al[0].subject == f"[Payment 7 天後到期] {p.tw_ref}"
              and '<a href="http://vm.example/ri">開啟 VM</a>' in al[0].body_html, al and al[0].subject)
        check("preview body states the actual due date that triggered the notice", al and f"{D} (Taiwan)" in al[0].body_html, al and al[0].body_html)
        check("audit suppress_payment_reminder with metadata", audits("suppress_payment_reminder", al[0].pk).filter(
            metadata__alertKind="seven_days_before", metadata__caseUid=str(p.case_uid)).exists())
        runner.run_payment(d(D, -3))
        check("already reminded (suppressed counts): no second 7-day notice", kinds(p) == ["seven_days_before"], kinds(p))
        runner.run_payment(D)
        check("due date: due_today", kinds(p) == ["seven_days_before", "due_today"], kinds(p))
        runner.run_payment(d(D, 6))
        check("6 days overdue: nothing new", kinds(p) == ["seven_days_before", "due_today"], kinds(p))
        runner.run_payment(d(D, 7))
        check("7 days overdue: weekly_overdue", kinds(p) == ["seven_days_before", "due_today", "weekly_overdue"], kinds(p))
        # 2026-10-21 待確認（未改斷言）：2026-09-26 規則「suppressed 算已提醒」；10/16 程式改為 suppressed 不算成功，
        # 不寄信模式下 D+7 之後每天都新增一筆逾期提醒。10/16 規則文字未明示取代，故保留原每 7 日斷言待業主確認。
        runner.run_payment(d(D, 13))
        check("weekly cadence anchored to the last weekly reminder: day 13 nothing", len(kinds(p)) == 3, kinds(p))
        runner.run_payment(d(D, 14))
        check("day 14: next weekly reminder", kinds(p) == ["seven_days_before", "due_today", "weekly_overdue", "weekly_overdue"], kinds(p))
        runner.run_payment(d(D, 20))
        check("day 20: nothing (anchored to the latest weekly reminder, day 14)", len(kinds(p)) == 4, kinds(p))
        runner.run_payment(d(D, 21))
        check("day 21: third weekly reminder", kinds(p)[-3:] == ["weekly_overdue"] * 3 and len(kinds(p)) == 5, kinds(p))

        # 失敗後同一天可以重新佔位
        q = make_case(sales, policyFrom="2026-08-01", policyTo="2027-08-01")
        with override_settings(PAYMENT_REMINDER_EMAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            real_send = runner._send
            runner._send = lambda *a_, **k: (_ for _ in ()).throw(OSError("smtp down"))
            try:
                runner.run_payment(d(D, -7))
            finally:
                runner._send = real_send
            al = pays(q)
            check("payment send failure -> failed with error_message", len(al) == 1 and al[0].status == "failed" and al[0].error_message == "smtp down")
            mail.outbox = []
            runner.run_payment(d(D, -7))
            al = pays(q)
            check("same day retry after failure (Alpha: DO UPDATE WHERE status = 'failed') -> sent, still one row",
                  len(al) == 1 and al[0].status == "sent" and any(q.tw_ref in m.subject for m in mail.outbox), [(x.status) for x in al])

        # 沒有任何 Finance 的 e-mail
        Personnel.objects.filter(role_code__in=["accounting", "accounting_manager"]).update(email=None)
        s = make_case(sales, policyFrom="2026-08-01", policyTo="2027-08-01")
        r = runner.run_payment(d(D, -7))
        err = audits("payment_reminder_configuration_error", s.case_uid).first()
        # 2026-10-16 92 項規則（第 85 項）：有效收件人先寄，缺漏另提示；收件人只含啟用中 Finance Staff（不再含 Finance Manager）
        check("no active Finance e-mail -> AE and supervisor still reminded, missing Finance reported separately",
              [x.recipients for x in pays(s)] == [["zz.ae@tw-insure.com", "zz.boss@tw-insure.com"]] and not err
              and any(e["caseUid"] == str(s.case_uid) and e.get("partialDelivery") and e["error"] == "No active Finance Staff has a valid email." for e in r["configurationErrors"]),
              ([x.recipients for x in pays(s)], [e for e in r["configurationErrors"] if e["caseUid"] == str(s.case_uid)]))

        # ================= 案件明細的 Reminders API =================
        r = call(sales, "get", f"/api/case-reminders?caseUid={p.case_uid}")
        j = r.json()
        check("API: 200 with every payment reminder of the case, newest first, label and preview", r.status_code == 200 and len(j["payment"]) == len(pays(p))
              and j["payment"][0]["alertDate"] == max(x.alert_date for x in pays(p)).isoformat()
              and {x["alertKind"]: x["alertLabel"] for x in j["payment"]}.get("weekly_overdue") == "逾期每週提醒"
              and all(x["bodyHtml"] and x["subject"] for x in j["payment"]) and j["emailEnabled"] is False, j.get("payment", [])[:1])
        r = call(sales, "get", f"/api/case-reminders?caseUid={a.case_uid}")
        j = r.json()
        check("API: Signed Slip reminders newest first", [x["alertOn"] for x in j["signedSlip"]] == [d(DAY60, 7), DAY60] and j["signedSlip"][0]["status"] == "suppressed")
        j = call(sales, "get", f"/api/case-reminders?caseUid={c.case_uid}").json()
        errs = j["configurationErrors"]
        logged = [e for e in errs if e["at"]]
        # 2026-10-16 第 85 項：有效收件人（Finance）先寄，AE 缺漏不再整封擋下寫 Audit 錯誤，而是在 API 最上方另列即時缺漏提示（at 為空）；
        # Audit 紀錄仍新到舊。此時 Finance e-mail 已被上一段清空，所以即時提示同時列出 AE 與 Finance 缺漏。
        check("API: configuration errors from the Audit Log (both reminders, newest first) plus the live payment contact warning", any(e["reminder"] == "signed_slip" and e["alertDate"] == DAY60
              and e["error"] == "AE does not match one active Personnel record." for e in logged)
              and errs[0]["reminder"] == "payment" and errs[0]["at"] is None and errs[0]["alertKind"] == "contact_missing" and "AE does not match one active Personnel record." in errs[0]["error"]
              and [e["at"] for e in logged] == sorted([e["at"] for e in logged], reverse=True), errs[:3])
        check("API: viewer cannot see a case that is not theirs -> 404", call(viewer, "get", f"/api/case-reminders?caseUid={p.case_uid}").status_code == 404)
        check("API: Finance can inspect case reminders under the approved all-case read permission", call(fin, "get", f"/api/case-reminders?caseUid={p.case_uid}").status_code == 200)
        check("API: unknown case -> 404", call(sales, "get", "/api/case-reminders?caseUid=00000000-0000-4000-8000-000000000000").status_code == 404)
        raise Rollback()
except Rollback:
    pass
fails = [x for x in results if not x[1]]
for n, ok, dd in results: print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   <-- {dd}"))
print(f"\n{len(results)-len(fails)}/{len(results)} passed; database changes rolled back")
print("after rollback: ZZ people =", Personnel.objects.filter(name__startswith="ZZ REM").count(), "| ZZ cases =", Case.objects.filter(payload__originalInsured="ZZ Rem Insured").count(),
      "| alerts =", SignedSlipAlert.objects.count() + PaymentAlert.objects.count())
