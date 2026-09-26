import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def read_secret(env_name, default_path):
    secret_path = os.getenv(env_name, default_path)
    return Path(secret_path).read_text(encoding="utf-8").strip()


SECRET_KEY = read_secret(
    "DJANGO_SECRET_KEY_FILE",
    "/run/secrets/django_secret_key",
)

DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "127.0.0.1,localhost,192.168.1.127",
    ).split(",")
    if host.strip()
]

# 案件文件的檔案本體（Docker volume `case_documents` 掛在這裡；見 cases/storage.py）
CASE_DOCUMENT_ROOT = os.getenv("RI_CASE_DOCUMENT_ROOT", "/data/documents")
# 上傳以 JSON（base64）送出：10 MB 的檔案約 14 MB 的請求內容
DATA_UPLOAD_MAX_MEMORY_SIZE = 16 * 1024 * 1024
# Signed Slip 提醒信：VM 尚未設定寄信（SMTP 未決定），如實回報 false
SIGNED_SLIP_OUTBOUND_ENABLED = os.getenv("RI_SIGNED_SLIP_OUTBOUND_ENABLED", "false").lower() == "true"

AUDIT_LOG_ENABLED = (
    os.getenv("AUDIT_LOG_ENABLED", "false").lower() == "true"
)

INSTALLED_APPS = [
    "ri_system.apps.RIAdminConfig",  # 唯讀的 Django admin（見 ri_system/admin_site.py）
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "fxrates",
    "masterdata",
    "personnel",
    "cases",
    "production",
    "dashboard",
    "conversion",
    "audit",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ri_system.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ri_system.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE", "ri_system"),
        "USER": os.getenv("MYSQL_USER", "ri_app"),
        "PASSWORD": read_secret(
            "MYSQL_PASSWORD_FILE",
            "/run/secrets/mysql_app_password",
        ),
        "HOST": os.getenv("MYSQL_HOST", "mysql"),
        "PORT": os.getenv("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "charset": "utf8mb4",
            "isolation_level": "read committed",
        },
    }
}

# ---- 登入 / Session / CSRF ----
# 目前 VM 是純 HTTP（區網）。上正式環境加上 HTTPS 後，DJANGO_COOKIE_SECURE 必須設為 true。
COOKIE_SECURE = os.getenv("DJANGO_COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_NAME = "ri_sessionid"
SESSION_COOKIE_AGE = 8 * 60 * 60  # 8 小時，閒置滑動延長
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = COOKIE_SECURE
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "ri_system.views.csrf_failure"
CSRF_COOKIE_SECURE = COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://192.168.1.127:8080,http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    # 預設拒絕：任何沒有明確宣告權限的 view 都需要登入
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "ri_system.authz.ri_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_THROTTLE_RATES": {"login": os.getenv("RI_LOGIN_THROTTLE", "10/min")},
}

# 密碼規則（要告知同事的規則）：至少 8 個字元，且必須同時包含英文字母與數字。
# 前端的提示文字在 frontend/src/passwordRule.js，兩邊要一起改。
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "ri_system.password_validators.LetterAndDigitValidator",
    },
]

LANGUAGE_CODE = "zh-hant"
TIME_ZONE = "Asia/Taipei"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
