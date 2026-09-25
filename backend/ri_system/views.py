from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()

    return JsonResponse(
        {
            "status": "ok",
            "service": "ri-backend",
            "database": "ok",
        }
    )


def csrf_failure(request, reason=""):
    """CSRF 驗證失敗時回傳 JSON（預設是 HTML 頁面，前端無法解析）。"""
    return JsonResponse(
        {"error": "CSRF_FAILED", "message": "Security token is missing or expired. Reload the page and try again."},
        status=403,
    )
