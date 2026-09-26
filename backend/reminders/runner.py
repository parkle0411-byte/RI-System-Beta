"""
每天的提醒排程 - 對應 Alpha api/signed-slip-reminders.js（台北 09:00）與 api/payment-reminders.js（台北 09:30）的 handler。
由 manage.py run_signed_slip_reminders／run_payment_reminders 執行（主機的 cron，見 scripts/install_reminder_cron.sh）。

流程與 Alpha 相同：找出今天該提醒的項目 → 解析收件人（缺資料就只寫「設定錯誤」的 Audit，不寄給任何人）→
在提醒表「佔位」（同一天同一件只會有一筆）→ 收件人有測試網域就記 simulated → 否則寄出（sent／failed）。

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - 寄信未啟用（settings.REMINDER_EMAIL_ENABLED = false，VM 目前的狀態）時記成 suppressed，並寫 Audit
    （suppress_signed_slip_reminder／suppress_payment_reminder）；suppressed 算「已提醒」。
  - 一次處理完當天全部項目（Alpha 受 Hatchable 限制每次 10 件、一分鐘後再接著跑），所以 moreWork 一律是 false。
  - 信件主旨與內文在佔位時就存進提醒紀錄；信件最後的連結指向 VM（settings.REMINDER_LINK_URL）。
  - 回傳多一個 suppressed 計數。
  - 缺 Signed Slip 的再保人在信件與紀錄裡顯示案件上的原始名稱（Alpha 顯示比對用的小寫鍵值）。
"""
import logging
from email.utils import make_msgid

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import record_audit
from cases.calc.payment_terms import build_payment_schedule, taipei_date
from cases.calc.jsnum import get, is_array
from cases.calc.signed_slip import is_reserved_test_email, reinsurer_key, reminder_due, taipei_today
from cases.models import Case, CaseDocument
from personnel.models import Personnel

from . import messages as msg
from .models import SUCCESS_STATUSES, PaymentAlert, SignedSlipAlert

log = logging.getLogger(__name__)
SLIP_ACTOR = {"id": "scheduler:signed-slip-reminders", "name": "Signed Slip scheduler", "role": "system"}
PAY_ACTOR = {"id": "scheduler:payment-reminders", "name": "Payment reminder scheduler", "role": "system"}


def display_names(case_data, keys):
    """
    reminder_due 回傳的是比對用的鍵值（去空白、小寫，例如 "ui re beta (facility)"）；Alpha 直接把它放進信件。
    VM 換回案件上第一個對應的原始名稱（去頭尾空白），比對邏輯不變（2026-09-26 你的決定）。
    """
    rows = get(case_data, "reinsurers")
    names = {}
    for row in rows if is_array(rows) else []:
        name = get(row, "name")
        key = reinsurer_key(name)
        if key and key not in names:
            names[key] = str(name).strip()
    return [names.get(k, k) for k in keys]


def _open_cases():
    return Case.objects.filter(status__in=("posted", "closed"), recycled_at__isnull=True, is_archived=False).order_by("id")


def _people(*extra):
    return list(Personnel.objects.filter(is_active=True).order_by("id")
                .values("id", "name", "email", "supervisor_name", "supervisor_email", *extra))


def _audit(**kw):
    with transaction.atomic():
        record_audit(source="scheduler", **kw)


def _send(recipients, subject, html, text=None):
    """真的寄出（只在 REMINDER_EMAIL_ENABLED 時呼叫）。回傳 Message-ID。"""
    message_id = make_msgid(domain=settings.REMINDER_MESSAGE_ID_DOMAIN)
    mail = EmailMultiAlternatives(subject=subject, body=text or "", from_email=settings.DEFAULT_FROM_EMAIL, to=recipients,
                                  headers={"Message-ID": message_id})
    mail.attach_alternative(html, "text/html")
    mail.send(fail_silently=False)
    return message_id


def _link():
    return settings.REMINDER_LINK_URL, settings.REMINDER_LINK_TEXT


def _finish(alert, status, actor, action, after, metadata, **fields):
    with transaction.atomic():
        type(alert).objects.filter(pk=alert.pk).update(status=status, **fields)
        record_audit(entity_type=_ENTITY[type(alert)], entity_id=alert.pk, action=action, before={"status": "pending"}, after=after,
                     actor=actor, source="scheduler", metadata=metadata)


_ENTITY = {SignedSlipAlert: "signed_slip_alert", PaymentAlert: "payment_alert"}


# ---------------------------------------------------------------- Signed Slip（台北 09:00）

def run_signed_slip(today=None):
    today = today or taipei_today()
    cases = list(_open_cases())
    files_by_case = {}
    for row in CaseDocument.objects.filter(kind="signed").values("case_id", "kind", "reinsurers"):
        files_by_case.setdefault(row["case_id"], []).append(row)
    last_by_case = {}
    for case_id, alert_on in SignedSlipAlert.objects.filter(status__in=SUCCESS_STATUSES).values_list("case_id", "alert_on"):
        text = alert_on.isoformat()
        if text > last_by_case.get(case_id, ""):
            last_by_case[case_id] = text
    people = _people()

    due_cases = []
    for case in cases:
        case_data = {**(case.payload if isinstance(case.payload, dict) else {}), "id": case.pk, "caseUid": str(case.case_uid),
                     "twRef": case.tw_ref or "", "status": case.status}
        due = reminder_due(case_data, files_by_case.get(case.pk, []), last_by_case.get(case.pk, ""), today)
        if due:
            due_cases.append((case, case_data, {**due, "missing": display_names(case_data, due["missing"])}))

    result = {"today": today, "dueToday": len(due_cases), "attempted": 0, "sent": 0, "simulated": 0, "suppressed": 0,
              "skipped": 0, "failed": 0, "configurationErrors": [], "moreWork": False}
    for case, case_data, due in due_cases:
        contact = msg.contact_for(case_data, people)
        if "error" in contact:
            error = {"caseUid": str(case.case_uid), "twRef": case.tw_ref or "", "ae": case_data.get("ae") or "", "error": contact["error"]}
            result["configurationErrors"].append(error)
            _audit(entity_type="case", entity_id=case.case_uid, action="signed_slip_configuration_error", before=None, after=error,
                   actor=SLIP_ACTOR, metadata={"alertOn": today})
            result["attempted"] += 1
            continue
        recipients = list(dict.fromkeys([contact["aeEmail"], contact["supervisorEmail"]]))
        mail = msg.reminder_message(case_data, due, contact, *_link())
        try:
            with transaction.atomic():
                alert = SignedSlipAlert.objects.create(
                    case=case, alert_on=today, policy_from=case_data.get("policyFrom"), days_since_effective=due["daysSinceEffective"],
                    missing_reinsurers=due["missing"], recipients=recipients, status="pending",
                    subject=mail["subject"], body_html=mail["html"], body_text=mail["text"])
        except IntegrityError:
            result["skipped"] += 1
            continue
        result["attempted"] += 1
        base = {"caseUid": str(case.case_uid), "alertOn": today, "recipients": recipients, "missingReinsurers": due["missing"]}
        meta = {"caseUid": str(case.case_uid)}
        now = timezone.now()
        if any(is_reserved_test_email(r) for r in recipients):
            _finish(alert, "simulated", SLIP_ACTOR, "simulate_signed_slip_reminder", {"status": "simulated", **base}, meta, sent_at=now)
            result["simulated"] += 1
        elif not settings.REMINDER_EMAIL_ENABLED:
            _finish(alert, "suppressed", SLIP_ACTOR, "suppress_signed_slip_reminder",
                    {"status": "suppressed", **base, "subject": mail["subject"], "reason": "reminder e-mail is not enabled on the VM"},
                    meta, sent_at=now)
            result["suppressed"] += 1
        else:
            try:
                message_id = _send(recipients, mail["subject"], mail["html"], mail["text"])
            except Exception as exc:  # noqa: BLE001 - 同 Alpha：任何寄信錯誤都記成 failed
                error_message = str(exc)[:1000]
                _finish(alert, "failed", SLIP_ACTOR, "fail_signed_slip_reminder", {"status": "failed", **base, "error": error_message},
                        meta, error=error_message)
                result["failed"] += 1
                continue
            _finish(alert, "sent", SLIP_ACTOR, "send_signed_slip_reminder", {"status": "sent", **base, "messageId": message_id},
                    meta, sent_at=timezone.now(), message_id=message_id)
            result["sent"] += 1
    return result


# ---------------------------------------------------------------- 付款提醒（台北 09:30）

def run_payment(today=None):
    today = today or taipei_date()
    cases = list(_open_cases())
    people = _people("role_code")
    finance = msg.finance_emails(people)
    success = {}
    for case_id, kind, keys, alert_date in PaymentAlert.objects.filter(status__in=SUCCESS_STATUSES).values_list(
            "case_id", "alert_kind", "schedule_keys", "alert_date"):
        for key in keys if isinstance(keys, list) else []:
            index = f"{case_id}::{key}::{kind}"
            text = alert_date.isoformat()
            if text > success.get(index, ""):
                success[index] = text

    due = []
    for case in cases:
        case_data = {**(case.payload if isinstance(case.payload, dict) else {}), "id": case.pk, "caseUid": str(case.case_uid),
                     "twRef": case.tw_ref or ""}
        grouped = {}
        for item in build_payment_schedule(case_data)["items"]:
            dates = {k: success.get(f"{case.pk}::{item.get('scheduleKey')}::{k}", "") for k in ("seven_days_before", "due_today", "weekly_overdue")}
            kind = msg.due_kind(item, today, dates)
            if kind:
                grouped.setdefault(kind, []).append(item)
        due.extend((case, case_data, kind, items) for kind, items in grouped.items())

    result = {"today": today, "dueToday": len(due), "attempted": 0, "sent": 0, "simulated": 0, "suppressed": 0,
              "skipped": 0, "failed": 0, "configurationErrors": [], "moreWork": False}
    for case, case_data, kind, items in due:
        resolved = msg.resolve_recipients(case_data, people, finance)
        if "error" in resolved:
            error = {"caseUid": str(case.case_uid), "twRef": case.tw_ref or "", "error": resolved["error"]}
            result["configurationErrors"].append(error)
            _audit(entity_type="case", entity_id=case.case_uid, action="payment_reminder_configuration_error", before=None, after=error,
                   actor=PAY_ACTOR, metadata={"alertDate": today, "alertKind": kind})
            result["attempted"] += 1
            continue
        recipients = resolved["recipients"]
        mail = msg.message(case_data, kind, items, *_link())
        alert = _claim_payment(case, today, kind, [i.get("scheduleKey") for i in items], recipients, mail)
        if alert is None:
            result["skipped"] += 1
            continue
        result["attempted"] += 1
        meta = {"caseUid": str(case.case_uid), "alertDate": today, "alertKind": kind}
        now = timezone.now()
        if any(is_reserved_test_email(r) for r in recipients):
            _finish(alert, "simulated", PAY_ACTOR, "simulate_payment_reminder", {"status": "simulated", "recipients": recipients}, meta, sent_at=now)
            result["simulated"] += 1
        elif not settings.REMINDER_EMAIL_ENABLED:
            _finish(alert, "suppressed", PAY_ACTOR, "suppress_payment_reminder",
                    {"status": "suppressed", "recipients": recipients, "subject": mail["subject"],
                     "reason": "reminder e-mail is not enabled on the VM"}, meta, sent_at=now)
            result["suppressed"] += 1
        else:
            try:
                _send(recipients, mail["subject"], mail["html"])
            except Exception as exc:  # noqa: BLE001 - 同 Alpha：記成 failed（Alpha 這裡不寫 Audit）
                PaymentAlert.objects.filter(pk=alert.pk).update(status="failed", error_message=str(exc)[:1000])
                result["failed"] += 1
                continue
            _finish(alert, "sent", PAY_ACTOR, "send_payment_reminder", {"status": "sent", "recipients": recipients}, meta, sent_at=timezone.now())
            result["sent"] += 1
    return result


def _claim_payment(case, today, kind, keys, recipients, mail):
    """
    Alpha：INSERT … ON CONFLICT (case_id, alert_date, alert_kind) DO UPDATE SET status = 'pending', error_message = NULL
    WHERE status = 'failed' RETURNING id —— 同一天失敗過的可以重新佔位，其他狀態一律略過。
    重新佔位時同 Alpha 保留原本的 recipients／schedule_keys；主旨與內文（VM 才有）更新成這次要寄的內容。
    """
    try:
        with transaction.atomic():
            return PaymentAlert.objects.create(case=case, alert_date=today, alert_kind=kind, schedule_keys=keys, recipients=recipients,
                                               status="pending", subject=mail["subject"], body_html=mail["html"])
    except IntegrityError:
        pass
    with transaction.atomic():
        alert = PaymentAlert.objects.select_for_update().filter(case=case, alert_date=today, alert_kind=kind).first()
        if alert is None or alert.status != "failed":
            return None
        PaymentAlert.objects.filter(pk=alert.pk).update(status="pending", error_message=None, subject=mail["subject"], body_html=mail["html"])
        alert.refresh_from_db()
        return alert
