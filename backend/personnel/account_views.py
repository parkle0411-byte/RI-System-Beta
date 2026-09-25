"""
帳號管理 API（VM 專有；Alpha 沒有，因為 Alpha 的登入由 Hatchable 代管）。全部需要 accounts.manage（System Administrator）。

  POST /api/personnel-accounts                 建立帳號   {personnelId, username, email?, initialPassword?}
                                               initialPassword 留空 → 系統產生並回傳一次；有填 → 管理員指定，不回傳
  POST /api/personnel-accounts/disable         停用帳號   {personnelId}
  POST /api/personnel-accounts/reset-password  重設密碼   {personnelId} → 回傳一次性新密碼

密碼只出現在這一次回應（Cache-Control: no-store），不會寫進資料庫明文、日誌或 Audit。
邏輯與 CLI 共用 personnel/accounts.py。
"""
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from . import accounts
from .views import serialize


def serialize_with_username(person, username):
    return serialize(person, {person.auth_user_id or "": username})


def _person_id(request):
    try:
        return int(request.data.get("personnelId"))
    except (TypeError, ValueError, AttributeError):
        return None


class AccountBase(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"POST": "accounts.manage"}

    def post(self, request):
        person_id = _person_id(request)
        if person_id is None or person_id < 1:
            return Response({"error": "personnel_required", "message": "A valid personnelId is required."}, status=400)
        try:
            return self.run(request, person_id, actor_from(request.ri_principal), request_id_from(request))
        except accounts.AccountError as e:
            return Response({"error": e.code, "message": e.message}, status=e.status)


class CreateAccountView(AccountBase):
    """
    initialPassword 有填 -> 管理員指定的初始密碼（須通過密碼規則，且不會再回傳）。
    沒填 -> 系統隨機產生，只在這次回應回傳一次。
    """

    def run(self, request, person_id, actor, request_id):
        supplied = request.data.get("initialPassword")
        person, user, password, generated = accounts.create_account(
            personnel_id=person_id, username=request.data.get("username"), email=request.data.get("email"),
            password=str(supplied) if supplied not in (None, "") else None,
            actor=actor, source="application", request_id=request_id,
        )
        body = {"ok": True, "person": serialize_with_username(person, user.username),
                "username": user.username, "passwordSource": "generated" if generated else "admin"}
        if generated:
            body["initialPassword"] = password  # 只有系統產生的才回傳；管理員自己設的不回傳
        return Response(body, status=201)


class DisableAccountView(AccountBase):
    def run(self, request, person_id, actor, request_id):
        person, user, ended = accounts.disable_account(
            personnel_id=person_id, actor=actor, source="application", request_id=request_id,
            acting_personnel_id=request.ri_principal.pk,
        )
        return Response({"ok": True, "person": serialize_with_username(person, user.username), "sessionsEnded": ended})


class ResetPasswordView(AccountBase):
    def run(self, request, person_id, actor, request_id):
        person, user, password, ended = accounts.reset_password(
            personnel_id=person_id, actor=actor, source="application", request_id=request_id,
            acting_personnel_id=request.ri_principal.pk,
        )
        return Response(
            {"ok": True, "person": serialize_with_username(person, user.username),
             "username": user.username, "newPassword": password, "sessionsEnded": ended}
        )
