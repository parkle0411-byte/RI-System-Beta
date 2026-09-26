"""
Alpha（Hatchable PostgreSQL）資料表的匯出格式：每張表是「以 Alpha 欄位名稱為鍵」的資料列清單。

  {"source": {...}, "tables": {"ri_cases": [ {...}, ... ], ...}}，文件檔案另放一個目錄（檔名 = storage_key）。

canonical() 把「內容相同、寫法不同」的值統一，比對時才不會誤判：
  時間 → UTC、微秒的 ISO 文字；numeric → 去掉多餘的 0（"31.500000" 與 31.5 相同）；
  JSON 裡整數值的浮點數 → 整數（JavaScript 不分 5 與 5.0）。
"""
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

# 每張表在 Alpha 的欄位（見 Alpha 的 migrations）。VM 專有的欄位（例如 personnel.must_change_password）不在匯出格式裡。
COLUMNS = {
    "ri_master_records": ["id", "entity_type", "code", "name", "display_order", "is_active", "payload", "row_version",
                          "created_by", "created_at", "updated_by", "updated_at", "deactivated_by", "deactivated_at"],
    "ri_personnel": ["id", "name", "email", "department", "role_code", "is_active", "is_split_eligible", "account_status",
                     "supervisor_name", "supervisor_email", "row_version", "created_by", "created_at", "updated_by", "updated_at",
                     "deactivated_by", "deactivated_at", "auth_user_id", "account_invited_by", "account_invited_at",
                     "account_activated_at", "account_disabled_by", "account_disabled_at"],
    "ri_fx_rates": ["id", "year_month", "currency", "rate", "row_version", "is_locked", "locked_by", "locked_at", "lock_reason",
                    "created_by", "created_at", "updated_by", "updated_at"],
    "ri_cases": ["id", "legacy_case_id", "parent_case_id", "tw_ref", "case_kind", "status", "reinsurance_structure",
                 "class_master_id", "class_code_snapshot", "class_name_snapshot", "reinsured_master_id", "reinsured_name_snapshot",
                 "ae_master_id", "ae_name_snapshot", "currency", "effective_date", "expiration_date", "payload", "row_version",
                 "is_archived", "archived_by", "archived_at", "recycled_by", "recycled_at", "created_by", "created_at",
                 "updated_by", "updated_at", "case_uid", "announced_by", "announced_at", "owner_personnel_id"],
    "ri_case_documents": ["id", "case_id", "kind", "reinsurers", "filename", "content_type", "byte_size", "sha256",
                          "storage_key", "is_selected", "uploaded_by", "uploaded_at"],
    "ri_draft_recycle_bin": ["id", "original_case_id", "original_case_version", "case_snapshot", "deleted_by", "deleted_at",
                             "restore_deadline", "restored_by", "restored_at", "permanently_deleted_by", "permanently_deleted_at"],
    "ri_production_reports": ["id", "report_uid", "year_month", "version", "status", "rows", "excluded_rows", "source_signature",
                              "row_version", "close_token", "created_by", "created_at", "closed_by", "closed_at"],
    "ri_production_exclusions": ["id", "case_id", "year_month", "scope", "installment_key", "reinsurer_key", "deferred_to",
                                 "reason", "created_by", "created_at"],
    "ri_dashboard_targets": ["id", "period_type", "period_key", "amount", "is_active", "row_version", "created_by", "created_at",
                             "updated_by", "updated_at", "deactivated_by", "deactivated_at"],
    "ri_reference_sequences": ["prefix", "last_value", "updated_at"],
    # VM 尚未有這兩張表（提醒信還沒移植）：先記在轉換批次裡，之後再依對照表匯入
    "ri_payment_alerts": None,
    "ri_signed_slip_alerts": None,
}
TIME_COLUMNS = {"created_at", "updated_at", "deactivated_at", "locked_at", "archived_at", "recycled_at", "announced_at",
                "uploaded_at", "deleted_at", "restore_deadline", "restored_at", "permanently_deleted_at", "closed_at",
                "account_invited_at", "account_activated_at", "account_disabled_at"}
DATE_COLUMNS = {"effective_date", "expiration_date"}
DECIMAL_COLUMNS = {"rate", "amount"}
JSON_COLUMNS = {"payload", "reinsurers", "case_snapshot", "rows", "excluded_rows"}
# 帳號相關：切換後重新建立（2026-09-26 你的決定），不匯入也不比對；email 沿用第一次匯入的規則，不匯入
PERSONNEL_SKIPPED = {"email", "supervisor_email", "account_status", "auth_user_id", "account_invited_by", "account_invited_at",
                     "account_activated_at", "account_disabled_by", "account_disabled_at"}


def parse_time(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        t = value
    else:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def time_text(value):
    t = parse_time(value)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00") if t else None


def decimal_text(value):
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    text = format(d.normalize(), "f")
    return "0" if text in ("-0", "") else text


def json_canonical(value):
    if isinstance(value, dict):
        return {k: json_canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_canonical(v) for v in value]
    if isinstance(value, float) and value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    return value


def canonical(table, row, skip=()):
    out = {}
    for col, value in row.items():
        if col in skip:
            continue
        if col in TIME_COLUMNS:
            value = time_text(value)
        elif col in DATE_COLUMNS:
            value = str(value)[:10] if value not in (None, "") else None
        elif col in DECIMAL_COLUMNS:
            value = decimal_text(value)
        elif col in JSON_COLUMNS:
            value = json_canonical(value if not isinstance(value, str) else json.loads(value))
        elif col in ("id", "case_id", "parent_case_id", "original_case_id") and isinstance(value, str) and value.isdigit():
            value = int(value)          # node-postgres 把 bigint 當文字回傳
        elif col in ("code", "supervisor_name") and value == "":
            value = None                # 空字串與 null 視為相同（VM 存 null）
        elif isinstance(value, float) and value.is_integer():
            value = int(value)
        elif isinstance(value, (datetime, date)):
            value = value.isoformat()
        out[col] = value
    return out


def row_hash(table, row, skip=()):
    blob = json.dumps(canonical(table, row, skip), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def source_hash(export):
    blob = json.dumps(export.get("tables", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- VM → Alpha 格式（匯出、來回比對用）

def _value(v):
    if isinstance(v, datetime):
        return time_text(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return decimal_text(v)
    if hasattr(v, "hex") and not isinstance(v, (str, bytes, int)):
        return str(v)          # UUID
    return v


def export_model_row(table, obj):
    cols = COLUMNS[table]
    data = {f.column: _value(getattr(obj, f.attname)) for f in obj._meta.concrete_fields}
    return {c: data.get(c) for c in cols}
