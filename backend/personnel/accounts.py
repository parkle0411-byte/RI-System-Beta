"""
帳號生命週期（建立 / 停用 / 重設密碼）的唯一實作。
管理指令（CLI）與管理員畫面（API）都呼叫這裡，行為與稽核紀錄完全一致。

- 初始密碼有兩種來源：管理員指定，或（留空時）由系統隨機產生。
  無論哪種都不寫入資料庫明文、日誌或 Audit；系統產生的只回傳給呼叫者一次，管理員自己設的不再回傳。
  管理員指定的密碼與使用者自己改密碼走同一套 Django 密碼規則（長度、常見密碼、純數字、與帳號名太像）。
- 每個動作與它的 Audit / Snapshot 在同一個交易內；稽核寫入失敗就整個回滾。
- 「最後一位啟用中的管理員」與「不能停用自己」的保護放在這裡，讓 CLI 與 API 都受同樣限制。
"""
import re
import secrets
import string

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from audit.services import record_audit, record_snapshot
from personnel.audit_state import personnel_state
from personnel.models import Personnel

ALPHABET = string.ascii_letters + string.digits + "!@#%^*-_=+"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@+-]{2,149}$")


class AccountError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def generate_password(length=20):
    while True:
        pwd = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


def end_sessions(user):
    """立刻讓這個使用者所有已登入的 session 失效。"""
    ended = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
            session.delete()
            ended += 1
    return ended


def active_admin_count():
    return Personnel.objects.filter(role_code="admin", is_active=True, account_status="active").count()


def _lock(personnel_id):
    try:
        return Personnel.objects.select_for_update().get(pk=personnel_id)
    except Personnel.DoesNotExist:
        raise AccountError("personnel_not_found", "Personnel record was not found.", 404)


MAX_PASSWORD_LENGTH = 128


def check_admin_password(password, username, email):
    """管理員指定的初始密碼必須通過與一般使用者相同的密碼規則。"""
    if not password.strip():
        raise AccountError("weak_password", "Password must not be blank.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AccountError("weak_password", f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    candidate = get_user_model()(username=username, email=email)  # 只用來檢查「與帳號資料太像」，不會存檔
    try:
        validate_password(password, candidate)
    except ValidationError as exc:
        raise AccountError("weak_password", " ".join(exc.messages))


def create_account(*, personnel_id, username, email, actor, source, request_id=None, password=None):
    """
    password 有值 = 管理員指定的初始密碼；None 或空字串 = 系統隨機產生。
    回傳 (person, user, password, generated)；generated 為 False 時，password 是呼叫者自己給的，不應再回傳給畫面。
    """
    User = get_user_model()
    username = str(username or "").strip().lower()  # 帳號一律小寫，登入時也不分大小寫
    email = str(email or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise AccountError(
            "invalid_username",
            "Username must be 3-150 characters: lower-case letters, digits and . _ @ + - (starting with a letter or digit).",
        )
    with transaction.atomic():
        person = _lock(personnel_id)
        if not person.is_active:
            raise AccountError("personnel_inactive", f"{person.name} is inactive; activate the Personnel record first.", 409)
        if person.auth_user_id:
            raise AccountError("account_exists", f"{person.name} already has an account (status: {person.account_status}).", 409)
        if User.objects.filter(username__iexact=username).exists():
            raise AccountError("username_taken", f"Username '{username}' is already in use.", 409)
        if email and Personnel.objects.filter(email__iexact=email).exclude(pk=person.pk).exists():
            raise AccountError("email_taken", f"Email '{email}' already belongs to another Personnel record.", 409)

        generated = not password
        if generated:
            password = generate_password()
        else:
            check_admin_password(password, username, email)

        before = personnel_state(person)
        user = User.objects.create_user(username=username, email=email, password=password)
        now = timezone.now()
        person.auth_user_id = str(user.pk)
        person.account_status = "active"
        person.account_invited_by = actor["id"]
        person.account_invited_at = now
        person.account_activated_at = now
        person.account_disabled_by = None
        person.account_disabled_at = None
        if email:
            person.email = email
        person.row_version += 1
        person.updated_by = actor["id"]
        person.save()

        after = personnel_state(person)
        record_snapshot(entity_type="personnel", entity_id=person.pk, version=person.row_version,
                        reason="personnel_account_created", data=after, created_by=actor["id"])
        # 只記錄「誰、什麼帳號、什麼角色」，不含密碼
        record_audit(entity_type="personnel", entity_id=person.pk, action="create_account",
                     before=before, after=after, actor=actor, source=source, request_id=request_id,
                     metadata={"username": username, "accountUserId": user.pk,
                               "passwordSource": "generated" if generated else "admin"})
    return person, user, password, generated


def disable_account(*, personnel_id, actor, source, request_id=None, acting_personnel_id=None):
    """回傳 (person, user, sessions_ended)。"""
    User = get_user_model()
    with transaction.atomic():
        person = _lock(personnel_id)
        if not person.auth_user_id:
            raise AccountError("no_account", f"{person.name} has no account.", 409)
        if person.account_status == "disabled":
            raise AccountError("already_disabled", f"{person.name}'s account is already disabled.", 409)
        if acting_personnel_id is not None and int(acting_personnel_id) == person.pk:
            raise AccountError("cannot_disable_own_account", "You cannot disable your own account.", 409)
        if person.role_code == "admin" and person.is_active and person.account_status == "active" and active_admin_count() <= 1:
            raise AccountError("last_active_admin", "The system must retain at least one active Admin.", 409)

        before = personnel_state(person)
        user = User.objects.get(pk=int(person.auth_user_id))
        user.is_active = False
        user.save(update_fields=["is_active"])
        ended = end_sessions(user)
        person.account_status = "disabled"
        person.account_disabled_by = actor["id"]
        person.account_disabled_at = timezone.now()
        person.row_version += 1
        person.updated_by = actor["id"]
        person.save()

        after = personnel_state(person)
        record_snapshot(entity_type="personnel", entity_id=person.pk, version=person.row_version,
                        reason="personnel_account_disabled", data=after, created_by=actor["id"])
        record_audit(entity_type="personnel", entity_id=person.pk, action="disable_account",
                     before=before, after=after, actor=actor, source=source, request_id=request_id,
                     metadata={"username": user.username, "sessionsEnded": ended})
    return person, user, ended


def reset_password(*, personnel_id, actor, source, request_id=None, acting_personnel_id=None):
    """回傳 (person, user, new_password, sessions_ended)。"""
    User = get_user_model()
    with transaction.atomic():
        person = _lock(personnel_id)
        if not person.auth_user_id or person.account_status != "active":
            raise AccountError("no_active_account", f"{person.name} has no active account.", 409)
        if acting_personnel_id is not None and int(acting_personnel_id) == person.pk:
            raise AccountError("cannot_reset_own_password", "Use Change Password to change your own password.", 409)
        user = User.objects.get(pk=int(person.auth_user_id))
        password = generate_password()
        user.set_password(password)
        user.save(update_fields=["password"])
        ended = end_sessions(user)
        state = personnel_state(person)
        # 密碼本身絕不寫入；只記錄「重設過」與結束了幾個 session
        record_audit(entity_type="personnel", entity_id=person.pk, action="reset_account_password",
                     before=state, after=state, actor=actor, source=source, request_id=request_id,
                     metadata={"username": user.username, "sessionsEnded": ended})
    return person, user, password, ended
