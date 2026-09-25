from rest_framework.response import Response
from rest_framework.views import APIView

from ri_system.authz import NoStoreMixin, RIPermission

from .models import AuditLog


class AuditLogView(NoStoreMixin, APIView):
    """對應 Alpha 的 api/audit-log.js：唯讀，最新的在前面，最多 250 筆；欄位名稱與 Alpha 相同。"""

    permission_classes = [RIPermission]
    permission_map = {"GET": "audit.read"}

    def get(self, request):
        try:
            requested = int(request.query_params.get("limit", 100))
        except (TypeError, ValueError):
            requested = 100
        limit = min(max(requested, 1), 250)
        events = list(
            AuditLog.objects.order_by("-occurred_at", "-id").values(
                "id", "entity_type", "entity_id", "action", "before_data", "after_data",
                "actor_id", "actor_name", "actor_role", "request_id", "source",
                "occurred_at", "retention_until", "metadata",
            )[:limit]
        )
        return Response({"ok": True, "displayVersion": "V 0.003", "events": events, "readOnly": True})
