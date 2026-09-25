"""
登入 / 登出 / 目前使用者 / 改密碼。

Session + CSRF：前端先 GET /api/auth/csrf 取得 csrftoken cookie，之後所有寫入請求帶 X-CSRFToken。
登入端點本身也強制檢查 CSRF（防止 login CSRF），並有限流（見 settings 的 DRF throttle rate）。
"""
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .authz import AuthError, NoStoreMixin, RIPermission, load_principal, serialize_principal


class CsrfView(NoStoreMixin, APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        get_token(request)  # 確保 csrftoken cookie 被設定
        return Response({"ok": True})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(NoStoreMixin, APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        username = str(request.data.get("username") or "").strip().lower()
        password = str(request.data.get("password") or "")
        user = authenticate(request, username=username, password=password) if username and password else None
        if user is None:
            # 不區分「帳號不存在」與「密碼錯誤」，避免帳號列舉
            return Response(
                {"error": "INVALID_CREDENTIALS", "message": "Invalid username or password."}, status=401
            )
        # 憑證正確後才檢查 Personnel 狀態；不符合就不建立 session
        request.user = user
        person = load_principal(request)
        login(request, user)
        return Response({"ok": True, "principal": serialize_principal(person)})


class LogoutView(NoStoreMixin, APIView):
    permission_classes = []  # 未登入時登出也視為成功（冪等）

    def post(self, request):
        logout(request)
        return Response({"ok": True})


class AppContextView(NoStoreMixin, APIView):
    """對應 Alpha 的 /api/app-context：前端啟動時用來取得目前使用者與權限。"""

    permission_classes = []  # 由 load_principal 回 401 / 403（Alpha 相同錯誤碼）

    def get(self, request):
        person = load_principal(request)
        return Response({
            "principal": serialize_principal(person),
            "authenticationEnabled": True,
            "permissionModel": "enforced",
        })


class ChangePasswordView(NoStoreMixin, APIView):
    permission_classes = []

    def post(self, request):
        person = load_principal(request)
        current = str(request.data.get("currentPassword") or "")
        new = str(request.data.get("newPassword") or "")
        if not request.user.check_password(current):
            raise AuthError(400, "INVALID_CURRENT_PASSWORD", "Current password is incorrect.")
        if person.must_change_password and new == current:
            raise AuthError(400, "PASSWORD_UNCHANGED", "The new password must be different from the temporary password.")
        try:
            validate_password(new, request.user)
        except ValidationError as exc:
            raise AuthError(400, "WEAK_PASSWORD", " ".join(exc.messages))
        request.user.set_password(new)
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)  # 改密碼後保持目前這個 session 登入
        if person.must_change_password:
            person.must_change_password = False
            person.save(update_fields=["must_change_password"])
        return Response({"ok": True, "changedAt": timezone.now().isoformat(), "principal": serialize_principal(person)})
