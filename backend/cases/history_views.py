"""GET /api/case-history?caseUid=：案件 Announce 之後的事件與內容修改（2026-11-27 業主決定）。

能打開該案件的人就看得到（與 GET /api/cases?caseUid= 相同的權限與範圍）。只讀版本紀錄，不寫任何資料；
Audit Log 暫停與否都不影響。草稿階段只保留一份最新副本，所以只列第一次 Announce 之後的紀錄。
Facility 案件暫不提供（業主 2026-11-27 決定）。
"""
import uuid
from datetime import timedelta

from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import EntitySnapshot
from personnel.models import Personnel
from ri_system.authz import AuthError, NoStoreMixin, RIPermission, has_permission

from .history import CLAIM_REASONS, CONTENT_REASONS, EVENT_LABELS, MAX_CHANGES, compare, label
from .views import visible_cases

MAX_EVENTS = 200
SYSTEM_ACTORS = {"cli": "System (maintenance)", "system": "System"}


def _actor_names(values):
    ids = {int(v.split(":", 1)[1]) for v in values if v.startswith("personnel:") and v.split(":", 1)[1].isdigit()}
    names = {f"personnel:{pk}": name for pk, name in Personnel.objects.filter(pk__in=ids).values_list("pk", "name")}
    return lambda value: names.get(value) or SYSTEM_ACTORS.get(value.split(":", 1)[0]) or value


class CaseHistoryView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "dashboard.read"}

    def get(self, request):
        person = request.ri_principal
        if not has_permission(person, "cases.read.all") and not has_permission(person, "cases.read.own"):
            raise AuthError(403, "PERMISSION_DENIED", "You do not have permission to read cases.")
        try:
            uid = uuid.UUID(str(request.query_params.get("caseUid")))
        except ValueError:
            uid = None
        case = (visible_cases(person).filter(case_uid=uid).exclude(reinsurance_structure="FACILITY")
                .only("case_uid", "announced_at").first()) if uid else None
        if case is None:
            return Response({"error": "case_not_found", "message": "Case was not found."}, status=404)

        # 只先讀小欄位；payload 需要比對時才逐筆讀（單筆可能很大，不能放進排序，見 ri_system/sorted_fetch.py）
        snapshots = EntitySnapshot.objects.filter(entity_type="case", entity_id=str(case.case_uid))
        rows = list(snapshots.order_by("entity_version").values_list(
            "pk", "entity_version", "snapshot_reason", "created_by", "created_at"))
        start = next((i for i, row in enumerate(rows) if row[2] == "announced"), None)
        if start is None and case.announced_at:
            since = case.announced_at - timedelta(seconds=5)
            start = next((i for i, row in enumerate(rows) if row[4] >= since), None)
        if start is None:
            return Response({"ok": True, "announced": bool(case.announced_at), "events": [], "truncated": False})
        first = max(start, len(rows) - MAX_EVENTS)

        loaded = {}

        def payload_of(index):
            if index not in loaded:
                data = snapshots.values_list("snapshot_data", flat=True).get(pk=rows[index][0])
                value = data.get("payload") if isinstance(data, dict) else None
                loaded[index] = value if isinstance(value, dict) else None
            return loaded[index]

        actor = _actor_names({row[3] for row in rows[first:]})
        events = []
        for index in range(first, len(rows)):
            _, version, reason, created_by, created_at = rows[index]
            event = {"version": version, "at": created_at, "actorName": actor(created_by), "reason": reason,
                     "action": EVENT_LABELS.get(reason) or label(reason), "compared": False, "changes": [],
                     "comment": None, "comparedWithVersion": None, "truncated": False}
            if (reason in CONTENT_REASONS or reason in CLAIM_REASONS) and index > start and payload_of(index) is not None:
                # 前一個存有完整內容的版本
                base = next((j for j in range(index - 1, -1, -1) if payload_of(j) is not None), None)
                if base is not None:
                    changes, comment = compare(reason, payload_of(base), payload_of(index))
                    event.update(compared=True, changes=changes[:MAX_CHANGES], comment=comment,
                                 comparedWithVersion=rows[base][1], truncated=len(changes) > MAX_CHANGES)
            events.append(event)
        events.reverse()
        return Response({"ok": True, "announced": True, "events": events, "truncated": first > start})
