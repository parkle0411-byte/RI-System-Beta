from django.db import connection
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from .authz import NoStoreMixin, RIPermission


class HealthView(NoStoreMixin, APIView):
    """
    VM 的連線狀態（前端的 System status 畫面）。只有 System Administrator 能看（foundation.read，與 Alpha 的
    foundation-status 同一個權限；2026-09-26 你的決定）；未登入 401，其他角色 403。
    """
    permission_classes = [RIPermission]
    permission_map = {"GET": "foundation.read"}

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return Response({"status": "ok", "service": "ri-backend", "database": "ok"})


def csrf_failure(request, reason=""):
    """CSRF 驗證失敗時回傳 JSON（預設是 HTML 頁面，前端無法解析）。"""
    return JsonResponse(
        {"error": "CSRF_FAILED", "message": "Security token is missing or expired. Reload the page and try again."},
        status=403,
    )
