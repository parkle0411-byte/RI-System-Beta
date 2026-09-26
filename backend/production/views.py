"""
Production Report API - 對應 Hatchable Alpha 的 api/production-report.js。

  GET  /api/production-report?month=YYYY-MM   production.read   預覽（未確認的業績列）、已產生的版本、摘要、權限
  POST /api/production-report                 production.read   action = exclude | generate | close
       exclude／generate：System Administrator、Finance Staff、Finance Manager（依 role_code，同 Alpha）
       close：System Administrator、Finance Manager

關帳（close）：報表裡的案件把這些 key 記成已確認；全部確認的案件變成 Confirmed（closed）並產生 Leg 1–3 交易
（有待沖銷時先加 -RVS 沖銷分錄，見 closing.py）；該月匯率全部鎖定。

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - 業績月份用台北時間：Announce／建立時間先換成台北時間的文字再交給 calc（Alpha 是 UTC，月初 8 小時內算上個月）。
  - 排除、產生版本也寫 Audit（Alpha 只有關帳寫 Audit）；關帳時每個案件與每個被鎖定的匯率都補寫 Snapshot，匯率鎖定也寫 Audit。
  - 關帳：先鎖報表與案件列，再檢查版本與狀態（Alpha 是事後以「除以零」檢查）；結果相同（有變動就 409 close_conflict，什麼都不寫）。
  - 關帳時案件的 transactions 裡有 null：409 transactions_corrupt（Alpha 會拋錯；同 Reverse 的決定）。
  - 案件的排序：Announce 時間為空的排最後（同 PostgreSQL 的 ORDER BY 預設；MySQL 預設排最前）。
"""
import re
import uuid
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from cases.calc.jsnum import UNDEFINED, get, is_array, js_or, js_slice, js_to_number, js_to_string, js_trim, json_roundtrip
from cases.models import Case
from fxrates.models import FxRate
from fxrates.views import fx_state
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from . import calc
from .closing import TransactionsCorrupt, confirm_case
from .models import ProductionExclusion, ProductionReport

TAIPEI = ZoneInfo("Asia/Taipei")
_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\Z")
DISPLAY_VERSION = "V 0.003"


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


def _taipei_text(value):
    """時間換成台北時間的 ISO 文字（calc 取前 7 個字當月份）。"""
    return value.astimezone(TAIPEI).isoformat() if value else None


def _utc_text(value):
    """Alpha（Hatchable）回傳的時間格式：2026-09-26T04:59:04.281784+00:00"""
    return value.astimezone(dt_timezone.utc).isoformat() if value else None


def can_operate(person):
    return person.role_code in ("admin", "accounting", "accounting_manager")


def can_close(person):
    return person.role_code in ("admin", "accounting_manager")


def case_source(case):
    return {
        "id": case.pk, "case_uid": str(case.case_uid), "parent_case_id": case.parent_case_id, "tw_ref": case.tw_ref,
        "status": case.status, "row_version": case.row_version, "payload": case.payload,
        "announced_at": _taipei_text(case.announced_at), "created_at": _taipei_text(case.created_at),
    }


def exclusion_row(e):
    return {
        "id": str(e.id), "case_id": e.case_id, "year_month": e.year_month, "scope": e.scope,
        "installment_key": e.installment_key, "reinsurer_key": e.reinsurer_key, "deferred_to": e.deferred_to,
        "reason": e.reason, "created_by": e.created_by, "created_at": _utc_text(e.created_at),
    }


def report_view(report, include_rows=True):
    view = {
        "reportUid": str(report.report_uid), "month": report.year_month, "version": report.version, "status": report.status,
        "sourceSignature": report.source_signature, "rowVersion": report.row_version,
        "createdBy": report.created_by, "createdAt": _utc_text(report.created_at),
        "closedBy": report.closed_by, "closedAt": _utc_text(report.closed_at),
    }
    if include_rows:
        view["rows"] = report.rows if is_array(report.rows) else []
        view["excluded"] = report.excluded_rows if is_array(report.excluded_rows) else []
    return view


def _live_cases():
    return Case.objects.filter(recycled_at__isnull=True, is_archived=False, status__in=("posted", "closed", "reversed"))


def load_month(month):
    cases = list(_live_cases().order_by(F("announced_at").asc(nulls_last=True), F("created_at").asc(nulls_last=True), "id"))
    fx_rows = list(FxRate.objects.filter(year_month=month).order_by("currency"))
    exclusions = list(ProductionExclusion.objects.filter(year_month=month) | ProductionExclusion.objects.filter(deferred_to=month))
    exclusions.sort(key=lambda e: (e.created_at, str(e.id)))
    reports = list(ProductionReport.objects.filter(year_month=month).order_by("-version"))
    fx_rates = {month: {r.currency: float(r.rate) for r in fx_rows}}
    sources = [case_source(c) for c in cases]
    preview = calc.build_production_preview(sources, month, fx_rates, [exclusion_row(e) for e in exclusions])
    return {"cases": cases, "sources": sources, "fx_rows": fx_rows, "reports": reports, "preview": preview}


def summary(preview):
    premium = income = 0.0
    for row in preview["rows"]:
        premium += js_to_number(js_or(row["premium"], 0))
    for row in preview["rows"]:
        income += js_to_number(js_or(row["income"], 0))
    return {"rowCount": len(preview["rows"]), "excludedRowCount": len(preview["excluded"]),
            "premiumNtd": premium, "incomeNtd": income, "missingRateCurrencies": preview["missingRateCurrencies"]}


def _text(value):
    return js_to_string(js_or(value, ""))


class ProductionReportView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "production.read", "POST": "production.read"}

    @staticmethod
    def _month(value):
        month = js_trim(js_to_string(value))
        return month if _MONTH.match(month) else None

    def get(self, request):
        month = self._month(request.query_params.get("month"))
        if month is None:
            return _error(400, "invalid_month", "Report month must use YYYY-MM.")
        person = request.ri_principal
        state = load_month(month)
        latest = state["reports"][0] if state["reports"] else None
        closed = any(r.status == "closed" for r in state["reports"])
        preview = state["preview"]
        return Response(json_roundtrip({
            "ok": True, "displayVersion": DISPLAY_VERSION, "month": month, "headers": calc.PRODUCTION_REPORT_HEADERS,
            "rows": preview["rows"], "excluded": preview["excluded"], "sourceSignature": preview["sourceSignature"],
            "versions": [report_view(r) for r in state["reports"]],
            "summary": summary(preview),
            "scope": {
                "readOnly": False, "canOperate": can_operate(person), "canClose": can_close(person), "monthClosed": closed,
                "fxLocked": any(r.is_locked for r in state["fx_rows"]),
                "canGenerate": can_operate(person) and not closed and not preview["missingRateCurrencies"],
                "canCloseLatest": can_close(person) and latest is not None and latest.status == "valid"
                and latest.source_signature == preview["sourceSignature"],
            },
        }))

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        month = self._month(js_or(body.get("month"), ""))
        if month is None:
            return _error(400, "invalid_month", "Report month must use YYYY-MM.")
        action = _text(body.get("action"))
        handlers = {"exclude": self.exclude, "generate": self.generate, "close": self.close}
        if action not in handlers:
            return _error(400, "unsupported_action", "Unsupported Production Report action.")
        return handlers[action](request, body, month, load_month(month))

    # ---- 排除（延到下個月） ----
    def exclude(self, request, body, month, state):
        person = request.ri_principal
        if not can_operate(person):
            return _error(403, "permission_denied", "Accounting access is required to exclude Production rows.")
        if any(r.status == "closed" for r in state["reports"]):
            return _error(409, "month_closed", "This Production month is closed.")
        scope = _text(body.get("scope"))
        if scope not in ("case", "reinsurer"):
            return _error(400, "invalid_scope", "Exclusion scope must be case or reinsurer.")
        reason = js_slice(js_trim(_text(body.get("reason"))), 0, 2000)
        if not reason:
            return _error(400, "reason_required", "Exclusion reason is required.")
        row_id = _text(body.get("rowId"))
        row = next((r for r in state["preview"]["rows"] if r["id"] == row_id), None)
        if row is None:
            return _error(409, "row_not_available", "This row is no longer available. Refresh the preview.")
        actor_info = actor_from(person)
        try:
            with transaction.atomic():
                exclusion = ProductionExclusion.objects.create(
                    case_id=int(row["caseId"]), year_month=month, scope=scope, installment_key=row["key"],
                    reinsurer_key=row["reinsurerKey"] if scope == "reinsurer" else None,
                    deferred_to=calc.next_production_month(month), reason=reason, created_by=actor_info["name"],
                )
                data = exclusion_row(exclusion)
                # VM 補上：排除會改變業績歸屬月份，寫 Audit（Alpha 沒有）
                record_audit(entity_type="production_exclusion", entity_id=exclusion.id, action="exclude_production_row",
                             before=None, after=data, actor=actor_info, request_id=request_id_from(request),
                             metadata={"month": month, "rowId": row_id, "caseUid": row["caseUid"]})
        except IntegrityError:
            return _error(409, "already_excluded", "This Production item is already excluded for the selected month.")
        return Response({"ok": True, "exclusion": data}, status=201)

    # ---- 產生版本 ----
    def generate(self, request, body, month, state):
        person = request.ri_principal
        if not can_operate(person):
            return _error(403, "permission_denied", "Accounting access is required to generate Production Reports.")
        if any(r.status == "closed" for r in state["reports"]):
            return _error(409, "month_closed", "This Production month is closed and cannot be regenerated.")
        preview = state["preview"]
        if preview["missingRateCurrencies"]:
            return _error(400, "fx_rate_required", f"Set the official {month} exchange rate before generating Excel.",
                          currencies=preview["missingRateCurrencies"])
        if _text(body.get("sourceSignature")) != preview["sourceSignature"]:
            return _error(409, "source_changed", "Production source data changed. Refresh the preview before generating.")
        latest = state["reports"][0] if state["reports"] else None
        version = latest.version + 1 if latest else 1
        actor_info = actor_from(person)
        try:
            with transaction.atomic():
                invalidated = list(ProductionReport.objects.select_for_update().filter(year_month=month, status="valid"))
                ProductionReport.objects.filter(pk__in=[r.pk for r in invalidated]).update(status="invalid", row_version=F("row_version") + 1)
                report = ProductionReport.objects.create(
                    year_month=month, version=version, status="valid", rows=json_roundtrip(preview["rows"]),
                    excluded_rows=json_roundtrip(preview["excluded"]), source_signature=preview["sourceSignature"],
                    created_by=actor_info["name"],
                )
                # VM 補上：產生版本寫 Audit（Alpha 沒有）
                record_audit(entity_type="production_report", entity_id=report.report_uid, action="generate_production_report",
                             before={"invalidatedReportUids": [str(r.report_uid) for r in invalidated]},
                             after={"reportUid": str(report.report_uid), "month": month, "version": version,
                                    "sourceSignature": report.source_signature, "rowCount": len(preview["rows"]),
                                    "excludedRowCount": len(preview["excluded"])},
                             actor=actor_info, request_id=request_id_from(request), metadata={"month": month})
        except IntegrityError:
            return _error(409, "version_conflict", "Another Production Report version was created. Refresh and try again.")
        return Response(json_roundtrip({"ok": True, "report": report_view(report)}), status=201)

    # ---- 關帳 ----
    def close(self, request, body, month, state):
        person = request.ri_principal
        if not can_close(person):
            return _error(403, "permission_denied", "Only Finance Manager or System Administrator can close a Production month.")
        report_uid = _text(body.get("reportUid"))
        expected = js_to_number(body.get("rowVersion", UNDEFINED))  # Number(undefined) 是 NaN
        report = next((r for r in state["reports"] if str(r.report_uid) == report_uid), None)
        latest = state["reports"][0] if state["reports"] else None
        if report is None:
            return _error(404, "report_not_found", "Production Report version was not found.")
        if report.status != "valid" or report is not latest:
            return _error(409, "latest_valid_required", "Only the latest valid Production Report version can close the month.")
        if report.row_version != expected:
            return _error(409, "version_conflict", "This Production Report changed. Refresh before closing.")
        signature = state["preview"]["sourceSignature"]
        if report.source_signature != signature or _text(body.get("sourceSignature")) != signature:
            return _error(409, "source_changed", "Production source data changed. Generate a new version before closing.")

        rows_by_case = {}
        for row in (report.rows if is_array(report.rows) else []):
            rows_by_case.setdefault(js_to_number(get(row, "caseId")), []).append(row)
        sources = {float(s["id"]): s for s in state["sources"]}
        cases = {float(c.pk): c for c in state["cases"]}
        plans = []
        for case_id, report_rows in rows_by_case.items():
            source = sources.get(case_id)
            if source is None:
                return _error(409, "case_changed", "A case in this report is no longer available.")
            try:
                result = confirm_case(source, report_rows)
            except TransactionsCorrupt:
                return _error(409, "transactions_corrupt",
                              "The transaction records of a case in this report are damaged (an empty entry was found). Contact the system administrator.")
            plans.append((cases[case_id], source, result))

        actor_info = actor_from(person)
        close_token = uuid.uuid4()
        closed_cases = sum(p[2]["closedCases"] for p in plans)
        conflict = _error(409, "close_conflict", "The report, a case, or the FX rate changed while closing. Nothing was closed; refresh and try again.")
        try:
            with transaction.atomic():
                locked_report = ProductionReport.objects.select_for_update().filter(pk=report.pk).first()
                if (locked_report is None or locked_report.row_version != expected or locked_report.status != "valid"
                        or locked_report.year_month != month):
                    raise _Conflict()
                now = timezone.now()
                locked_report.status = "closed"
                locked_report.row_version += 1
                locked_report.close_token = close_token
                locked_report.closed_by = actor_info["name"]
                locked_report.closed_at = now
                locked_report.save()
                request_id = request_id_from(request)
                for case, source, result in plans:
                    locked = Case.objects.select_for_update().filter(
                        pk=case.pk, row_version=source["row_version"], status__in=("posted", "reversed"),
                        recycled_at__isnull=True, is_archived=False).first()
                    if locked is None:
                        raise _Conflict()
                    locked.payload = result["payload"]
                    locked.status = result["nextStatus"]
                    locked.row_version += 1
                    locked.updated_by = actor_info["id"]
                    locked.save()
                    after = {"status": locked.status, "rowVersion": locked.row_version, "payload": result["payload"]}
                    record_snapshot(entity_type="case", entity_id=locked.case_uid, version=locked.row_version,
                                    reason="production_case_confirmed",
                                    data={"caseUid": str(locked.case_uid), "twRef": locked.tw_ref, **after}, created_by=actor_info["id"])
                    record_audit(entity_type="case", entity_id=locked.case_uid, action="production_case_confirmed",
                                 before={"status": source["status"], "rowVersion": source["row_version"], "payload": js_or(source["payload"], {})},
                                 after=after, actor=actor_info, request_id=request_id,
                                 metadata={"reportUid": report_uid, "month": month, "productionClosed": not result["remaining"]})
                for fx in FxRate.objects.select_for_update().filter(year_month=month, is_locked=False):
                    before = fx_state(fx)
                    fx.is_locked = True
                    fx.locked_by = actor_info["id"]
                    fx.locked_at = now
                    fx.lock_reason = f"Production Report {month} closed"
                    fx.updated_by = actor_info["id"]
                    fx.row_version += 1
                    fx.save()
                    # VM 補上：匯率鎖定也是修改，寫 Snapshot 與 Audit（Alpha 只在報表的 Audit 裡）
                    record_snapshot(entity_type="fx_rate", entity_id=fx.id, version=fx.row_version, reason="fx_rate_locked",
                                    data=fx_state(fx), created_by=actor_info["id"])
                    record_audit(entity_type="fx_rate", entity_id=fx.id, action="lock_fx_rate", before=before, after=fx_state(fx),
                                 actor=actor_info, request_id=request_id, metadata={"reportUid": report_uid, "month": month})
                record_audit(entity_type="production_report", entity_id=report_uid, action="close_production_report",
                             before=json_roundtrip(report_view(report)),
                             after={"reportUid": report_uid, "month": month, "status": "closed", "rowVersion": expected + 1,
                                    "sourceSignature": signature, "confirmedCases": closed_cases},
                             actor=actor_info, request_id=request_id,
                             metadata={"closeToken": str(close_token), "includedRows": len(report.rows) if is_array(report.rows) else 0})
        except (_Conflict, IntegrityError):
            return conflict
        return Response({"ok": True, "reportUid": report_uid, "month": month, "status": "closed", "confirmedCases": closed_cases})


class _Conflict(Exception):
    pass

