"""
Master Data API (masterdata) - 對應 Hatchable Alpha 的 api/master-data.js。

TODO: 尚未接上登入權限系統（對應 Alpha 的 mdm.read / mdm.write）。
VM 上的登入機制完成前，先開放給所有已連線的使用者，之後要收緊。
TODO: 尚未實作 ri_entity_snapshots / ri_audit_log 寫入，
之後要做成共用模組再補上（對應 Alpha 目前也暫停 audit log 寫入的狀態）。
"""
import re

from django.db import transaction
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MasterRecord
from .serializers import MasterRecordSerializer

ALLOWED_TYPES = {"ae", "reinsurer", "reinsured", "class", "foreign_broker", "clause"}
UNIVERSAL_CLAUSE_CODES = {"LMA3333", "INTERMEDIARY"}

# TODO: 暫時使用固定 actor，登入機制完成後改為 request.user
ACTOR_PLACEHOLDER = "vm-system"


def clean_text(value, max_len):
    return str(value if value is not None else "").strip()[:max_len]


def normalize_clause_code(value):
    text = clean_text(value, 80).upper()
    return re.sub(r"\s+", "_", text)


def validate_payload(entity_type, supplied, fallback=None):
    fallback = fallback if isinstance(fallback, dict) else {}
    if supplied is None:
        return fallback, None
    if not isinstance(supplied, dict):
        return None, "Master-data payload must be an object."

    value = {}
    abbreviation = clean_text(supplied.get("abbreviation"), 80)
    if entity_type in ("reinsurer", "reinsured", "foreign_broker"):
        value["abbreviation"] = abbreviation
    if entity_type == "reinsured":
        value["address"] = clean_text(supplied.get("address"), 1000)
    if entity_type != "reinsurer":
        return value, None

    fixed_clauses_in = supplied.get("fixedClauses", [])
    if fixed_clauses_in is not None and not isinstance(fixed_clauses_in, list):
        return None, "Fixed clauses must be a list."
    fixed_clauses_in = fixed_clauses_in or []
    if len(fixed_clauses_in) > 100:
        return None, "A reinsurer cannot contain more than 100 fixed clauses."

    seen = set()
    fixed_clauses = []
    for row in fixed_clauses_in:
        row = row or {}
        code = normalize_clause_code(row.get("code"))
        title = clean_text(row.get("title"), 300)
        if not code or not title:
            return None, "Every fixed clause requires both a code and full name."
        if code in UNIVERSAL_CLAUSE_CODES:
            return None, f"{code} is universal and must not be added to a reinsurer."
        if code in seen:
            return None, f"Fixed clause {code} is duplicated."
        seen.add(code)
        fixed_clauses.append({"code": code, "title": title})

    ratings_in = supplied.get("ratings", [])
    if ratings_in is not None and not isinstance(ratings_in, list):
        return None, "Ratings must be a list."
    ratings_in = ratings_in or []
    if len(ratings_in) > 50:
        return None, "A reinsurer cannot contain more than 50 ratings."

    ratings = []
    for row in ratings_in:
        row = row or {}
        agency = clean_text(row.get("agency"), 120)
        grade = clean_text(row.get("grade"), 80)
        if not agency or not grade:
            return None, "Every rating requires both an agency and a grade."
        ratings.append({
            "agency": agency,
            "grade": grade,
            "outlook": clean_text(row.get("outlook"), 80),
            "ratingType": clean_text(row.get("ratingType"), 120),
            "asOfDate": clean_text(row.get("asOfDate"), 40),
            "legalEntity": clean_text(row.get("legalEntity"), 240),
            "sourceUrl": clean_text(row.get("sourceUrl"), 1000),
            "checkedAt": clean_text(row.get("checkedAt"), 80),
            "status": clean_text(row.get("status"), 80),
        })

    value["fixedClauses"] = fixed_clauses
    value["ratings"] = ratings
    return value, None


def serialize_record(record):
    return MasterRecordSerializer(record).data


class MasterDataView(APIView):
    """
    GET  /api/master-data?entityType=xxx   -> 列表 + counts
    POST /api/master-data                   -> 新增
    PUT  /api/master-data                   -> 編輯（含 optimistic lock）
    """

    permission_classes = [AllowAny]

    def get(self, request):
        requested_type = clean_text(request.query_params.get("entityType"), 40).lower()
        if requested_type and requested_type not in ALLOWED_TYPES:
            return Response(
                {"error": "invalid_entity_type", "message": "Unsupported master-data type."},
                status=400,
            )
        qs = MasterRecord.objects.all()
        if requested_type:
            qs = qs.filter(entity_type=requested_type)
        qs = qs.order_by("entity_type", "-is_active", "name", "id")

        records = [serialize_record(r) for r in qs]
        counts = {t: 0 for t in ["ae", "reinsurer", "reinsured", "class", "foreign_broker", "clause"]}
        for r in qs:
            if r.is_active and r.entity_type in counts:
                counts[r.entity_type] += 1

        return Response({"ok": True, "displayVersion": "V 0.003", "records": records, "counts": counts})

    def post(self, request):
        body = request.data or {}
        entity_type = clean_text(body.get("entityType"), 40).lower()
        code = clean_text(body.get("code"), 80).upper()
        name = clean_text(body.get("name"), 240)

        if entity_type not in ALLOWED_TYPES:
            return Response(
                {"error": "invalid_entity_type", "message": "Select AE, Reinsurer, Reinsured, Class, Foreign RI Broker, or Clause."},
                status=400,
            )
        if not name:
            return Response({"error": "name_required", "message": "Name is required."}, status=400)
        if entity_type == "clause" and not code:
            return Response({"error": "code_required", "message": "Clause code is required."}, status=400)
        if entity_type == "clause" and code in UNIVERSAL_CLAUSE_CODES:
            return Response(
                {"error": "reserved_code", "message": f"{code} is a system-managed universal clause and cannot be created here."},
                status=400,
            )

        payload, err = validate_payload(entity_type, body.get("payload"), {})
        if err:
            return Response({"error": "invalid_fixed_clauses", "message": err}, status=400)

        with transaction.atomic():
            if MasterRecord.objects.filter(entity_type=entity_type, name__iexact=name).exists():
                return Response(
                    {"error": "duplicate_name", "message": "This name already exists in the selected master-data type."},
                    status=409,
                )
            if code and MasterRecord.objects.filter(entity_type=entity_type, code__iexact=code).exists():
                return Response(
                    {"error": "duplicate_code", "message": "This code already exists in the selected master-data type."},
                    status=409,
                )

            record = MasterRecord.objects.create(
                entity_type=entity_type,
                code=code or None,
                name=name,
                is_active=True,
                payload=payload,
                created_by=ACTOR_PLACEHOLDER,
                updated_by=ACTOR_PLACEHOLDER,
            )

        return Response(
            {"ok": True, "displayVersion": "V 0.003", "record": serialize_record(record)},
            status=201,
        )

    def put(self, request):
        body = request.data or {}
        try:
            record_id = int(body.get("id"))
            expected_version = int(body.get("rowVersion"))
        except (TypeError, ValueError):
            return Response(
                {"error": "version_required", "message": "A valid master id and rowVersion are required."},
                status=400,
            )
        entity_type = clean_text(body.get("entityType"), 40).lower()
        code = clean_text(body.get("code"), 80).upper()
        name = clean_text(body.get("name"), 240)
        is_active = body.get("isActive") is not False

        if record_id < 1 or expected_version < 1:
            return Response(
                {"error": "version_required", "message": "A valid master id and rowVersion are required."},
                status=400,
            )
        if entity_type not in ALLOWED_TYPES or not name:
            return Response(
                {"error": "invalid_master", "message": "A supported type and name are required."},
                status=400,
            )

        with transaction.atomic():
            try:
                current = MasterRecord.objects.select_for_update().get(id=record_id)
            except MasterRecord.DoesNotExist:
                return Response({"error": "master_not_found", "message": "Master record was not found."}, status=404)

            if current.entity_type != entity_type:
                return Response({"error": "type_immutable", "message": "Master-data type cannot be changed."}, status=400)

            current_code_upper = (current.code or "").upper()
            if entity_type == "clause" and current_code_upper in UNIVERSAL_CLAUSE_CODES:
                return Response(
                    {"error": "reserved_record", "message": "This universal clause is system-managed and cannot be edited or deactivated here."},
                    status=400,
                )
            if entity_type == "clause" and not code:
                return Response({"error": "code_required", "message": "Clause code is required."}, status=400)
            if entity_type == "clause" and code in UNIVERSAL_CLAUSE_CODES:
                return Response(
                    {"error": "reserved_code", "message": f"{code} is a system-managed universal clause and cannot be reused."},
                    status=400,
                )
            if current.row_version != expected_version:
                return Response(
                    {
                        "error": "version_conflict",
                        "message": "This master record changed elsewhere. Reload before saving.",
                        "currentRowVersion": current.row_version,
                    },
                    status=409,
                )

            payload, err = validate_payload(
                entity_type,
                body.get("payload") if "payload" in body else None,
                current.payload or {},
            )
            if err:
                return Response({"error": "invalid_fixed_clauses", "message": err}, status=400)

            if MasterRecord.objects.filter(entity_type=entity_type, name__iexact=name).exclude(id=record_id).exists():
                return Response(
                    {"error": "duplicate_name", "message": "This name already exists in the selected master-data type."},
                    status=409,
                )
            if code and MasterRecord.objects.filter(entity_type=entity_type, code__iexact=code).exclude(id=record_id).exists():
                return Response(
                    {"error": "duplicate_code", "message": "This code already exists in the selected master-data type."},
                    status=409,
                )

            current.code = code or None
            current.name = name
            current.is_active = is_active
            current.payload = payload
            current.row_version = current.row_version + 1
            current.updated_by = ACTOR_PLACEHOLDER
            if is_active:
                current.deactivated_by = None
                current.deactivated_at = None
            else:
                current.deactivated_by = ACTOR_PLACEHOLDER
                current.deactivated_at = timezone.now()
            current.save()

        return Response({"ok": True, "displayVersion": "V 0.003", "record": serialize_record(current)})
