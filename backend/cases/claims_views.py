"""
理賠 API - 對應 Hatchable Alpha 的 api/claims.js。

  GET  /api/claims?caseUid=…   cases.read.all   這個保單期間的理賠（存在「根案件」上；從任何一張批單看都一樣）
  POST /api/claims             cases.write      action = create_claim | update_reserve | record_payment

record_payment 會立刻產生 Claim Leg 1/2 交易（payload.transactions），分攤依「最新一張已 Announce／Confirmed 的批單」
（沒有就用根案件）的再保人比例；這些交易會出現在 SOA 與 Accounting 帳本。

與 Alpha 的差異（都記在 MIGRATION-STATUS.md）：
  - 交易編號用根案件的 TW Ref（Alpha 傳入的 payload 沒有 twRef，編號開頭會是 "undefined"）。
  - 出險日、付款日期必填，而且必須是真實存在的日期（Alpha 不檢查，可留空或任何文字）。
  - 未決賠款準備：看不懂的文字回 400（Alpha 當成 0）、不可為負；準備金與付款金額都進位到分（Alpha 原樣存）。
  - 補寫 Snapshot；先鎖根案件列，再檢查、寫入（Alpha 是事後以「除以零」檢查版本）。
"""
import re
import uuid
from datetime import date

from django.db import IntegrityError, transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import record_audit, record_snapshot, request_id_from
from ri_system.authz import NoStoreMixin, RIPermission, actor_from

from .calc.accounting import build_claim_payment_transactions
from .calc.jsnum import (
    UNDEFINED, get, is_array, is_nullish, js_is_finite, js_is_integer, js_max, js_or, js_slice, js_string_to_number,
    js_to_number, js_to_string, js_trim, json_roundtrip, money,
)
from .models import Case

ACTIONS = ("create_claim", "update_reserve", "record_payment")
AUDIT_ACTIONS = {"create_claim": "create_claim", "update_reserve": "update_claim_reserve", "record_payment": "record_claim_payment"}
SNAPSHOT_REASONS = {"create_claim": "claim_created", "update_reserve": "claim_reserve_updated", "record_payment": "claim_payment_recorded"}
_DATE_SHAPE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def _error(status, code, message, **extra):
    return Response({"error": code, "message": message, **extra}, status=status)


def clean_text(value, max_len=1000):
    """String(value == null ? '' : value).trim().slice(0, max)"""
    return js_slice(js_trim("" if is_nullish(value) else js_to_string(value)), 0, max_len)


def _parse_amount(value):
    """
    Number(String(value ?? '').replace(/,/g, ''))；留空是 0（同 Alpha）。
    回傳 None 表示看不懂（Alpha 會安靜地當成 0；VM 拒絕）。
    """
    number = js_string_to_number(("" if is_nullish(value) else js_to_string(value)).replace(",", ""))
    return number if js_is_finite(number) else None


def _real_date(value):
    if not isinstance(value, str) or not _DATE_SHAPE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _payload(case):
    return case.payload if isinstance(case.payload, dict) and case.payload else {}


def _live(qs):
    return qs.filter(recycled_at__isnull=True, is_archived=False)


def _find_case(case_uid):
    try:
        parsed = uuid.UUID(case_uid)
    except ValueError:
        return None
    if str(parsed) != case_uid:  # Alpha 比對 case_uid::text，只接受小寫、有連字號的標準寫法
        return None
    return _live(Case.objects).filter(case_uid=parsed).first()


def _root_and_chain(row, lock=False):
    qs = _live(Case.objects.select_for_update() if lock else Case.objects)
    root = qs.filter(pk=row.parent_case_id).first() if row.parent_case_id else (qs.filter(pk=row.pk).first() if lock else row)
    if root is None:
        return None
    # ORDER BY CASE WHEN parent_case_id IS NULL THEN 0 ELSE 1 END, id
    chain = sorted(_live(Case.objects).filter(pk=root.pk) | _live(Case.objects).filter(parent_case_id=root.pk),
                   key=lambda c: (0 if c.parent_case_id is None else 1, c.pk))
    chain = [root if c.pk == root.pk else c for c in chain]
    return root, chain


def _split_source(root, chain):
    locked = [c for c in chain if c.parent_case_id and c.status in ("posted", "closed")]
    return locked[-1] if locked else root


def claims_view(root, chain):
    payload = _payload(root)
    split = _split_source(root, chain)
    split_reinsurers = _payload(split).get("reinsurers")
    return {
        "rootCaseUid": str(root.case_uid),
        "rootTwRef": root.tw_ref or "",
        "rootStatus": root.status,
        "rootRowVersion": root.row_version,
        "currency": js_or(payload.get("currency"), ""),
        "claims": payload["claims"] if is_array(payload.get("claims")) else [],
        "splitSource": {
            "caseUid": str(split.case_uid), "twRef": split.tw_ref or "", "status": split.status,
            "reinsurers": split_reinsurers if is_array(split_reinsurers) else [],
        },
        "actions": {"canWrite": bool(root.tw_ref)},
    }


def _next_id(rows):
    """rows.reduce((max, item) => Math.max(max, Number(item?.id) || 0), 0) + 1"""
    top = 0.0
    for item in rows:
        top = js_max(top, js_or(js_to_number(get(item, "id")), 0.0))
    return top + 1


def _id_out(value):
    return int(value) if js_is_integer(value) else value


class ClaimsView(NoStoreMixin, APIView):
    permission_classes = [RIPermission]
    permission_map = {"GET": "cases.read.all", "POST": "cases.write"}

    def get(self, request):
        case_uid = clean_text(request.query_params.get("caseUid"), 80)
        if not case_uid:
            return _error(400, "case_uid_required", "caseUid is required.")
        row = _find_case(case_uid)
        if row is None:
            return _error(404, "case_not_found", "Case was not found.")
        state = _root_and_chain(row)
        if state is None:
            return _error(404, "root_case_not_found", "The root case was not found.")
        return Response(json_roundtrip({"ok": True, "claimsState": claims_view(*state)}))

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        case_uid = clean_text(body.get("caseUid"), 80)
        action = clean_text(body.get("action"), 40)
        expected = js_to_number(body.get("rowVersion", UNDEFINED))
        if not case_uid:
            return _error(400, "case_uid_required", "caseUid is required.")
        if not js_is_integer(expected) or expected < 1:
            return _error(400, "row_version_required", "A valid root rowVersion is required.")
        if action not in ACTIONS:
            return _error(400, "invalid_action", "Unsupported Claims action.")
        try:
            with transaction.atomic():
                return self._apply(request, body, case_uid, action, int(expected))
        except IntegrityError:
            return _error(409, "version_conflict", "Claims changed elsewhere. Reload before saving.")

    def _apply(self, request, body, case_uid, action, expected):
        selected = _find_case(case_uid)
        if selected is None:
            return _error(404, "case_not_found", "Case was not found.")
        state = _root_and_chain(selected, lock=True)
        if state is None:
            return _error(404, "root_case_not_found", "The root case was not found.")
        root, chain = state
        if not root.tw_ref:
            return _error(409, "claim_reference_required",
                          "Claims can be recorded after the root case has been Announced and assigned a TW Reference.")
        if root.row_version != expected:
            return _error(409, "version_conflict", "Claims changed elsewhere. Reload before saving.",
                          currentRowVersion=root.row_version)

        old_payload = _payload(root)
        payload = json_roundtrip(old_payload)
        payload["claims"] = payload["claims"] if is_array(payload.get("claims")) else []

        if action == "create_claim":
            data = body.get("claim")
            date_of_loss = clean_text(get(data, "dateOfLoss"), 20)
            if not _real_date(date_of_loss):
                return _error(400, "invalid_date_of_loss", "Enter the Date of Loss as a valid date (YYYY-MM-DD).")
            reserve = _parse_amount(get(data, "outstandingReserve"))
            if reserve is None or reserve < 0:
                return _error(400, "invalid_claim_reserve", "Outstanding Reserve must be a number of zero or more.")
            claim = {
                "id": _id_out(_next_id(payload["claims"])),
                "lossNo": clean_text(get(data, "lossNo"), 160),
                "dateOfLoss": date_of_loss,
                "causeOfLoss": clean_text(get(data, "causeOfLoss"), 2000),
                "outstandingReserve": money(reserve),
                "payments": [],
            }
            payload["claims"].append(claim)
        else:
            claim_id = js_to_number(body.get("claimId", UNDEFINED))
            claim = next((c for c in payload["claims"] if js_to_number(get(c, "id")) == claim_id), None)
            if claim is None:
                return _error(404, "claim_not_found", "Claim was not found.")
            if action == "update_reserve":
                reserve = _parse_amount(body.get("outstandingReserve"))
                if reserve is None or reserve < 0:
                    return _error(400, "invalid_claim_reserve", "Outstanding Reserve must be a number of zero or more.")
                claim["outstandingReserve"] = money(reserve)
            else:
                data = body.get("payment")
                # 理賠付款可以是負數（追償、自負額沖抵等，2026-09-25 確認），只拒絕 0 與看不懂的輸入
                amount = _parse_amount(get(data, "amount"))
                amount = money(amount) if amount is not None else 0
                if not amount:
                    return _error(400, "payment_amount_required", "Enter a non-zero payment amount.")
                payment_date = clean_text(get(data, "date"), 20)
                if not _real_date(payment_date):
                    return _error(400, "invalid_payment_date", "Enter the payment date as a valid date (YYYY-MM-DD).")
                claim["payments"] = claim["payments"] if is_array(claim.get("payments")) else []
                payment = {"id": _id_out(_next_id(claim["payments"])), "date": payment_date, "amount": amount,
                           "note": clean_text(get(data, "note"), 1000)}
                claim["payments"].append(payment)
                split = _split_source(root, chain)
                payload["transactions"] = payload["transactions"] if is_array(payload.get("transactions")) else []
                # Alpha 傳入的 payload 沒有 twRef（編號開頭會是 "undefined"）：補上根案件的 TW Ref
                payload["transactions"].extend(build_claim_payment_transactions(
                    {**payload, "twRef": root.tw_ref}, _payload(split), claim, payment))

        payload = json_roundtrip(payload)
        claim_id = _id_out(js_or(get(claim, "id"), None))
        actor_info = actor_from(request.ri_principal)
        root.payload = payload
        root.row_version += 1
        root.updated_by = actor_info["id"]
        root.save()
        record_snapshot(entity_type="case", entity_id=root.case_uid, version=root.row_version,
                        reason=SNAPSHOT_REASONS[action],
                        data={"caseUid": str(root.case_uid), "twRef": root.tw_ref, "status": root.status,
                              "rowVersion": root.row_version, "payload": payload},
                        created_by=actor_info["id"])
        record_audit(entity_type="case", entity_id=root.case_uid, action=AUDIT_ACTIONS[action],
                     before={"rowVersion": expected, "payload": old_payload},
                     after={"rowVersion": root.row_version, "payload": payload},
                     actor=actor_info, request_id=request_id_from(request),
                     metadata={"claimId": claim_id, "action": action})
        return Response(json_roundtrip({"ok": True, "action": action, "claimId": claim_id,
                                        "claimsState": claims_view(root, chain)}))
