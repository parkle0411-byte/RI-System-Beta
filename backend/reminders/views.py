"""
案件的提醒紀錄 - VM 才有（Alpha 沒有畫面，只能看資料表與 Audit）。案件明細的「Reminders」分頁使用（2026-09-26 你的決定）。

  GET /api/case-reminders?caseUid=…   與案件列表相同的權限（看得到這個案件的人）
    signedSlip／payment        這個案件的提醒紀錄（新到舊），含產生當下存下的信件主旨與內文
    configurationErrors        排程因聯絡資料不完整而沒有提醒的紀錄（來自 Audit：*_configuration_error），最近 60 筆
    emailEnabled               VM 是否真的會寄信（目前 false：提醒記成 suppressed）
"""
import uuid

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditLog
from cases.calc.jsnum import js_or, js_to_string, js_trim
from cases.views import visible_cases
from ri_system.authz import NoStoreMixin, RIPermission

from .messages import label
from .models import PaymentAlert, SignedSlipAlert

CONFIG_ACTIONS = {"signed_slip_configuration_error": "signed_slip", "payment_reminder_configuration_error": "payment"}


def _time(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


class CaseRemindersView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "dashboard.read"}   # 同 GET /api/cases；實際範圍由 visible_cases 決定

    def get(self, request):
        raw = js_trim(js_to_string(js_or(request.query_params.get("caseUid"), "")))
        try:
            parsed = uuid.UUID(raw)
        except ValueError:
            parsed = None
        case = visible_cases(request.ri_principal).filter(case_uid=parsed).first() if parsed else None
        if case is None:
            return Response({"error": "case_not_found", "message": "Case was not found."}, status=404)
        slip = [{
            "id": str(a.pk), "alertOn": a.alert_on.isoformat(), "status": a.status, "recipients": a.recipients,
            "missingReinsurers": a.missing_reinsurers, "daysSinceEffective": a.days_since_effective,
            "subject": a.subject, "bodyHtml": a.body_html, "bodyText": a.body_text, "error": a.error, "messageId": a.message_id,
            "createdAt": _time(a.created_at), "sentAt": _time(a.sent_at),
        } for a in SignedSlipAlert.objects.filter(case=case).order_by("-alert_on", "-created_at")]
        payment = [{
            "id": str(a.pk), "alertDate": a.alert_date.isoformat(), "alertKind": a.alert_kind, "alertLabel": label(a.alert_kind),
            "status": a.status, "recipients": a.recipients, "scheduleKeys": a.schedule_keys, "subject": a.subject,
            "bodyHtml": a.body_html, "errorMessage": a.error_message, "createdAt": _time(a.created_at), "sentAt": _time(a.sent_at),
        } for a in PaymentAlert.objects.filter(case=case).order_by("-alert_date", "-created_at")]
        errors = [{
            "at": _time(e.occurred_at), "reminder": CONFIG_ACTIONS[e.action],
            "alertDate": (e.metadata or {}).get("alertOn") or (e.metadata or {}).get("alertDate"),
            "alertKind": (e.metadata or {}).get("alertKind"), "error": (e.after_data or {}).get("error"),
        } for e in AuditLog.objects.filter(entity_type="case", entity_id=str(case.case_uid), action__in=list(CONFIG_ACTIONS))
                              .order_by("-occurred_at", "-id")[:60]]
        return Response({"ok": True, "caseUid": str(case.case_uid), "emailEnabled": settings.REMINDER_EMAIL_ENABLED,
                         "signedSlip": slip, "payment": payment, "configurationErrors": errors})
