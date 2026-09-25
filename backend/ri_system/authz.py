"""
登入者 → Personnel → 角色 → 權限。移植自 Hatchable Alpha 的 lib/authorization.js，
角色權限矩陣、錯誤碼（AUTHENTICATION_REQUIRED / PERSONNEL_NOT_LINKED / PERSONNEL_INACTIVE /
ACCOUNT_INACTIVE / PERMISSION_DENIED）與 principal 輸出格式都與 Alpha 保持一致，
這樣 Alpha 前端的權限判斷邏輯可以直接沿用。

與 Alpha 的差異：Alpha 有「Hatchable 專案協作者」這條特殊路徑（#13），VM 沒有這個概念，
所有人都必須是綁定 Personnel 的 Django 帳號。
"""
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from personnel.models import Personnel

ROLE_LABELS = {
    "admin": "System Administrator",
    "sales": "Reinsurance Staff",
    "accounting": "Finance Staff",
    "accounting_manager": "Finance Manager",
    "general_manager": "General Manager",
    "viewer": "Case Viewer",
}

# 與 Alpha lib/authorization.js 的 ROLE_PERMISSIONS 逐項相同。
# 修改此表前必須先確認 Alpha 端已同步修改（權限矩陣以 Alpha 為準）。
ROLE_PERMISSIONS = {
    "admin": [
        "dashboard.read", "cases.read.all", "cases.write", "cases.announce",
        "documents.read", "documents.write", "mdm.read", "mdm.write",
        "production.read", "fx.read", "fx.write", "personnel.read",
        "personnel.write", "accounts.manage", "targets.read", "targets.write",
        "audit.read", "foundation.read", "accounting.read", "accounting.write",
        "recycle.read", "recycle.write",
    ],
    "sales": [
        "dashboard.read", "cases.read.all", "cases.write", "cases.announce",
        "documents.read", "documents.write", "mdm.read", "mdm.write",
        "production.read", "fx.read",
    ],
    "accounting": [
        "production.read", "fx.read", "accounting.read", "accounting.write",
    ],
    "accounting_manager": [
        "production.read", "fx.read", "fx.write", "accounting.read", "accounting.write",
    ],
    "general_manager": [
        "dashboard.read", "cases.read.all", "documents.read", "mdm.read", "mdm.write",
        "production.read", "fx.read", "personnel.read", "targets.read",
        "targets.write", "audit.read",
    ],
    "viewer": [
        "dashboard.read", "cases.read.own",
    ],
}


class AuthError(APIException):
    def __init__(self, status_code, code, message):
        self.status_code = status_code
        self.code = code
        super().__init__(detail=message, code=code)


def ri_exception_handler(exc, context):
    """AuthError 以 Alpha 的 {error, message} 格式輸出；其餘沿用 DRF 預設。"""
    if isinstance(exc, AuthError):
        return Response({"error": exc.code, "message": str(exc.detail)}, status=exc.status_code)
    return drf_exception_handler(exc, context)


def permissions_for_role(role_code):
    return list(ROLE_PERMISSIONS.get(role_code, []))


def has_permission(person, permission):
    return person is not None and permission in ROLE_PERMISSIONS.get(person.role_code, [])


def actor_from(person):
    """對應 Alpha 的 actorFromPrincipal：寫入 created_by / updated_by / audit 的操作者。"""
    return {"id": f"personnel:{person.pk}", "name": person.name, "role": person.role_code}


def serialize_principal(person):
    return {
        "id": person.pk,
        "name": person.name,
        "email": person.email or "",
        "department": person.department,
        "roleCode": person.role_code,
        "roleLabel": ROLE_LABELS.get(person.role_code, person.role_code),
        "isActive": person.is_active,
        "isSplitEligible": person.is_split_eligible,
        "accountStatus": person.account_status,
        "mustChangePassword": person.must_change_password,  # VM 專有（Alpha 沒有）
        "permissions": permissions_for_role(person.role_code),
    }


def load_principal(request):
    """把已登入的 Django User 轉成 Personnel，並檢查在職與帳號狀態。"""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        raise AuthError(401, "AUTHENTICATION_REQUIRED", "Authentication is required.")
    person = Personnel.objects.filter(auth_user_id=str(user.pk)).first()
    if person is None:
        raise AuthError(403, "PERSONNEL_NOT_LINKED", "This account is not linked to Personnel.")
    if not person.is_active:
        raise AuthError(403, "PERSONNEL_INACTIVE", "Personnel is inactive. Business access is denied.")
    if person.account_status != "active":
        raise AuthError(403, "ACCOUNT_INACTIVE", "The internal account is not active.")
    return person


class RIPermission(BasePermission):
    """
    view 以 permission_map = {"GET": "fx.read", "POST": "fx.write"} 宣告每個 HTTP 方法所需權限。
    沒有宣告的方法一律拒絕（預設拒絕）。通過後 request.ri_principal 為 Personnel。

    必須先改密碼（must_change_password）的人，所有業務 API 一律拒絕（PASSWORD_CHANGE_REQUIRED），
    不管前端有沒有擋。登入、登出、app-context、改密碼不經過這裡，所以仍然可用。
    """

    def has_permission(self, request, view):
        person = load_principal(request)
        if person.must_change_password:
            raise AuthError(403, "PASSWORD_CHANGE_REQUIRED", "You must change your password before using the system.")
        required = getattr(view, "permission_map", {}).get(request.method)
        if required is None or not has_permission(person, required):
            raise AuthError(403, "PERMISSION_DENIED", "You do not have permission for this operation.")
        request.ri_principal = person
        return True


class NoStoreMixin:
    """對應 Alpha 的 Cache-Control: no-store：登入後的業務資料不得被瀏覽器或代理快取。"""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store, max-age=0"
        return response
