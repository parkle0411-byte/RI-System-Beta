# 切換演練共用：登入與呼叫 API（在測試環境的 backend 容器內以 manage.py shell 執行）
import json
from datetime import datetime, timedelta, timezone
from django.core.cache import cache
from django.test import Client

PASSWORD = "Ui-Test-Pass-1"
TPE = timezone(timedelta(hours=8))


def login(username):
    c = Client(enforce_csrf_checks=True, HTTP_HOST="nginx", raise_request_exception=False)
    cache.clear()
    c.get("/api/auth/csrf")
    r = c.post("/api/auth/login", data=json.dumps({"username": username, "password": PASSWORD}), content_type="application/json",
               HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    assert r.status_code == 200, r.content
    return c


def call(c, method, url, body=None):
    c.get("/api/auth/csrf")
    kw = dict(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
    if body is None:
        return getattr(c, method)(url, **kw)
    return getattr(c, method)(url, data=json.dumps(body), content_type="application/json", **kw)


def months():
    now = datetime.now(TPE)
    m1 = f"{now.year:04d}-{now.month:02d}"
    y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return m1, f"{y:04d}-{m:02d}"
