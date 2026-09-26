"""
Alpha → VM 資料轉換的 ID 對應（純函式，不碰資料庫）。

VM 會重新編號（2026-09-26 你的決定），所以 Alpha 的數字 ID 出現的每一個地方都要換成 VM 的 ID：
  案件 ID   ri_cases.parent_case_id、ri_case_documents.case_id、ri_draft_recycle_bin.original_case_id（含 case_snapshot）、
            ri_production_exclusions.case_id／installment_key／reinsurer_key、ri_production_reports.rows／excluded_rows
            （caseId、id、key、reinsurerKey）、payload.confirmedProductionKeys（"<caseId>:<installment>:R<n>"）
  人員 ID   ri_cases.owner_personnel_id、payload.ownerPersonnelId、payload.splitParties[].personnelId、
            payload.accountingNotifications[].accountingPersonnelId
  主檔 ID   ri_cases.class_master_id／reinsured_master_id／ae_master_id（payload 裡只存名稱，不存主檔 ID）
  操作者    各種 *_by 欄位與 payload.paymentEntries[].createdBy 的 "personnel:<id>"（其他格式的操作者原樣保留）
不需要對應：案件的 case_uid、文件 ID 與 storage_key、報表的 report_uid、排除紀錄的 id（都是 UUID）。

同一組函式也用在反方向（傳入「VM → Alpha」的對照表），匯入後把 VM 的資料轉回 Alpha 的 ID 與原始資料逐筆比對。
數字的型別保持不變：原本是數字就還是數字，原本是文字（例如 "12"）就還是文字。
"""
import copy
import re

_ACTOR = re.compile(r"personnel:([0-9]+)\Z")
_KEY = re.compile(r"([0-9]+)(:.*)\Z", re.S)
CASE_ACTOR_FIELDS = ("created_by", "updated_by", "announced_by", "archived_by", "recycled_by")


class RemapError(Exception):
    """來源資料引用了對照表裡沒有的 ID（例如指向不存在的案件或人員）。"""


class Maps:
    def __init__(self, cases=None, personnel=None, masters=None):
        self.cases = dict(cases or {})
        self.personnel = dict(personnel or {})
        self.masters = dict(masters or {})

    def inverse(self):
        return Maps({v: k for k, v in self.cases.items()}, {v: k for k, v in self.personnel.items()},
                    {v: k for k, v in self.masters.items()})


def _lookup(table, value, what):
    try:
        return table[int(value)]
    except (KeyError, ValueError, TypeError):
        raise RemapError(f"{what} {value!r} is not in the source data") from None


def map_id(table, value, what):
    """數字 ID：None 保持 None；int 回 int；像 "12" 的文字回文字；其他型別原樣（Alpha 的資料驗證不會寫出其他型別）。"""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return _lookup(table, value, what)
    if isinstance(value, float) and value.is_integer():
        return float(_lookup(table, value, what))
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return str(_lookup(table, value, what))
    return value


def map_actor(value, maps):
    if isinstance(value, str):
        m = _ACTOR.match(value)
        if m:
            return f"personnel:{_lookup(maps.personnel, m.group(1), 'actor personnel')}"
    return value


def map_key(value, maps):
    """"<caseId>:..." 的 key：開頭的案件 ID 換掉，其餘不變。"""
    if isinstance(value, str):
        m = _KEY.match(value)
        if m:
            return f"{_lookup(maps.cases, m.group(1), 'production key case')}{m.group(2)}"
    return value


def remap_payload(payload, maps):
    if not isinstance(payload, dict):
        return copy.deepcopy(payload)
    p = copy.deepcopy(payload)
    if "ownerPersonnelId" in p:
        p["ownerPersonnelId"] = map_id(maps.personnel, p["ownerPersonnelId"], "ownerPersonnelId")
    for party in p.get("splitParties") or [] if isinstance(p.get("splitParties"), list) else []:
        if isinstance(party, dict) and "personnelId" in party:
            party["personnelId"] = map_id(maps.personnel, party["personnelId"], "splitParties.personnelId")
    for note in p.get("accountingNotifications") or [] if isinstance(p.get("accountingNotifications"), list) else []:
        if isinstance(note, dict) and "accountingPersonnelId" in note:
            note["accountingPersonnelId"] = map_id(maps.personnel, note["accountingPersonnelId"], "accountingPersonnelId")
    if isinstance(p.get("confirmedProductionKeys"), list):
        p["confirmedProductionKeys"] = [map_key(k, maps) for k in p["confirmedProductionKeys"]]
    for entry in p.get("paymentEntries") or [] if isinstance(p.get("paymentEntries"), list) else []:
        if isinstance(entry, dict) and "createdBy" in entry:
            entry["createdBy"] = map_actor(entry["createdBy"], maps)
    return p


def remap_case(row, maps):
    """ri_cases 的一列（Alpha 的欄位名稱；也用於回收桶的 case_snapshot）。"""
    r = copy.deepcopy(row)
    if "id" in r:
        r["id"] = map_id(maps.cases, r["id"], "case id")
    if r.get("parent_case_id") is not None:
        r["parent_case_id"] = map_id(maps.cases, r["parent_case_id"], "parent_case_id")
    for col in ("class_master_id", "reinsured_master_id", "ae_master_id"):
        if r.get(col) is not None:
            r[col] = map_id(maps.masters, r[col], col)
    if r.get("owner_personnel_id") is not None:
        r["owner_personnel_id"] = map_id(maps.personnel, r["owner_personnel_id"], "owner_personnel_id")
    for col in CASE_ACTOR_FIELDS:
        if col in r:
            r[col] = map_actor(r[col], maps)
    if "payload" in r:
        r["payload"] = remap_payload(r["payload"], maps)
    return r


def remap_document(row, maps):
    r = copy.deepcopy(row)
    r["case_id"] = map_id(maps.cases, r["case_id"], "document case_id")
    r["uploaded_by"] = map_actor(r.get("uploaded_by"), maps)
    return r


def remap_recycle(row, maps):
    r = copy.deepcopy(row)
    r["original_case_id"] = map_id(maps.cases, r["original_case_id"], "original_case_id")
    for col in ("deleted_by", "restored_by", "permanently_deleted_by"):
        if col in r:
            r[col] = map_actor(r[col], maps)
    if isinstance(r.get("case_snapshot"), dict):
        r["case_snapshot"] = remap_case(r["case_snapshot"], maps)
    return r


def remap_exclusion(row, maps):
    r = copy.deepcopy(row)
    r["case_id"] = map_id(maps.cases, r["case_id"], "exclusion case_id")
    r["installment_key"] = map_key(r["installment_key"], maps)
    if r.get("reinsurer_key") is not None:
        r["reinsurer_key"] = map_key(r["reinsurer_key"], maps)
    return r


def remap_report_row(row, maps):
    if not isinstance(row, dict):
        return copy.deepcopy(row)
    r = copy.deepcopy(row)
    if "caseId" in r:
        r["caseId"] = map_id(maps.cases, r["caseId"], "report row caseId")
    for k in ("id", "key", "reinsurerKey"):
        if k in r:
            r[k] = map_key(r[k], maps)
    return r


def remap_report(row, maps):
    r = copy.deepcopy(row)
    r["rows"] = [remap_report_row(x, maps) for x in (r.get("rows") or [])]
    r["excluded_rows"] = [remap_report_row(x, maps) for x in (r.get("excluded_rows") or [])]
    return r


def remap_actor_row(row, maps, columns):
    r = copy.deepcopy(row)
    for col in columns:
        if col in r:
            r[col] = map_actor(r[col], maps)
    return r
