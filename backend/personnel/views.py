"""
Personnel API - 對應 Hatchable Alpha 的 api/personnel.js 與 api/personnel-options.js（含 #14、#15）。

  GET  /api/personnel          personnel.read   列表 + counts + scope
  POST /api/personnel          personnel.write  新增
  PUT  /api/personnel          personnel.write  編輯 / 停用 / 重新啟用（含 optimistic lock）
  GET  /api/personnel-options  cases.write      啟用中人員（案件負責人、業績拆分的下拉選單）

Alpha #15：「在職(is_active)」與「登入帳號啟用(account_status)」是兩個獨立概念，
在職狀態不受帳號狀態限制；帳號生命週期有自己的規則（見 accounts.py 與 account_views.py）。
"""
import re

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from, has_permission

from .accounts import active_admin_count
from .audit_state import personnel_state
from .models import Personnel

DEPARTMENTS = {
    "business_1", "business_2", "special_risk", "reinsurance",
    "finance", "admin", "business_development",
}
ROLES = {"sales", "accounting", "accounting_manager", "general_manager", "admin", "viewer"}
DEFAULT_ROLES = {
    "business_1": "viewer", "business_2": "viewer", "special_risk": "viewer",
    "business_development": "viewer", "reinsurance": "sales",
    "finance": "accounting", "admin": "admin",
}
AUDIT_METADATA = {"displayVersion": "V 0.003", "milestone": "personnel-management"}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def clean_text(value, max_len):
    return str(value if value is not None else "").strip()[:max_len]


def valid_email(value):
    return not value or (len(value) <= 254 and EMAIL_RE.match(value) is not None)


def default_split_eligibility(department, role_code):
    return department not in ("finance", "admin") and not (department == "reinsurance" and role_code == "general_manager")


def parse_input(body):
    name = clean_text(body.get("name"), 160)
    email = clean_text(body.get("email"), 320).lower()
    department = clean_text(body.get("department"), 40)
    role_code = clean_text(body.get("roleCode") or DEFAULT_ROLES.get(department), 40)
    supervisor_name = clean_text(body.get("supervisorName"), 160)
    if not name:
        return {"error": "name_required", "message": "Personnel name is required."}
    if department not in DEPARTMENTS:
        return {"error": "invalid_department", "message": "Select an approved department."}
    if role_code not in ROLES:
        return {"error": "invalid_role", "message": "Select an approved role."}
    if not valid_email(email):
        return {"error": "invalid_email", "message": "Enter a valid Email address."}
    return {
        "name": name,
        "email": email or None,
        "department": department,
        "role_code": role_code,
        "supervisor_name": supervisor_name or None,
        "supervisor_email": None,
        "is_active": body.get("isActive") is not False,
        "is_split_eligible": (body.get("isSplitEligible") is True) if "isSplitEligible" in body
        else default_split_eligibility(department, role_code),
    }


def resolve_supervisor(inp, excluded_id=0):
    """
    主管必須是「同部門的在職人員」或「在職的 General Manager」，且不能是自己。
    Alpha #14：資料庫裡本來就有同名跨部門的人（例如兩位 A.L），沒有排序時取哪一位不確定。
    這裡固定「同部門優先，再依 id」，結果永遠可重現。
    """
    if not inp["supervisor_name"]:
        inp["supervisor_name"] = None
        inp["supervisor_email"] = None
        return None
    candidates = list(
        Personnel.objects.filter(name__iexact=inp["supervisor_name"], is_active=True)
        .filter(Q(department=inp["department"]) | Q(role_code="general_manager"))
        .exclude(pk=excluded_id)
    )
    candidates.sort(key=lambda p: (p.department != inp["department"], p.pk))
    if not candidates:
        return {
            "error": "invalid_supervisor",
            "message": "Select an active Supervisor in the same Department or a General Manager. Self-selection is not allowed.",
        }
    inp["supervisor_name"] = candidates[0].name
    inp["supervisor_email"] = candidates[0].email or None
    return None


def duplicate_check(inp, excluded_id=0):
    qs = Personnel.objects.exclude(pk=excluded_id)
    if qs.filter(name__iexact=inp["name"], department=inp["department"]).exists():
        return "name"
    if inp["email"] and qs.filter(email__iexact=inp["email"]).exists():
        return "email"
    return None


def duplicate_response(field):
    return Response({"error": f"duplicate_{field}", "message": f"This personnel {field} already exists."}, status=409)


def unique_violation_response(exc):
    """資料庫唯一約束是最終防線（同 Master Data 的 #18 作法）。"""
    message = str(exc)
    if "ri_personnel_name_department_unique" in message:
        return duplicate_response("name")
    if "ri_personnel_email_unique" in message:
        return duplicate_response("email")
    return None


def usernames_for(people):
    ids = [int(p.auth_user_id) for p in people if p.auth_user_id]
    if not ids:
        return {}
    return {str(u.pk): u.username for u in get_user_model().objects.filter(pk__in=ids)}


def serialize(person, usernames=None):
    data = {
        "id": person.pk,
        "name": person.name,
        "email": person.email or "",
        "department": person.department,
        "roleCode": person.role_code,
        "isActive": person.is_active,
        "isSplitEligible": person.is_split_eligible,
        "accountStatus": person.account_status,
        "accountBound": bool(person.auth_user_id),
        "accountInvitedAt": person.account_invited_at,
        "accountActivatedAt": person.account_activated_at,
        "accountDisabledAt": person.account_disabled_at,
        "supervisorName": person.supervisor_name or "",
        "supervisorEmail": person.supervisor_email or "",
        "rowVersion": person.row_version,
        "updatedAt": person.updated_at,
    }
    if usernames is not None:  # 只有 accounts.manage 看得到登入帳號名稱（VM 專有欄位）
        data["accountUsername"] = usernames.get(person.auth_user_id or "", "")
        data["accountMustChangePassword"] = person.must_change_password
    return data


class PersonnelView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "personnel.read", "POST": "personnel.write", "PUT": "personnel.write"}

    def get(self, request):
        people = list(Personnel.objects.order_by("-is_active", "name", "id"))
        names = usernames_for(people) if has_permission(request.ri_principal, "accounts.manage") else None
        rows = [serialize(p, names) for p in people]
        return Response({
            "ok": True,
            "displayVersion": "V 0.003",
            "personnel": rows,
            "counts": {
                "total": len(rows),
                "active": sum(1 for r in rows if r["isActive"]),
                "splitEligible": sum(1 for r in rows if r["isActive"] and r["isSplitEligible"]),
                "accountsActive": sum(1 for r in rows if r["accountStatus"] == "active"),
            },
            # Alpha 這裡寫 authentication: company_vm_deferred；VM 已啟用登入，如實回報
            "scope": {
                "authentication": "django_session",
                "credentialsEnabled": True,
                "rolesEnforced": True,
                "passwordStorage": "django_pbkdf2",
                "accountLifecycleSeparateFromPersonnel": True,
            },
        })

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        inp = parse_input(body)
        if "error" in inp:
            return Response(inp, status=400)
        supervisor_error = resolve_supervisor(inp)
        if supervisor_error:
            return Response(supervisor_error, status=400)
        field = duplicate_check(inp)
        if field:
            return duplicate_response(field)

        actor_info = actor_from(request.ri_principal)
        actor = actor_info["id"]
        try:
            with transaction.atomic():
                person = Personnel.objects.create(
                    name=inp["name"], email=inp["email"], department=inp["department"],
                    role_code=inp["role_code"], is_active=inp["is_active"],
                    is_split_eligible=inp["is_split_eligible"], account_status="not_configured",
                    supervisor_name=inp["supervisor_name"], supervisor_email=inp["supervisor_email"],
                    created_by=actor, updated_by=actor,
                    deactivated_by=None if inp["is_active"] else actor,
                    deactivated_at=None if inp["is_active"] else timezone.now(),
                )
                after = personnel_state(person)
                record_snapshot(entity_type="personnel", entity_id=person.pk, version=person.row_version,
                                reason="personnel_created", data=after, created_by=actor)
                record_audit(entity_type="personnel", entity_id=person.pk, action="create_personnel",
                             before=None, after=after, actor=actor_info,
                             request_id=request_id_from(request), metadata=AUDIT_METADATA)
        except IntegrityError as exc:
            response = unique_violation_response(exc)
            if response is None:
                raise
            return response
        return Response({"ok": True, "displayVersion": "V 0.003", "person": serialize(person)}, status=201)

    def put(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        try:
            person_id = int(body.get("id"))
            expected_version = int(body.get("rowVersion"))
        except (TypeError, ValueError):
            person_id = expected_version = 0
        if person_id < 1 or expected_version < 1:
            return Response(
                {"error": "version_required", "message": "A valid personnel id and rowVersion are required."}, status=400
            )
        inp = parse_input(body)
        if "error" in inp:
            return Response(inp, status=400)
        supervisor_error = resolve_supervisor(inp, person_id)
        if supervisor_error:
            return Response(supervisor_error, status=400)

        actor_info = actor_from(request.ri_principal)
        actor = actor_info["id"]
        try:
            with transaction.atomic():
                try:
                    current = Personnel.objects.select_for_update().get(pk=person_id)
                except Personnel.DoesNotExist:
                    return Response({"error": "personnel_not_found", "message": "Personnel record was not found."}, status=404)
                if current.row_version != expected_version:
                    return Response(
                        {"error": "version_conflict",
                         "message": "This personnel record changed elsewhere. Reload before saving.",
                         "currentRowVersion": current.row_version},
                        status=409,
                    )
                field = duplicate_check(inp, person_id)
                if field:
                    return duplicate_response(field)

                email_changed = (current.email or "").lower() != (inp["email"] or "").lower()
                if email_changed and current.account_status in ("pending", "active"):
                    return Response(
                        {"error": "disable_account_before_email_change",
                         "message": "Disable the account before changing a bound or invited Personnel Email."},
                        status=409,
                    )
                if (current.role_code == "admin" and current.is_active and current.account_status == "active"
                        and (inp["role_code"] != "admin" or not inp["is_active"]) and active_admin_count() <= 1):
                    return Response(
                        {"error": "last_active_admin", "message": "The system must retain at least one active Admin."},
                        status=409,
                    )
                reset_disabled_account = email_changed and current.account_status == "disabled"

                before = personnel_state(current)
                was_active = current.is_active
                current.name = inp["name"]
                current.email = inp["email"]
                current.department = inp["department"]
                current.role_code = inp["role_code"]
                current.is_active = inp["is_active"]
                current.is_split_eligible = inp["is_split_eligible"]
                current.supervisor_name = inp["supervisor_name"]
                current.supervisor_email = inp["supervisor_email"]
                if reset_disabled_account:
                    # 停用中的帳號換了 Email：解除綁定，之後可為新 Email 重新建立帳號
                    # （舊的 Django 帳號保持停用；ri_runtime 沒有 DELETE 權限，也不該刪）
                    current.account_status = "not_configured"
                    current.auth_user_id = None
                    current.account_invited_by = current.account_invited_at = None
                    current.account_activated_at = None
                    current.account_disabled_by = current.account_disabled_at = None
                current.row_version += 1
                current.updated_by = actor
                if current.is_active:
                    current.deactivated_by = None
                    current.deactivated_at = None
                elif was_active:  # 只有「在職 → 停用」那一刻才記錄停用者與時間，之後的編輯不覆寫
                    current.deactivated_by = actor
                    current.deactivated_at = timezone.now()
                current.save()

                if was_active == current.is_active:
                    action, reason = "update_personnel", "personnel_updated"
                elif current.is_active:
                    action, reason = "reactivate_personnel", "reactivate_personnel"
                else:
                    action, reason = "deactivate_personnel", "deactivate_personnel"
                after = personnel_state(current)
                record_snapshot(entity_type="personnel", entity_id=current.pk, version=current.row_version,
                                reason=reason, data=after, created_by=actor)
                record_audit(entity_type="personnel", entity_id=current.pk, action=action,
                             before=before, after=after, actor=actor_info,
                             request_id=request_id_from(request),
                             metadata={**AUDIT_METADATA, "accountResetForEmailChange": reset_disabled_account})
        except IntegrityError as exc:
            response = unique_violation_response(exc)
            if response is None:
                raise
            return response
        return Response({"ok": True, "displayVersion": "V 0.003", "person": serialize(current)})


class PersonnelOptionsView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "cases.write"}

    def get(self, request):
        rows = list(Personnel.objects.filter(is_active=True).order_by("name", "id"))
        me = request.ri_principal
        default_owner = next((p for p in rows if p.pk == me.pk), None)
        return Response({
            "ok": True,
            "defaultOwnerId": default_owner.pk if default_owner else None,
            "personnel": [
                {"id": p.pk, "name": p.name, "isActive": True, "isSplitEligible": p.is_split_eligible}
                for p in rows
            ],
        })
