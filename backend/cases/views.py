"""
案件 API - 對應 Hatchable Alpha 的 api/cases.js（含 #7、#8）。

  GET  /api/cases              dashboard.read + (cases.read.all | cases.read.own)  列表 + summary
  GET  /api/cases?caseUid=…    同上                                                 單一案件
  POST /api/cases              cases.write     新增 Draft
  PUT  /api/cases              cases.write     編輯 Draft／Announced／Reversed（樂觀鎖 rowVersion）

與 Alpha 的差異（都記在 VM-RULES.md）：
  - 列表的金額用 cases/calc/totals.py（記帳的逐步進位算法），不用 Alpha 的未進位算法。
  - 預設案件負責人只用「目前登入者」（VM 沒有 Hatchable 協作者的 P.L 後備）。
  - id、rowVersion 一律輸出成數字（Alpha 的 bigint 欄位在列表裡會變成字串）。
  - 見 resolve.py：主檔名稱精確比對、同名人員的拒絕、付款條件鎖定的比較方式。
"""
import json
import copy
import uuid

from django.db import IntegrityError, transaction
from django.db.models import BooleanField, Count, Q
from django.db.models.expressions import RawSQL
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from coordination.services import PRODUCTION_SOURCES, serialized
from audit.services import record_audit, record_snapshot, request_id_from
from masterdata.models import MasterRecord
from ri_system.authz import AuthError, NoStoreMixin, RIPermission, actor_from, has_permission

from .calc.jsnum import js_is_integer, js_to_number, js_to_string
from .calc.payment_terms import derive_ledger_settlement
from .cash_ledger import transaction_details
from .calc.totals import list_financials
from .draft import loss_record_save_errors, normalize_draft
from . import draft_input
from .property_original import adopt, enabled as property_enabled, edit_guard, persist_settlements, scope as property_scope
from .sum_insured import prepare_transition
from .models import Case
from . import insured_master
from .manual_reference import manual_tw_ref_fields, requires_manual_tw_ref, manual_reference_error
from .resolve import (
    add_required_property_clauses, resolve_clause_titles, payment_terms_signature, resolve_case_owner, resolve_master_references,
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
                **manual_tw_ref_fields(payload),
                **list_financials(row.payload),
                "caseKind": row.case_kind, "reinsuranceStructure": row.reinsurance_structure,
                "ownerPersonnelId": row.owner_personnel_id,
                "ownerPersonnelName": _json_text(payload, "ownerPersonnelName") or "",
                "originalInsured": _first_text(payload, "originalInsured", "original_insured"),
                "originalInsuredCn": _first_text(payload, "originalInsuredCn"),
                "insuredMasterId": row.insured_master_id,
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
        # 即時計算逐筆保費、理賠收付與保留經紀費狀態；回傳欄位不寫回資料庫。
        from .calc.swiss_facility import case_payload
        from .data_integrity import financial_issues
        issues=financial_issues(row.payload)
        payload = copy.deepcopy(row.payload) if issues else resolve_clause_titles(case_payload(row))
        if not issues and row.case_kind == "endorsement" and row.parent_case_id and row.status == "draft":
            from .endorsement_rules import context_for, apply_fixed
            apply_fixed(payload, context_for(row))
        from .placing_rules import adj_rate
        computed_adj_rate = adj_rate(payload)
        if not issues and isinstance(payload.get("transactions"), list):
            cash = transaction_details({**payload, "currency":payload.get("currency") or row.currency, "reinsured":payload.get("reinsured") or row.reinsured_name_snapshot})
            payload["transactions"] = [
                {**t, "paymentScheduleSettlement": cash.get(t.get("txNo"), {}).get("settlement", derive_ledger_settlement(payload, t)),
                 **{k:v for k,v in cash.get(t.get("txNo"), {}).items() if k in ("cashTracking","cashDescription","paymentDirection","paid","outstanding")}}
                if isinstance(t, dict) else t for t in payload["transactions"]
            ]
        return Response({
            "ok": True, "displayVersion": DISPLAY_VERSION,
            "case": {
                "id": row.pk, "caseUid": str(row.case_uid), "twRef": row.tw_ref, "status": row.status,
                "caseKind": row.case_kind, "parentCaseId": row.parent_case_id, "insuredMaster": insured_master.information(row.insured_master),
                "rowVersion": row.row_version, "payload": payload, "adjRate": computed_adj_rate,
                **({'dataError':True,'dataIssues':issues} if issues else {}),
                "announcedAt": row.announced_at, "updatedAt": row.updated_at,
            },
        })

    # ---- 新增 Draft ---------------------------------------------------------

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        if isinstance(body.get("case"),dict) and body["case"].get("parentTwRef"):
            return _error(400,"workflow_required","Create endorsements through the Case workflow.")
        from .placing_rules import promote
        if isinstance(body.get('case'), dict):
            body['case'] = promote(dict(body['case']))
        incomplete = body.get('incompleteDraft') is True
        if incomplete and not draft_input.scope(body.get('case')):
            return _error(400, 'incomplete_draft_scope', 'Incomplete drafts require Property or CGL Quota Share with ordinary reinsurers.')
        normalized = draft_input.normalize(body.get('case')) if incomplete else normalize_draft(body.get("case"))
        if normalized["errors"]:
            return _error(400, "validation_failed", normalized["errors"][0], errors=normalized["errors"])
        loss_errors = [] if incomplete else loss_record_save_errors(normalized["value"])
        if loss_errors:
            return _error(400, "validation_failed", loss_errors[0], errors=loss_errors)

        person = request.ri_principal
        actor_info = actor_from(person)
        draft_key = body.get('draftKey') if incomplete else None
        if draft_key is not None and (not isinstance(draft_key, str) or not 16 <= len(draft_key) <= 128):
            return _error(400, 'invalid_draft_key', 'Draft retry key is invalid.')
        case_uid = uuid.uuid5(uuid.NAMESPACE_URL, f'ri-draft:{person.pk}:{draft_key}') if draft_key else uuid.uuid4()
        payload = normalized["value"]
        from .property_original import VERSION, VERSION_KEY, ordinary
        if property_scope(payload) and ordinary(payload):payload[VERSION_KEY]=VERSION
        adopt(payload)
        add_required_property_clauses(payload)
        resolve_clause_titles(payload)
        if payload.get("currency") == "TWD":
            payload["premiumRounding"] = "currency-stepwise-v1"
        # Draft creation never imports posting, receipt or settlement records.
        # These are owned by Production / Claims / Accounting for every case type.
        for field in ("transactions", "paymentEntries", "claims", "confirmedProductionKeys"):
            payload[field] = []
        payload["swissAccounting"] = {}
        payload["facilityAccounting"] = {}
        payload["cedantTermsBasis"] = "case"
        columns = normalized["columns"]
        if not payload.get("ownerPersonnelId"):
            # VM 只用「目前登入者」當預設負責人（已在 load_principal 確認在職）
            payload["ownerPersonnelId"] = person.pk
            payload["ownerPersonnelName"] = person.name

        split_error = None if incomplete else resolve_personnel_splits(payload)
        if split_error:
            return Response(split_error, status=400)
        owner = resolve_case_owner(payload)
        if "error" in owner:
            return Response(owner, status=400)
        masters = resolve_master_references(payload)
        after = _case_state(case_uid=case_uid, status="draft", case_kind="original", row_version=1,
                            columns=columns, master_references=masters, payload=payload)

        with serialized(PRODUCTION_SOURCES):
            if draft_key:
                prior = Case.objects.filter(case_uid=case_uid, created_by=actor_info['id']).first()
                if prior:
                    if prior.status != 'draft' or prior.is_archived or prior.recycled_at:
                        return _error(409, 'draft_retry_unavailable', 'The saved draft has moved to another workflow state.')
                    return Response({'ok': True, 'recoveredDraft': True, 'case': {
                        'id': prior.pk, 'caseUid': str(prior.case_uid), 'status': prior.status,
                        'rowVersion': prior.row_version, 'savedAt': prior.updated_at,
                    }})
            ref_error = manual_reference_error(payload)
            if ref_error:
                return _error(409, "manual_reference_conflict", ref_error)
            try:
                insured = insured_master.sync(None,payload,actor_info,body,new=True)
                case = Case.objects.create(
                    insured_master=insured,
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
                     "rowVersion": case.row_version, "insuredMaster": insured_master.information(case.insured_master), "savedAt": case.updated_at},
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

        with serialized(PRODUCTION_SOURCES):
            current = (
                Case.objects.select_for_update()
                .filter(case_uid=parsed_uid, recycled_at__isnull=True, is_archived=False).first()
                if parsed_uid else None
            )
            if current is None:
                return _error(404, "case_not_found", "Case was not found.")
            if current.status not in ("draft", "posted", "reversed") and not (current.status == "closed" and property_enabled(current.payload)):
                return _error(409, "case_not_editable", "Only Draft, Announced, or Reversed cases can be edited.")
            if current.row_version != expected_version:
                return _error(409, "version_conflict", "This Draft was changed elsewhere. Reload it before saving again.",
                              currentRowVersion=current.row_version)

            supplied_case = dict(body.get("case")) if isinstance(body.get("case"),dict) else body.get("case")
            if isinstance(supplied_case,dict):
                from .placing_rules import KEY
                supplied_case.pop(KEY, None)
                if KEY in (current.payload or {}): supplied_case[KEY] = current.payload[KEY]
                supplied_case["parentTwRef"] = (current.payload or {}).get("parentTwRef") or "" if current.case_kind=="endorsement" else ""
            incomplete = body.get('incompleteDraft') is True
            if incomplete and (current.status != 'draft' or not draft_input.scope(supplied_case, current.payload)):
                return _error(409, 'incomplete_draft_scope', 'Automatic saving is available only for incomplete ordinary QS Drafts.')
            candidate = prepare_transition(current.payload, supplied_case)
            if not isinstance(candidate, dict):
                # 2026-10-29：沒有 case 物件時回 400（原本批單會在下面的批單檢查出錯 500）；訊息同 normalize_draft
                return _error(400, "validation_failed", "case must be an object.", errors=["case must be an object."])
            endorsement_context = None
            if current.case_kind == "endorsement" and current.parent_case_id:
                from .endorsement_rules import context_for, apply_fixed, date_edit_error
                endorsement_context = context_for(current)
                if candidate.get('installmentEnabled') is True or candidate.get('performanceInstallments'):
                    return _error(400, 'endorsement_installments_not_allowed', 'Endorsements must use a single premium settlement.')
                error = date_edit_error(candidate, draft_input.input_for(current.payload or {}), unlocked=body.get("endorsementUnlocked") is True)
                if error:
                    return _error(409, "endorsement_period_locked", error)
                apply_fixed(candidate, endorsement_context)
            normalized = draft_input.normalize(candidate, existing=current.payload) if incomplete else normalize_draft(candidate,
                                         allow_negative_premiums=current.case_kind == "endorsement" and current.parent_case_id is not None,
                                         existing_premiums=current.payload)
            if normalized["errors"]:
                return _error(400, "validation_failed", normalized["errors"][0], errors=normalized["errors"])
            payload = normalized["value"]
            if endorsement_context:
                apply_fixed(payload, endorsement_context)
                payload["manualTwRef"] = (current.payload or {}).get("manualTwRef") or ""
            if (current.payload or {}).get("renewalPremiumBasis"):
                from .renewal_premiums import refresh_renewal_premiums
                if current.status == 'draft':
                    refresh_renewal_premiums(payload, current.payload, supplied_case)
                else:
                    for key in ('renewalPremiumBasis', 'renewalPremiumManual', 'renewalPremiumIssues'):
                        if key in current.payload:
                            payload[key] = copy.deepcopy(current.payload[key])
            loss_errors = [] if incomplete else loss_record_save_errors(payload, case_kind=current.case_kind)
            if loss_errors:
                return _error(400, "validation_failed", loss_errors[0], errors=loss_errors)
            if current.status != "draft":
                from .endorsement_rules import endorsement_issues
                term_issues = endorsement_issues(payload)
                if term_issues:
                    return _error(400, "case_not_ready", term_issues[0]["label"], issues=term_issues)
            columns = normalized["columns"]
            stored = current.payload if isinstance(current.payload, dict) else {}
            adopt(payload, stored)
            if incomplete:
                for key in ('accountingRules', 'accountingLegacyMath', 'propertyOriginalRules'):
                    if key in stored and key not in payload:
                        payload[key] = stored[key]
            if stored.get(insured_master.KEY): payload[insured_master.KEY]=True
            add_required_property_clauses(payload)
            resolve_clause_titles(payload)
            payload["confirmedProductionKeys"] = stored.get("confirmedProductionKeys") or []
            if stored.get("premiumRounding") == "legacy-cents":
                payload["premiumRounding"] = "legacy-cents"
            elif payload.get("currency") == "TWD":
                payload["premiumRounding"] = "currency-stepwise-v1"

            ref_error = manual_reference_error(payload, exclude_case_uid=current.case_uid)
            if ref_error:
                return _error(409, "manual_reference_conflict", ref_error)
            # Primary references are immutable after Announce, as with system references.
            if stored.get("twRefSource") == "auw_manual" and payload.get("manualTwRef") != current.tw_ref:
                return _error(409, "primary_reference_locked", "The AUW reference is the primary TW Reference and is locked after Announce.")
            for key in ("twRefSource", "previousTwRefs"):
                if key in stored:
                    payload[key] = stored[key]
            # 2026-10-14：「新案 Cedant 天數以案件為準」一旦記錄就由伺服器保留，不依賴前端是否回傳
            if stored.get("cedantTermsBasis") == "case":
                payload["cedantTermsBasis"] = "case"
            if current.case_kind != "endorsement" and current.status in ("posted", "reversed") and requires_manual_tw_ref(payload) and not payload.get("manualTwRef"):
                message = "TW Ref. (for AUW) is required for an Announced case with 0609 AUW (Facility)."
                return _error(400, "validation_failed", message, errors=[message])
            # Endorsement identity comes from the persisted workflow, not editable request fields.
            if current.case_kind == "endorsement" and current.parent_case_id is not None:
                payload["parentTwRef"] = stored.get("parentTwRef") or current.parent_case.tw_ref or ""
                payload["endorsementSeq"] = stored.get("endorsementSeq")
                from .endorsement_terms import apply_endorsement_terms
                root = current.parent_case
                from .calc.swiss_facility import applies as swiss_applies
                apply_endorsement_terms(payload, root, announced_at=current.announced_at)
                if "endorsementPerformanceMonth" in stored:
                    payload["endorsementPerformanceMonth"] = stored["endorsementPerformanceMonth"]

            # Claims 及其未收付更正只由 claims API 寫入；
            # transactions／paymentEntries 只由 claims、Reverse／Close、accounting 寫入。
            # 一般的案件編輯不得覆蓋它們，一律還原成資料庫目前的值，不管前端送了什麼。
            payload["claims"] = stored.get("claims") or []
            payload["transactions"] = stored.get("transactions") or []
            payload["paymentEntries"] = stored.get("paymentEntries") or []
            for key in ("paymentEditHistory", "claimCorrectionHistory", "accountingAdjustmentHistory", "paymentTermsHistory", "allianzClaimTracking", "greatAmericanClaimTracking", "qbeClaimTracking"):
                if key in stored:
                    payload[key] = stored[key]
            if "facilityAccounting" in stored:
                payload["facilityAccounting"] = stored["facilityAccounting"]
            from .calc.swiss_facility import applies as swiss_applies
            if "swissAccounting" in stored or swiss_applies(payload):
                payload["swissAccounting"] = stored.get("swissAccounting") or {}

            if current.status == "posted" and not property_enabled(stored) and not property_enabled(payload) and not same_content(
                payment_terms_signature(payload), payment_terms_signature(stored)
            ):
                return _error(409, "payment_terms_locked",
                              "Payment terms are locked after Announce. Create an Endorsement to change them.")
            # #7：Reversed 的案件存檔會直接變回 Announced，效果等同重新蓋上 Announced，
            # 所以要像 Announce 一樣由呼叫端明確確認。
            if current.status == "reversed" and body.get("reverseCorrectionConfirmed") is not True:
                return _error(409, "reverse_correction_confirmation_required",
                              "This case was Reversed. Saving will correct it and move it back to Announced status. Confirm to continue.")
            next_status = ("draft" if property_enabled(stored) else "posted") if current.status == "reversed" else current.status
            payload["status"] = next_status

            historical_split_ids = [
                int(p["personnelId"]) for p in (stored.get("splitParties") or [])
                if isinstance(p, dict) and isinstance(p.get("personnelId"), int) and p["personnelId"] > 0
            ] if isinstance(stored.get("splitParties"), list) else []
            split_error = None if incomplete else resolve_personnel_splits(payload, historical_split_ids)
            if split_error:
                return Response(split_error, status=400)
            if endorsement_context:
                apply_fixed(payload, endorsement_context)
            owner = resolve_case_owner(payload, current.owner_personnel_id)
            if "error" in owner:
                return Response(owner, status=400)
            if ((owner["id"] or 0) != (current.owner_personnel_id or 0)
                    and person.role_code != "admin" and person.pk != current.owner_personnel_id
                    and not (incomplete and current.status == 'draft' and current.owner_personnel_id is None and current.created_by == actor_info['id'])):
                return _error(403, "owner_transfer_denied",
                              "Only the current Case Owner or System Administrator can change the Case Owner.")

            now = timezone.now().isoformat()
            if property_enabled(stored) and current.status != "draft":
                if payload.get("reinsurers") != stored.get("reinsurers"):
                    from .documents import coverage_for
                    from .models import CaseDocument
                    files = [{"id":str(d.pk),"kind":d.kind,"reinsurers":d.reinsurers,"is_selected":d.is_selected} for d in CaseDocument.objects.filter(case=current)]
                    if not coverage_for(payload,files)["ready"]:
                        return _error(409,"documents_not_ready","Select an Offer and Signed Slip or Confirmation Email covering every revised Reinsurer before saving.")
                problem = edit_guard(current,payload,body,actor_info,now)
                if problem:
                    return _error(409,"property_edit_locked",problem)
            if current.status == "posted" and property_enabled(payload) and not property_enabled(stored):
                reason=str(body.get("reason") or "").strip()
                if not reason:return _error(400,"change_reason_required","Enter a reason for changing this placement.")
                from .property_original import refresh_transactions
                payload["twRef"]=current.tw_ref
                refresh_transactions(payload,now)
                persist_settlements(payload,now,actor_info)
                payload.setdefault("propertyEditHistory",[]).append({"at":now,"by":actor_info["id"],"reason":reason,"operation":"ordinary_rules_selected"})
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
            try:
                insured=insured_master.sync(current,payload,actor_info,body)
            except insured_master.MergeRequired as exc:
                return Response(exc.data,status=409)
            current.insured_master=insured
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
            from .calc.swiss_facility import reset_after_changes
            reset_after_changes(stored, payload, timezone.now().isoformat())
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
                     "caseKind": current.case_kind, "rowVersion": current.row_version, "insuredMaster": insured_master.information(current.insured_master), "savedAt": current.updated_at},
        })
