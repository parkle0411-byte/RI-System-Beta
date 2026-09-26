"""
記帳 API - 對應 Hatchable Alpha 的 api/accounting.js。

  GET  /api/accounting   accounting.read   整合帳本：已 Announce／Confirmed 案件的保費付款排程（依期別與付款對象拆開）＋理賠交易
  POST /api/accounting   accounting.read   action = record_payment | reverse_payment（兩者都另外需要 accounting.write）

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - 帳本讀取全部案件（Alpha 只讀前 1000 件，其餘直接不顯示）。
  - 記付款、沖銷只接受 Announced／Confirmed 的案件（Alpha 的 API 對 Draft 也照收；畫面本來就只列這兩種）。
  - 付款日期必須是真實存在的日期（Alpha 記付款只看格式、沖銷完全不檢查）；沖銷沒給日期時預設台北的今天（Alpha 用 UTC）。
  - 補寫 Snapshot（Alpha 只寫 Audit，版本號會有缺口）。
  - 先鎖案件列，再檢查、寫入（Alpha 是事後以「除以零」檢查版本）。
  - paymentEntries／transactions 裡若有不是物件的項目就略過（Alpha 會整個帳本拋錯）；正常流程不會寫出這種資料。
"""
import re
import uuid
from datetime import date, datetime, timezone as dt_timezone

from django.db import IntegrityError, transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from, has_permission

from .calc.jsnum import (
    UNDEFINED, get, is_array, js_is_finite, js_or, js_truthy, js_slice, js_to_number, js_to_string, js_trim, json_roundtrip, money,
)
from .calc.payment_terms import build_payment_schedule, taipei_date
from .ledger import _objects, ledger_rows
from .models import Case

LEDGER_STATUSES = ("posted", "closed")
_DATE_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


def _can_edit(person):
    return has_permission(person, "accounting.write")


def _live(qs):
    return qs.filter(recycled_at__isnull=True, is_archived=False)


def _iso_now():
    now = datetime.now(dt_timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _real_date(value):
    """YYYY-MM-DD 而且是日曆上真的有的日期（2026-02-30、2026-13-45 都不行）。"""
    if not isinstance(value, str) or not _DATE_SHAPE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _text(value):
    """String(value || "")"""
    return js_to_string(js_or(value, ""))


# ------------------------------------------------------------------ 帳本

def _case_view(case):
    payload = case.payload if isinstance(case.payload, dict) and case.payload else {}
    return {
        "caseUid": str(case.case_uid), "rowVersion": case.row_version,
        "twRef": case.tw_ref or "", "status": case.status, "announcedAt": case.announced_at,
        "reinsured": js_or(payload.get("reinsured"), case.reinsured_name_snapshot, ""),
        "currency": js_or(payload.get("currency"), case.currency, ""), "payload": payload,
    }


# ------------------------------------------------------------------ View

class AccountingView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "accounting.read", "POST": "accounting.read"}

    def get(self, request):
        cases = _live(Case.objects.filter(status__in=LEDGER_STATUSES)).order_by("tw_ref", "id")
        rows, warnings = ledger_rows([_case_view(c) for c in cases])
        currencies = []
        for row in rows:  # [...new Set(currency.filter(Boolean))].sort()
            if js_truthy(row["currency"]) and row["currency"] not in currencies:
                currencies.append(row["currency"])
        currencies.sort(key=js_to_string)
        return Response(json_roundtrip({
            "ok": True, "rows": rows, "warnings": warnings, "currencies": currencies,
            "scope": {"canEdit": _can_edit(request.ri_principal)},
        }))

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        action = _text(body.get("action"))
        handlers = {"record_payment": self.record_payment, "reverse_payment": self.reverse_payment}
        if action not in handlers:
            return _error(400, "unsupported_action", "Unsupported Accounting action.")
        try:
            with transaction.atomic():
                return handlers[action](request, body)
        except IntegrityError:
            return _error(409, "payment_conflict", "This case changed while saving. Nothing was changed; refresh and try again.")

    # ---- 共用 ----
    @staticmethod
    def _load_case_for_update(case_uid):
        try:
            parsed = uuid.UUID(case_uid)
        except ValueError:
            return None
        if str(parsed) != case_uid:  # Alpha 比對 case_uid::text，只接受小寫、有連字號的標準寫法
            return None
        return _live(Case.objects.select_for_update()).filter(case_uid=parsed).first()

    @staticmethod
    def _status_error(case, verb):
        if case.status in LEDGER_STATUSES:
            return None
        return _error(409, "accounting_status_locked",
                      f"Payments can be {verb} only for Announced or Confirmed cases.")

    @staticmethod
    def _save(request, body, case, payload, action, metadata):
        actor_info = actor_from(request.ri_principal)
        expected = js_to_number(body.get("rowVersion", UNDEFINED))  # Number(undefined) 是 NaN，不是 0
        if case.row_version != expected:
            return _error(409, "version_conflict", "This case changed. Refresh Accounting and try again.")
        old_entries = case.payload.get("paymentEntries") if isinstance(case.payload, dict) else None
        before = {"rowVersion": case.row_version, "paymentEntries": js_or(old_entries, [])}
        case.payload = payload
        case.row_version += 1
        case.updated_by = actor_info["id"]
        case.save()
        record_snapshot(entity_type="case", entity_id=case.case_uid, version=case.row_version,
                        reason={"record_payment": "payment_recorded", "reverse_payment": "payment_reversed"}[action],
                        data={"caseUid": str(case.case_uid), "twRef": case.tw_ref, "status": case.status,
                              "rowVersion": case.row_version, "payload": payload},
                        created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=case.case_uid, action=action, before=before,
                     after={"rowVersion": case.row_version, "paymentEntries": payload["paymentEntries"]},
                     actor=actor_info, request_id=request_id_from(request), metadata=metadata)
        return Response({"ok": True, "rowVersion": case.row_version})

    # ---- 記付款 ----
    def record_payment(self, request, body):
        person = request.ri_principal
        if not _can_edit(person):
            return _error(403, "permission_denied", "Accounting access is required to record payments.")
        case_uid = js_trim(_text(body.get("caseUid")))
        schedule_key = js_trim(_text(body.get("scheduleKey")))
        amount = js_to_number(body.get("amount"))
        payment_date = _text(body.get("paymentDate"))
        if not case_uid or not schedule_key or not js_is_finite(amount) or amount <= 0 or not _real_date(payment_date):
            return _error(400, "invalid_payment", "Case, installment, party, payment date, and a positive amount are required.")
        case = self._load_case_for_update(case_uid)
        if case is None:
            return _error(404, "case_not_found", "Case not found.")
        locked = self._status_error(case, "recorded")
        if locked:
            return locked
        payload = json_roundtrip(case.payload if isinstance(case.payload, dict) and case.payload else {})
        item = next((i for i in build_payment_schedule(payload)["items"] if i["scheduleKey"] == schedule_key), None)
        if item is None:
            return _error(400, "schedule_not_found", "The selected installment and party no longer exist.")
        # Alpha 也檢查 item.reviewRequired，但排程項目沒有這個欄位；實際只靠「沒有到期日」擋下
        if not item["dueDate"]:
            return _error(400, "schedule_pending_review", "Confirm the installment payment base date before recording payment.")
        if amount - item["outstanding"] > 0.004:
            return _error(400, "overpayment", "Payment cannot exceed the selected installment balance.")
        actor_info = actor_from(person)
        entry = {
            "id": str(uuid.uuid4()), "entryType": "payment", "scheduleKey": schedule_key,
            "installmentId": item["installmentId"], "installmentLabel": item["installmentLabel"],
            "partyType": item["partyType"], "partyName": item["partyName"],
            "amount": money(amount), "paymentDate": payment_date,
            "note": js_slice(js_trim(_text(body.get("note"))), 0, 1000),
            "createdAt": _iso_now(), "createdBy": actor_info["id"], "createdByName": actor_info["name"],
        }
        existing = payload.get("paymentEntries")
        payload["paymentEntries"] = [*(existing if is_array(existing) else []), entry]
        return self._save(request, body, case, payload, "record_payment", {
            "paymentEntryId": entry["id"], "scheduleKey": schedule_key, "amount": entry["amount"], "paymentDate": payment_date,
        })

    # ---- 沖銷付款 ----
    def reverse_payment(self, request, body):
        person = request.ri_principal
        if not _can_edit(person):
            return _error(403, "permission_denied", "Accounting access is required to reverse payments.")
        case_uid = js_trim(_text(body.get("caseUid")))
        entry_id = js_trim(_text(body.get("entryId")))
        payment_date = _text(js_or(body.get("paymentDate"), taipei_date()))
        if not _real_date(payment_date):
            return _error(400, "invalid_payment_date", "The reversal date must be a valid date (YYYY-MM-DD).")
        case = self._load_case_for_update(case_uid)
        if case is None:
            return _error(404, "case_not_found", "Case not found.")
        locked = self._status_error(case, "reversed")
        if locked:
            return locked
        payload = json_roundtrip(case.payload if isinstance(case.payload, dict) and case.payload else {})
        entries = payload.get("paymentEntries") if is_array(payload.get("paymentEntries")) else []
        original = next((e for e in _objects(entries)
                         if get(e, "id") == entry_id and get(e, "entryType") == "payment"), None)
        if original is None:
            return _error(400, "payment_not_found", "The original payment entry was not found.")
        if any(get(e, "entryType") == "reversal" and get(e, "reversalOf") == entry_id for e in _objects(entries)):
            return _error(409, "already_reversed", "This payment has already been reversed.")
        actor_info = actor_from(person)
        reversal = {
            "id": str(uuid.uuid4()), "entryType": "reversal", "reversalOf": entry_id,
            "scheduleKey": get(original, "scheduleKey"), "installmentId": get(original, "installmentId"),
            "installmentLabel": get(original, "installmentLabel"), "partyType": get(original, "partyType"),
            "partyName": get(original, "partyName"), "amount": get(original, "amount"),
            "paymentDate": payment_date,
            "note": js_slice(js_trim(_text(body.get("note"))), 0, 1000),
            "createdAt": _iso_now(), "createdBy": actor_info["id"], "createdByName": actor_info["name"],
        }
        payload["paymentEntries"] = json_roundtrip([*entries, reversal])
        return self._save(request, body, case, payload, "reverse_payment", json_roundtrip({
            "paymentEntryId": reversal["id"], "reversalOf": entry_id,
            "scheduleKey": get(original, "scheduleKey"), "amount": get(original, "amount"),
        }))
