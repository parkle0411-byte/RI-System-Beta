"""
Dashboard 與業績目標 API - 對應 Hatchable Alpha 的 api/dashboard.js 與 api/dashboard-targets.js。

  GET  /api/dashboard           dashboard.read   即時儀表板（cases.read.all 看全部；否則只看自己負責或參與分績的案件）
  GET  /api/dashboard-targets   targets.read     目標列表
  POST /api/dashboard-targets   targets.write    新增目標（年度或月份，同一期間只能一筆）
  PUT  /api/dashboard-targets   targets.write    修改金額、停用／重新啟用（期間不能改）

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - Dashboard 的「今天／本月／今年」與 Announce 月用台北時間（Alpha 是 UTC）。
  - 每月佣金趨勢與再保人占比用 Production Report 的規則（calc.py 的 production_rules）。
  - 目標 API 的 scope.dashboardConsumption 與 Audit metadata 的 dashboardConsumption 是 true（Dashboard 確實會用目標；Alpha 寫 false）。
  - 新增目標時若同時有人新增同一期間：409 duplicate_target（Alpha 會是未處理的資料庫錯誤）。
"""
import re
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from cases.calc.jsnum import (
    UNDEFINED, get, is_array, is_nullish, js_is_finite, js_is_integer, js_num_str, js_slice, js_to_number, js_to_string,
    js_trim, json_roundtrip, money,
)
from cases.models import Case
from fxrates.models import FxRate
from ri_system.authz import NoStoreMixin, RIPermission, actor_from, has_permission

from .calc import build_dashboard
from .models import DashboardTarget

TAIPEI = ZoneInfo("Asia/Taipei")
DISPLAY_VERSION = "V 0.003"
AUDIT_METADATA = {"displayVersion": DISPLAY_VERSION, "milestone": "personnel-accounts", "dashboardConsumption": True}
_YEAR = re.compile(r"[0-9]{4}\Z")
_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])\Z")


def _now():
    """目前時間（測試用 mock 替換這個函式，不影響 Django 其他地方的 timezone.now）。"""
    return timezone.now()


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


def _taipei_text(value):
    return value.astimezone(TAIPEI).isoformat() if value else None


def _pg_text(value):
    """PostgreSQL 的 party->>'personnelId'：JSON 值轉成文字（null 沒有值）。"""
    if value is None or value is UNDEFINED:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return js_to_string(value)


def _visible(case, person):
    if case.owner_personnel_id == person.pk:
        return True
    parties = case.payload.get("splitParties") if isinstance(case.payload, dict) else None
    return is_array(parties) and any(_pg_text(get(p, "personnelId")) == str(person.pk) for p in parties)


class DashboardView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "dashboard.read"}

    def get(self, request):
        person = request.ri_principal
        see_all = has_permission(person, "cases.read.all")
        cases = Case.objects.filter(recycled_at__isnull=True, is_archived=False).order_by("id")
        rows = [{"id": c.pk, "parent_case_id": c.parent_case_id, "status": c.status, "payload": c.payload,
                 "announced_at": _taipei_text(c.announced_at), "created_at": _taipei_text(c.created_at)}
                for c in cases if see_all or _visible(c, person)]
        targets = [{"period_type": t.period_type, "period_key": t.period_key, "amount": float(t.amount)}
                   for t in DashboardTarget.objects.filter(is_active=True).order_by("period_key", "id")]
        fx = [{"year_month": f.year_month, "currency": f.currency, "rate": float(f.rate)}
              for f in FxRate.objects.order_by("year_month", "id")]
        return Response(json_roundtrip(build_dashboard(rows, targets, fx, _now(), tz=TAIPEI, production_rules=True)))


# ------------------------------------------------------------------ 業績目標

def clean_text(value, max_len):
    """String(value ?? '').trim().slice(0, max)"""
    return js_slice(js_trim("" if is_nullish(value) else js_to_string(value)), 0, max_len)


def parse_input(body):
    period_type = clean_text(body.get("periodType", UNDEFINED), 20)
    period_key = clean_text(body.get("periodKey", UNDEFINED), 7)
    amount = js_to_number(body.get("amount", UNDEFINED))
    if period_type == "annual":
        valid_key = bool(_YEAR.match(period_key))
    else:
        valid_key = period_type == "monthly" and bool(_MONTH.match(period_key))
    if not valid_key:
        return {"error": "invalid_period", "message": "Select a valid annual year or monthly period."}
    if not js_is_finite(amount) or amount < 0 or amount > 9999999999999999:
        return {"error": "invalid_amount", "message": "Target must be a non-negative amount."}
    return {"periodType": period_type, "periodKey": period_key, "amount": money(amount), "isActive": body.get("isActive") is not False}


def serialize(t):
    return {"id": t.pk, "periodType": t.period_type, "periodKey": t.period_key, "amount": float(t.amount),
            "isActive": t.is_active, "rowVersion": t.row_version,
            "updatedAt": t.updated_at.astimezone(dt_timezone.utc).isoformat() if t.updated_at else None}


def _state(t):
    """Alpha 的 jsonb_build_object('id', 'periodType', 'periodKey', 'amount', 'isActive', 'rowVersion')"""
    return {"id": t.pk, "periodType": t.period_type, "periodKey": t.period_key, "amount": float(t.amount),
            "isActive": t.is_active, "rowVersion": t.row_version}


class DashboardTargetsView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "targets.read", "POST": "targets.write", "PUT": "targets.write"}

    def get(self, request):
        targets = DashboardTarget.objects.order_by("-period_key", "period_type", "-id")
        return Response({"ok": True, "displayVersion": DISPLAY_VERSION, "targets": [serialize(t) for t in targets],
                         "scope": {"dashboardConsumption": True}})

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        data = parse_input(body)
        if "error" in data:
            return Response(data, status=400)
        duplicate = _error(409, "duplicate_target", "This target period already exists. Edit the retained record instead.")
        if DashboardTarget.objects.filter(period_type=data["periodType"], period_key=data["periodKey"]).exists():
            return duplicate
        actor_info = actor_from(request.ri_principal)
        try:
            with transaction.atomic():
                target = DashboardTarget.objects.create(
                    period_type=data["periodType"], period_key=data["periodKey"], amount=data["amount"], is_active=data["isActive"],
                    created_by=actor_info["id"], updated_by=actor_info["id"],
                    deactivated_by=None if data["isActive"] else actor_info["id"],
                    deactivated_at=None if data["isActive"] else timezone.now(),
                )
                target.refresh_from_db()
                record_snapshot(entity_type="dashboard_target", entity_id=target.pk, version=target.row_version,
                                reason="dashboard_target_created", data=_state(target), created_by=actor_info["id"])
                record_audit(entity_type="dashboard_target", entity_id=target.pk, action="create_dashboard_target",
                             before=None, after=_state(target), actor=actor_info, request_id=request_id_from(request),
                             metadata=AUDIT_METADATA)
        except IntegrityError:
            return duplicate
        return Response({"ok": True, "displayVersion": DISPLAY_VERSION, "target": serialize(target)}, status=201)

    def put(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        target_id = js_to_number(body.get("id", UNDEFINED))
        expected = js_to_number(body.get("rowVersion", UNDEFINED))
        if not js_is_integer(target_id) or target_id < 1 or not js_is_integer(expected) or expected < 1:
            return _error(400, "version_required", "A valid target id and rowVersion are required.")
        data = parse_input(body)
        if "error" in data:
            return Response(data, status=400)
        actor_info = actor_from(request.ri_principal)
        conflict = _error(409, "version_conflict", "This target changed elsewhere. Reload before saving.")
        with transaction.atomic():
            current = DashboardTarget.objects.select_for_update().filter(pk=int(target_id)).first()
            if current is None:
                return _error(404, "target_not_found", "Dashboard target was not found.")
            if current.row_version != expected:
                return _error(409, "version_conflict", "This target changed elsewhere. Reload before saving.",
                              currentRowVersion=current.row_version)
            if current.period_type != data["periodType"] or current.period_key != data["periodKey"]:
                return _error(400, "period_immutable", "Target type and period cannot be changed. Add another retained period instead.")
            before = serialize(current)
            if current.is_active != data["isActive"]:
                action = "reactivate_dashboard_target" if data["isActive"] else "deactivate_dashboard_target"
            else:
                action = "update_dashboard_target"
            reason = "dashboard_target_updated" if action == "update_dashboard_target" else action
            current.amount = data["amount"]
            current.is_active = data["isActive"]
            current.row_version += 1
            current.updated_by = actor_info["id"]
            current.deactivated_by = None if data["isActive"] else actor_info["id"]
            current.deactivated_at = None if data["isActive"] else timezone.now()
            current.save()
            current.refresh_from_db()
            record_snapshot(entity_type="dashboard_target", entity_id=current.pk, version=current.row_version,
                            reason=reason, data=_state(current), created_by=actor_info["id"])
            record_audit(entity_type="dashboard_target", entity_id=current.pk, action=action, before=before,
                         after=_state(current), actor=actor_info, request_id=request_id_from(request), metadata=AUDIT_METADATA)
        return Response({"ok": True, "displayVersion": DISPLAY_VERSION, "target": serialize(current)})
