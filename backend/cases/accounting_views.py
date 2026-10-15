"""
記帳 API - 對應 Hatchable Alpha 的 api/accounting.js。

  GET  /api/accounting   accounting.read   整合帳本：已 Announce／Confirmed 案件的保費付款排程（依期別與付款對象拆開）＋理賠交易
    transactionRows：實際 SoA 保費與理賠交易，含 Reversed 案件歷史；rows 保留付款排程。
  POST /api/accounting   accounting.read   action = record_transaction_payments | reverse_batch_payment | record_payment | reverse_payment（均需要 accounting.write）

以下原本是 VM 與 Alpha v53 的差異，2026-09-29 已同步回 Alpha v56（兩邊行為相同，見 VM-RULES.md）：
  - 帳本讀取全部案件（v53 只讀前 1000 件）。
  - 記付款、沖銷只接受 Announced／Confirmed 的案件。
  - 付款日期必須是真實存在的日期；沖銷沒給日期時預設台北的今天。
  - 每次記付款、沖銷補寫 Snapshot。
  - paymentEntries／transactions 裡若有不是物件的項目就略過；正常流程不會寫出這種資料。
仍然不同的只有並行控制的寫法：VM 先鎖案件列再檢查、寫入；Alpha 是事後以「除以零」檢查版本（結果相同）。
"""
import logging
import re
import uuid
from datetime import date, datetime, timezone as dt_timezone

from django.db import IntegrityError, transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from coordination.services import PRODUCTION_SOURCES, serialized
from audit.services import record_audit, record_snapshot, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from, has_permission

from .calc.jsnum import (
    UNDEFINED, get, is_array, js_is_finite, js_locale_key_cached, js_or, js_truthy, js_slice, js_to_number, js_to_string, js_trim, json_roundtrip, money,
)
from .calc.payment_terms import build_payment_schedule, taipei_date
from .ledger import _objects, ledger_rows
from .shared_compute import CaseCompute
from .models import Case
from .transaction_ledger import transaction_rows
from .cash_ledger import payment_batches
from .transaction_payments import record_transaction_payments, reverse_batch_payment
from .calc.swiss_facility import applies as swiss_applies, DISPLAY_FIELDS, reset_after_changes, payment_error, case_payload
from .swiss_accounting import swiss_action

log = logging.getLogger(__name__)
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
    payload = case_payload(case, copy_payload=False)   # 只讀：這份 payload 只用來算列表，不複製整份（2026-10-15 效能）
    return {
        "caseUid": str(case.case_uid), "rootCaseUid": str(case.parent_case.case_uid) if case.parent_case_id else str(case.case_uid), "rowVersion": case.row_version,
        "twRef": case.tw_ref or "", "status": case.status, "announcedAt": case.announced_at,
        "reinsured": js_or(payload.get("reinsured"), case.reinsured_name_snapshot, ""),
        "currency": js_or(payload.get("currency"), case.currency, ""), "payload": payload,
    }


# ------------------------------------------------------------------ View

class AccountingView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "accounting.read", "POST": "accounting.read"}

    def get(self, request):
        cases = _live(Case.objects.filter(status__in=(*LEDGER_STATUSES, "reversed"))).select_related("parent_case").order_by("tw_ref", "id")
        # 2026-10-14：逐案計算；某一案的資料無法解讀時只略過該案並列入 warnings，其他案件照常顯示
        case_views, rows, warnings, transactions, swiss_rows = [], [], [], [], []
        now = datetime.now(dt_timezone.utc)   # 整個請求用同一個時間
        for case in cases:
            try:
                c = _case_view(case)
                shared = {c["caseUid"]: CaseCompute(c, now)}   # 付款排程與交易明細每件案件只算一次，三處共用
                case_rows, case_warnings = ledger_rows([c], now, shared) if c["status"] in LEDGER_STATUSES else ([], [])
                case_transactions = transaction_rows([c], shared)
                case_swiss = []
                if c["status"] in LEDGER_STATUSES and swiss_applies(c["payload"]):
                    for item in shared[c["caseUid"]].schedule("raw")["items"]:
                        case_swiss.append({**item, "key": c["caseUid"] + ":" + item["scheduleKey"], "caseUid": c["caseUid"],
                                           "caseRowVersion": c["rowVersion"], "twRef": c["twRef"], "rootCaseUid": c["rootCaseUid"],
                                           "entries": [e for e in _objects(c["payload"].get("paymentEntries")) if e.get("scheduleKey") == item["scheduleKey"]]})
            except Exception:  # noqa: BLE001 - 單一案件資料損壞不能讓整個 Accounting 失敗
                log.exception("Accounting could not read case %s", case.case_uid)
                warnings.append({"caseUid": str(case.case_uid), "twRef": case.tw_ref or "", "dataError": True,
                                 "issues": ["This case's accounting data could not be read and is not shown. Contact the System Administrator."]})
                continue
            case_views.append(c)
            rows.extend(case_rows)
            warnings.extend(case_warnings)
            transactions.extend(case_transactions)
            swiss_rows.extend(case_swiss)
        # 與 ledger_rows 相同的排序（twRef，再依到期日；穩定排序）
        rows.sort(key=lambda r: (js_locale_key_cached(r["twRef"]), js_locale_key_cached(_text(r.get("dueDate")))))
        currencies = []
        for row in [*rows, *transactions]:  # Include currencies in historical transactions.
            if js_truthy(row["currency"]) and row["currency"] not in currencies:
                currencies.append(row["currency"])
        currencies.sort(key=js_to_string)
        return Response(json_roundtrip({
            "ok": True, "rows": rows, "transactionRows": transactions, "warnings": warnings, "currencies": currencies,
            "scope": {"canEdit": _can_edit(request.ri_principal)},
            "cashBatches": payment_batches(case_views), "swissRows": swiss_rows,
        }))

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        action = _text(body.get("action"))
        handlers = {"record_payment": self.record_payment, "reverse_payment": self.reverse_payment,
                    "record_transaction_payments": lambda r, b: record_transaction_payments(self,r,b),
                    "reverse_batch_payment": lambda r, b: reverse_batch_payment(self,r,b)}
        for swiss_handler in ("confirm_swiss_collection", "unconfirm_swiss_collection", "record_swiss_clearance", "record_swiss_offset", "mark_swiss_statement"):
            handlers[swiss_handler] = lambda r, b: swiss_action(self, r, b)
        from .facility_accounting import settlement_action
        for manual_action in ('confirm_facility_settlement', 'unconfirm_facility_settlement'):
            handlers[manual_action] = lambda r, b: settlement_action(self, r, b)
        if action not in handlers:
            return _error(400, "unsupported_action", "Unsupported Accounting action.")
        try:
            with serialized(PRODUCTION_SOURCES):
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
        reset_after_changes(case.payload or {}, payload, _iso_now())
        case.payload = payload
        case.row_version += 1
        case.updated_by = actor_info["id"]
        case.save()
        record_snapshot(entity_type="case", entity_id=case.case_uid, version=case.row_version,
                        reason={"record_payment": "payment_recorded", "reverse_payment": "payment_reversed"}.get(action, action),
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
        # Validate and compare the same rounded amount that will be stored.
        amount = money(amount)
        if not js_is_finite(amount) or amount <= 0:
            return _error(400, "invalid_payment", "Payment amount must remain positive after rounding to two decimal places.")
        case = self._load_case_for_update(case_uid)
        if case is None:
            return _error(404, "case_not_found", "Case not found.")
        locked = self._status_error(case, "recorded")
        if locked:
            return locked
        payload = json_roundtrip(case_payload(case))
        item = next((i for i in build_payment_schedule(payload)["items"] if i["scheduleKey"] == schedule_key), None)
        if item is None:
            return _error(400, "schedule_not_found", "The selected installment and party no longer exist.")
        # Alpha 也檢查 item.reviewRequired，但排程項目沒有這個欄位；實際只靠「沒有到期日」擋下
        if not item["dueDate"]:
            return _error(400, "schedule_pending_review", "Confirm the installment payment base date before recording payment.")
        if amount - abs(item["outstanding"]) > 0.004:
            return _error(400, "overpayment", "Payment cannot exceed the selected installment balance.")
        blocked = payment_error(item, amount)
        if blocked:
            return _error(400, "swiss_payment_blocked", blocked)
        actor_info = actor_from(person)
        entry = {
            "id": str(uuid.uuid4()), "entryType": "payment", "scheduleKey": schedule_key,
            "installmentId": item["installmentId"], "installmentLabel": item["installmentLabel"],
            "partyType": item["partyType"], "partyName": item["partyName"],
            "amount": -amount if item["amount"] < 0 else amount, "paymentDate": payment_date,
            "note": js_slice(js_trim(_text(body.get("note"))), 0, 1000),
            "createdAt": _iso_now(), "createdBy": actor_info["id"], "createdByName": actor_info["name"],
        }
        if item.get("swissFacility") and item["amount"] > 0:
            entry["settlementDueDate"] = item["dueDate"]
        if item.get("returnPremium"):
            entry["paymentDirection"] = item["paymentDirection"]
            entry["returnPremium"] = True
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
        payload = json_roundtrip(case_payload(case))
        entries = payload.get("paymentEntries") if is_array(payload.get("paymentEntries")) else []
        original = next((e for e in _objects(entries)
                         if get(e, "id") == entry_id and get(e, "entryType") == "payment"), None)
        if original is None:
            return _error(400, "payment_not_found", "The original payment entry was not found.")
        if original.get("batchId"):
            return _error(400, "batch_reverse_required", "Reverse the entire remittance from Accounting history.")
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
        for field in ("settlementDueDate", "nonCash", "entryKind"):
            if field in original:
                reversal[field] = original[field]
        if original.get("offsetId"):
            return _error(400, "linked_offset_locked", "Offset records must remain linked to both policies; review them with Accounting.")
        payload["paymentEntries"] = json_roundtrip([*entries, reversal])
        return self._save(request, body, case, payload, "reverse_payment", json_roundtrip({
            "paymentEntryId": reversal["id"], "reversalOf": entry_id,
            "scheduleKey": get(original, "scheduleKey"), "amount": get(original, "amount"),
        }))
