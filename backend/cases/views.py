"""
案件 API - 對應 Hatchable Alpha 的 api/cases.js（含 #7、#8）。

  GET  /api/cases              dashboard.read + (cases.read.all | cases.read.own)  列表 + summary
  GET  /api/cases?caseUid=…    同上                                                 單一案件
  POST /api/cases              cases.write     新增 Draft
  PUT  /api/cases              cases.write     編輯 Draft／Announced／Reversed（樂觀鎖 rowVersion）

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - 列表的金額用 cases/calc/totals.py（記帳的逐步進位算法），不用 Alpha 的未進位算法。
  - 預設案件負責人只用「目前登入者」（VM 沒有 Hatchable 協作者的 P.L 後備）。
  - id、rowVersion 一律輸出成數字（Alpha 的 bigint 欄位在列表裡會變成字串）。
  - 見 resolve.py：主檔名稱精確比對、同名人員的拒絕、付款條件鎖定的比較方式。
"""
import json
import uuid

from django.db import IntegrityError, transaction
from django.db.models import BooleanField, Count, Q
from django.db.models.expressions import RawSQL
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from masterdata.models import MasterRecord
from ri_system.authz import AuthError, NoStoreMixin, RIPermission, actor_from, has_permission

from .calc.jsnum import js_is_integer, js_to_number, js_to_string
from .calc.payment_terms import derive_ledger_settlement
from .calc.totals import list_financials
from .draft import normalize_draft
from .models import Case
from .resolve import (
    payment_terms_signature, resolve_case_owner, resolve_master_references,
    resolve_personnel_splits, same_content,
)

DISPLAY_VERSION = "V 0.003"
LIST_LIMIT = 250

# Alpha：party->>'personnelId' = $2::text。JSON_TABLE 把 splitParties 展開成列，逐一比對。
_SPLIT_MEMBER_SQL = (
    "EXISTS (SELECT 1 FROM JSON_TABLE(ri_cases.payload, '$.splitParties[*]' "
    "COLUMNS (pid VARCHAR(40) PATH '$.personnelId')) AS party WHERE party.pid = %s)"
)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _json_text(payload, key):
    """payload->>'key'：不存在或 JSON null 回傳 None，其他一律轉成文字。"""
    value = payload.get(key) if isinstance(payload, dict) else None
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return js_to_string(value)


def _first_text(payload, *keys):
    for key in keys:
        value = _json_text(payload, key)
        if value is not None:
            return value
    return ""


def visible_cases(person):
    """有 cases.read.all 看全部；否則只看自己負責、或被列為 Performance Split 的案件。"""
    base = Case.objects.filter(recycled_at__isnull=True, is_archived=False)
    if has_permission(person, "cases.read.all"):
        return base
    return base.annotate(
        _split_member=RawSQL(_SPLIT_MEMBER_SQL, [str(person.pk)], output_field=BooleanField())
    ).filter(Q(owner_personnel_id=person.pk) | Q(_split_member=True))


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _case_state(*, case_uid, status, case_kind, row_version, columns, master_references, payload):
    return {
        "caseUid": str(case_uid), "status": status, "caseKind": case_kind, "rowVersion": row_version,
        "reinsuranceStructure": columns["reinsuranceStructure"], "currency": columns["currency"],
        "effectiveDate": _iso(columns["effectiveDate"]), "expirationDate": _iso(columns["expirationDate"]),
        "masterReferences": master_references, "payload": payload,
    }


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


class CasesView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "dashboard.read", "POST": "cases.write", "PUT": "cases.write"}

    def get(self, request):
        person = request.ri_principal
        if not has_permission(person, "cases.read.all") and not has_permission(person, "cases.read.own"):
            raise AuthError(403, "PERMISSION_DENIED", "You do not have permission to read cases.")
        case_uid = request.query_params.get("caseUid")
        if case_uid:
            return self.get_case(case_uid, person)
        return self.list_cases(person)

    # ---- 列表 ---------------------------------------------------------------

    def list_cases(self, person):
        scoped = visible_cases(person).filter(parent_case__isnull=True)
        rows = list(scoped.order_by("-updated_at", "-id")[:LIST_LIMIT])
        summary = scoped.aggregate(
            total=Count("id"),
            draft=Count("id", filter=Q(status="draft")),
            posted=Count("id", filter=Q(status="posted")),
            closed=Count("id", filter=Q(status="closed")),
            reversed=Count("id", filter=Q(status="reversed")),
        )

        # 縮寫：同名（不分大小寫）取「啟用優先、id 較大」的那筆
        abbreviations = {}
        masters = MasterRecord.objects.filter(entity_type__in=["reinsurer", "reinsured"]).order_by("-is_active", "-id")
        for master in masters:
            key = f"{master.entity_type}:{master.name.strip().lower()}"
            if key not in abbreviations:
                abbreviations[key] = _json_text(master.payload, "abbreviation") or ""
                abbreviations[key] = abbreviations[key].strip()

        def display_name(entity_type, name):
            return abbreviations.get(f"{entity_type}:{str(name or '').strip().lower()}") or name or ""

        cases = []
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else {}
            reinsurer_rows = payload.get("reinsurers")
            reinsurers = [
                _json_text(item, "name") if isinstance(item, dict) else None
                for item in (reinsurer_rows if isinstance(reinsurer_rows, list) else [])
            ]
            reinsured = row.reinsured_name_snapshot or ""
            cases.append({
                "id": row.pk, "caseUid": str(row.case_uid), "twRef": row.tw_ref, "status": row.status,
                "rowVersion": row.row_version,
                **list_financials(payload),
                "caseKind": row.case_kind, "reinsuranceStructure": row.reinsurance_structure,
                "ownerPersonnelId": row.owner_personnel_id,
                "ownerPersonnelName": _json_text(payload, "ownerPersonnelName") or "",
                "originalInsured": _first_text(payload, "originalInsured", "original_insured"),
                "originalInsuredCn": _first_text(payload, "originalInsuredCn"),
                "reinsurers": reinsurers,
                "reinsurerDisplayNames": [display_name("reinsurer", name) for name in reinsurers],
                "currency": _first_text(payload, "currency"),
                "reinsured": reinsured,
                "reinsuredDisplayName": display_name("reinsured", reinsured),
                "className": row.class_name_snapshot if row.class_name_snapshot is not None else (row.class_code_snapshot or ""),
                "aeName": row.ae_name_snapshot or "",
                "effectiveDate": row.effective_date,
                "effectiveTime": "00:00" if payload.get("policyFromTime") == "00:00" else "12:00",
                "expirationDate": row.expiration_date,
                "expirationTime": "00:00" if payload.get("policyToTime") == "00:00" else "12:00",
                "announcedAt": row.announced_at, "updatedAt": row.updated_at,
            })
        return Response({"ok": True, "displayVersion": DISPLAY_VERSION, "cases": cases, "summary": summary})

    # ---- 單筆 ---------------------------------------------------------------

    def get_case(self, case_uid, person):
        parsed = _parse_uuid(case_uid)
        row = visible_cases(person).filter(case_uid=parsed).first() if parsed else None
        if row is None:
            return _error(404, "case_not_found", "Case was not found.")
        # 記帳交易上儲存的 settlement 對「保費來源」的列永遠是過時的（付款條件上線後沒有東西再寫它）。
        # 這裡即時算出狀態附在回傳內容上，不動資料庫裡的 payload；claim 來源的列維持原樣。
        payload = dict(row.payload or {})
        if isinstance(payload.get("transactions"), list):
            payload["transactions"] = [
                {**(t if isinstance(t, dict) else {}), "paymentScheduleSettlement": derive_ledger_settlement(payload, t)}
                for t in payload["transactions"]
            ]
        return Response({
            "ok": True, "displayVersion": DISPLAY_VERSION,
            "case": {
                "id": row.pk, "caseUid": str(row.case_uid), "twRef": row.tw_ref, "status": row.status,
                "caseKind": row.case_kind, "parentCaseId": row.parent_case_id,
                "rowVersion": row.row_version, "payload": payload,
                "announcedAt": row.announced_at, "updatedAt": row.updated_at,
            },
        })

    # ---- 新增 Draft ---------------------------------------------------------

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        normalized = normalize_draft(body.get("case"))
        if normalized["errors"]:
            return _error(400, "validation_failed", normalized["errors"][0], errors=normalized["errors"])

        person = request.ri_principal
        actor_info = actor_from(person)
        case_uid = uuid.uuid4()
        payload = normalized["value"]
        columns = normalized["columns"]
        if not payload.get("ownerPersonnelId"):
            # VM 只用「目前登入者」當預設負責人（已在 load_principal 確認在職）
            payload["ownerPersonnelId"] = person.pk
            payload["ownerPersonnelName"] = person.name

        split_error = resolve_personnel_splits(payload)
        if split_error:
            return Response(split_error, status=400)
        owner = resolve_case_owner(payload)
        if "error" in owner:
            return Response(owner, status=400)
        masters = resolve_master_references(payload)
        after = _case_state(case_uid=case_uid, status="draft", case_kind="original", row_version=1,
                            columns=columns, master_references=masters, payload=payload)

        with transaction.atomic():
            try:
                case = Case.objects.create(
                    case_uid=case_uid, case_kind="original", status="draft",
                    reinsurance_structure=columns["reinsuranceStructure"],
                    class_master_id=masters["classMasterId"],
                    class_code_snapshot=payload.get("classCode") or None,
                    class_name_snapshot=payload.get("classOfBusiness") or None,
                    reinsured_master_id=masters["reinsuredMasterId"],
                    reinsured_name_snapshot=payload.get("reinsured") or None,
                    ae_master_id=masters["aeMasterId"], ae_name_snapshot=payload.get("ae") or None,
                    currency=columns["currency"], effective_date=columns["effectiveDate"],
                    expiration_date=columns["expirationDate"], payload=payload,
                    owner_personnel_id=owner["id"],
                    created_by=actor_info["id"], updated_by=actor_info["id"],
                )
            except IntegrityError:
                return _error(400, "validation_failed", "The case data violates a database rule.")
            record_snapshot(entity_type="case", entity_id=case_uid, version=1, reason="draft_created",
                            data=after, created_by=actor_info["id"])
            record_audit(entity_type="case", entity_id=case_uid, action="create_draft", before=None, after=after,
                         actor=actor_info, request_id=request_id_from(request),
                         metadata={"displayVersion": DISPLAY_VERSION, "milestone": "new-case-draft"})
        return Response({
            "ok": True, "displayVersion": DISPLAY_VERSION,
            "case": {"id": case.pk, "caseUid": str(case.case_uid), "status": case.status,
                     "rowVersion": case.row_version, "savedAt": case.updated_at},
        }, status=201)

    # ---- 編輯 ---------------------------------------------------------------

    def put(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        raw_uid = str(body.get("caseUid") or "").strip()
        if not raw_uid:
            return _error(400, "case_uid_required", "caseUid is required.")
        version = js_to_number(body.get("rowVersion"))  # Alpha：Number(req.body.rowVersion)，且必須是整數
        expected_version = int(version) if js_is_integer(version) else 0
        if expected_version < 1:
            return _error(400, "row_version_required", "A valid rowVersion is required.")

        person = request.ri_principal
        actor_info = actor_from(person)
        parsed_uid = _parse_uuid(raw_uid)

        with transaction.atomic():
            current = (
                Case.objects.select_for_update()
                .filter(case_uid=parsed_uid, recycled_at__isnull=True, is_archived=False).first()
                if parsed_uid else None
            )
            if current is None:
                return _error(404, "case_not_found", "Case was not found.")
            if current.status not in ("draft", "posted", "reversed"):
                return _error(409, "case_not_editable", "Only Draft, Announced, or Reversed cases can be edited.")
            if current.row_version != expected_version:
                return _error(409, "version_conflict", "This Draft was changed elsewhere. Reload it before saving again.",
                              currentRowVersion=current.row_version)

            normalized = normalize_draft(body.get("case"))
            if normalized["errors"]:
                return _error(400, "validation_failed", normalized["errors"][0], errors=normalized["errors"])
            payload = normalized["value"]
            columns = normalized["columns"]
            stored = current.payload if isinstance(current.payload, dict) else {}

            # #8：Claims 只能追加（用相反方向的付款更正，不刪除、不改寫），且只由 claims API 寫入；
            # transactions／paymentEntries 只由 claims、Reverse／Close、accounting 寫入。
            # 一般的案件編輯不得覆蓋它們，一律還原成資料庫目前的值，不管前端送了什麼。
            payload["claims"] = stored.get("claims") or []
            payload["transactions"] = stored.get("transactions") or []
            payload["paymentEntries"] = stored.get("paymentEntries") or []

            if current.status == "posted" and not same_content(
                payment_terms_signature(payload), payment_terms_signature(stored)
            ):
                return _error(409, "payment_terms_locked",
                              "Payment terms are locked after Announce. Create an Endorsement to change them.")
            # #7：Reversed 的案件存檔會直接變回 Announced，效果等同重新蓋上 Announced，
            # 所以要像 Announce 一樣由呼叫端明確確認。
            if current.status == "reversed" and body.get("reverseCorrectionConfirmed") is not True:
                return _error(409, "reverse_correction_confirmation_required",
                              "This case was Reversed. Saving will correct it and move it back to Announced status. Confirm to continue.")
            next_status = "posted" if current.status == "reversed" else current.status
            payload["status"] = next_status

            historical_split_ids = [
                int(p["personnelId"]) for p in (stored.get("splitParties") or [])
                if isinstance(p, dict) and isinstance(p.get("personnelId"), int) and p["personnelId"] > 0
            ] if isinstance(stored.get("splitParties"), list) else []
            split_error = resolve_personnel_splits(payload, historical_split_ids)
            if split_error:
                return Response(split_error, status=400)
            owner = resolve_case_owner(payload, current.owner_personnel_id)
            if "error" in owner:
                return Response(owner, status=400)
            if ((owner["id"] or 0) != (current.owner_personnel_id or 0)
                    and person.role_code != "admin" and person.pk != current.owner_personnel_id):
                return _error(403, "owner_transfer_denied",
                              "Only the current Case Owner or System Administrator can change the Case Owner.")

            masters = resolve_master_references(payload)
            before = _case_state(
                case_uid=current.case_uid, status=current.status, case_kind=current.case_kind,
                row_version=current.row_version,
                columns={"reinsuranceStructure": current.reinsurance_structure, "currency": current.currency,
                         "effectiveDate": current.effective_date, "expirationDate": current.expiration_date},
                master_references={"classMasterId": current.class_master_id,
                                   "reinsuredMasterId": current.reinsured_master_id,
                                   "aeMasterId": current.ae_master_id},
                payload=stored,
            )
            was_draft = current.status == "draft"
            current.reinsurance_structure = columns["reinsuranceStructure"]
            current.class_master_id = masters["classMasterId"]
            current.class_code_snapshot = payload.get("classCode") or None
            current.class_name_snapshot = payload.get("classOfBusiness") or None
            current.reinsured_master_id = masters["reinsuredMasterId"]
            current.reinsured_name_snapshot = payload.get("reinsured") or None
            current.ae_master_id = masters["aeMasterId"]
            current.ae_name_snapshot = payload.get("ae") or None
            current.currency = columns["currency"]
            current.effective_date = columns["effectiveDate"]
            current.expiration_date = columns["expirationDate"]
            current.payload = payload
            current.owner_personnel_id = owner["id"]
            current.status = next_status
            current.row_version += 1
            current.updated_by = actor_info["id"]
            try:
                current.save()
            except IntegrityError:
                return _error(400, "validation_failed", "The case data violates a database rule.")
            after = _case_state(
                case_uid=current.case_uid, status=next_status, case_kind=current.case_kind,
                row_version=current.row_version, columns=columns, master_references=masters, payload=payload,
            )
            record_snapshot(entity_type="case", entity_id=current.case_uid, version=current.row_version,
                            reason="draft_updated" if was_draft else "case_updated",
                            data=after, created_by=actor_info["id"])
            record_audit(entity_type="case", entity_id=current.case_uid,
                         action="update_draft" if was_draft else "update_case",
                         before=before, after=after, actor=actor_info, request_id=request_id_from(request),
                         metadata={"displayVersion": DISPLAY_VERSION, "milestone": "draft-edit"})
        return Response({
            "ok": True, "displayVersion": DISPLAY_VERSION,
            "case": {"id": current.pk, "caseUid": str(current.case_uid), "status": current.status,
                     "caseKind": current.case_kind, "rowVersion": current.row_version, "savedAt": current.updated_at},
        })
