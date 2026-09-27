"""
忘記密碼：同事自己用 e-mail 重設密碼（VM 才有；2026-09-27 你的決定）。

  GET  /api/auth/password-reset           公開  {enabled}：寄信是否已啟用（登入頁據此顯示「Forgot password?」）
  POST /api/auth/password-reset           公開  {identifier: 帳號或 e-mail} → 一律回同一句話（不透露帳號是否存在）
  POST /api/auth/password-reset/confirm   公開  {uid, token, newPassword} → 設定新密碼

規則：
  - 寄信未啟用（settings.EMAIL_ENABLED = false，SMTP 尚未決定）時回 503 password_reset_unavailable，登入頁不顯示入口。
  - 只寄給在職、帳號啟用、Personnel 有有效 e-mail 的人；用 e-mail 找時必須剛好對到一個人。
  - 連結用 Django 內建的 PasswordResetTokenGenerator：PASSWORD_RESET_TIMEOUT（1 小時）內有效；密碼一改、或該帳號登入後，
    舊連結就失效（只能用一次）。
  - 新密碼套用與改密碼相同的規則；重設後結束該帳號所有登入中的 session，must_change_password 清除（是本人自己設的）。
  - Audit：寄出連結寫 request_password_reset，完成重設寫 reset_own_password（都不含密碼與連結）。
  - 申請與完成都有限流（settings 的 password_reset rate）。
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.html import escape
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from audit.services import record_audit, request_id_from
from personnel.accounts import end_sessions
from personnel.audit_state import personnel_state
from personnel.models import Personnel
from reminders.messages import valid_email

from .authz import NoStoreMixin

log = logging.getLogger(__name__)
GENERIC = "If the account exists and has an e-mail address, a password reset link has been sent. The link is valid for 1 hour."
REQUEST_ACTOR = {"id": "password-reset", "name": "Password reset request", "role": "system"}


def _error(status, code, message):
    return Response({"error": code, "message": message}, status=status)


def _eligible(person):
    return person.is_active and person.account_status == "active" and person.auth_user_id and valid_email(person.email)


def find_person(identifier):
    """帳號（不分大小寫）或 e-mail（不分大小寫，必須剛好一個人）。找不到或不符資格回 None。"""
    text = str(identifier or "").strip()
    if not text:
        return None
    if "@" in text:
        matches = [p for p in Personnel.objects.filter(email__iexact=text) if _eligible(p)]
        return matches[0] if len(matches) == 1 else None
    user = get_user_model().objects.filter(username__iexact=text, is_active=True).first()
    if user is None:
        return None
    person = Personnel.objects.filter(auth_user_id=str(user.pk)).first()
    return person if person and _eligible(person) else None


def reset_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/reset-password?uid={uid}&token={token}"


def send_reset_email(person, user):
    link = reset_link(user)
    subject = "[Reinsurance Department System] 重設密碼 Password reset"
    text = (f"{person.name} 您好：\n\n我們收到重設您 Reinsurance Department System 密碼的申請（帳號：{user.username}）。"
            f"請在 1 小時內開啟以下連結設定新密碼：\n{link}\n\n如果不是您本人申請，請忽略這封信，您的密碼不會改變。\n\n"
            f"We received a request to reset your password (username: {user.username}). Open the link above within 1 hour to set a new password. "
            "If you did not request this, ignore this e-mail.\n\n本信由系統自動產生。")
    html = (f"<p>{escape(person.name)} 您好：</p><p>我們收到重設您 Reinsurance Department System 密碼的申請（帳號：<strong>{escape(user.username)}</strong>）。"
            f"請在 1 小時內開啟以下連結設定新密碼：</p><p><a href=\"{escape(link)}\">重設密碼 Reset password</a></p>"
            "<p>如果不是您本人申請，請忽略這封信，您的密碼不會改變。</p>"
            f"<p style=\"color:#666\">We received a request to reset your password (username: {escape(user.username)}). Open the link above within 1 hour "
            "to set a new password. If you did not request this, ignore this e-mail.</p><p style=\"color:#666\">本信由系統自動產生。</p>")
    mail = EmailMultiAlternatives(subject=subject, body=text, from_email=settings.DEFAULT_FROM_EMAIL, to=[person.email.strip()])
    mail.attach_alternative(html, "text/html")
    mail.send(fail_silently=False)


class PasswordResetView(NoStoreMixin, APIView):
    authentication_classes = []
    permission_classes = []
    throttle_scope = "password_reset"

    def get_throttles(self):
        return [ScopedRateThrottle()] if self.request.method == "POST" else []

    def get(self, request):
        return Response({"enabled": settings.EMAIL_ENABLED})

    def post(self, request):
        if not settings.EMAIL_ENABLED:
            return _error(503, "password_reset_unavailable", "Password reset by e-mail is not available yet. Please contact a System Administrator.")
        person = find_person(request.data.get("identifier") if isinstance(request.data, dict) else None)
        if person is not None:
            user = get_user_model().objects.get(pk=int(person.auth_user_id))
            try:
                send_reset_email(person, user)
            except Exception as exc:  # noqa: BLE001 - 不透露給申請者；記在伺服器日誌
                log.error("Password reset e-mail failed for personnel %s: %s", person.pk, exc)
                return Response({"ok": True, "message": GENERIC})
            with transaction.atomic():
                state = personnel_state(person)
                record_audit(entity_type="personnel", entity_id=person.pk, action="request_password_reset", before=state, after=state,
                             actor=REQUEST_ACTOR, source="application", request_id=request_id_from(request),
                             metadata={"username": user.username, "emailSent": True})
        return Response({"ok": True, "message": GENERIC})


class PasswordResetConfirmView(NoStoreMixin, APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        invalid = _error(400, "invalid_reset_link", "This password reset link is invalid or has expired. Request a new one.")
        try:
            user = get_user_model().objects.get(pk=int(force_str(urlsafe_base64_decode(str(body.get("uid") or "")))), is_active=True)
        except (ValueError, TypeError, OverflowError, get_user_model().DoesNotExist):
            return invalid
        if not default_token_generator.check_token(user, str(body.get("token") or "")):
            return invalid
        person = Personnel.objects.filter(auth_user_id=str(user.pk)).first()
        if person is None or not person.is_active or person.account_status != "active":
            return invalid
        new = str(body.get("newPassword") or "")
        try:
            validate_password(new, user)
        except ValidationError as exc:
            return _error(400, "WEAK_PASSWORD", " ".join(exc.messages))
        with transaction.atomic():
            user.set_password(new)
            user.save(update_fields=["password"])
            ended = end_sessions(user)
            changed = person.must_change_password
            if changed:
                person.must_change_password = False
                person.save(update_fields=["must_change_password"])
            state = personnel_state(person)
            record_audit(entity_type="personnel", entity_id=person.pk, action="reset_own_password", before=state, after=state,
                         actor={"id": f"personnel:{person.pk}", "name": person.name, "role": person.role_code}, source="application",
                         request_id=request_id_from(request),
                         metadata={"username": user.username, "sessionsEnded": ended, "via": "email_link", "mustChangePasswordCleared": changed})
        return Response({"ok": True, "message": "Your password has been reset. Sign in with the new password."})
