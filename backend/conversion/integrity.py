"""
匯入後的獨立完整性檢查（對帳第 5 項）。

為什麼要另外一份：對帳第 2 項「來回比對」用 remap.py 的同一組函式正反各做一次，
如果 remap.py 漏換了某個位置，正反兩次都漏，結果剛好互相抵消（2026-09-26 故意破壞測試發現：
排除紀錄的 installment_key、回收桶的 case_snapshot 沒換都沒被抓到）。

所以這裡刻意不用 remap.py、也不用匯入時建的對照表：
  - 對照自己重建：案件用 case_uid、人員用姓名、主檔用（類型、代碼、名稱）到 VM 的資料庫查。
  - ID 出現的位置自己列一份（下面的 *_FIELDS），逐一把「來源的值」換算成「應該是的 VM 值」，與 VM 實際的值比對。
  - 另外檢查每個引用都指向 VM 上存在的案件／人員／主檔。
  - --apply 時，每份文件的檔案本體都要在 VM 文件庫、大小與 SHA-256 與紀錄相同。
"""
import hashlib
import re

from cases import storage
from cases.models import Case, CaseDocument, DraftRecycleBin
from dashboard.models import DashboardTarget
from masterdata.models import MasterRecord
from personnel.models import Personnel
from production.models import ProductionExclusion, ProductionReport

_ACTOR_TEXT = re.compile(r"personnel:([0-9]+)\Z")
_CASE_KEY = re.compile(r"([0-9]+)(:.*)\Z", re.S)

CASE_MASTER_FIELDS = ("class_master_id", "reinsured_master_id", "ae_master_id")
CASE_ACTORS = ("created_by", "updated_by", "announced_by", "archived_by", "recycled_by")
DOCUMENT_ACTORS = ("uploaded_by",)
RECYCLE_ACTORS = ("deleted_by", "restored_by", "permanently_deleted_by")
TARGET_ACTORS = ("created_by", "updated_by", "deactivated_by")
REPORT_ROW_KEYS = ("id", "key", "reinsurerKey")


def _int(v):
    if isinstance(v, bool):
        raise ValueError(v)
    if isinstance(v, float):
        if not v.is_integer():
            raise ValueError(v)
        return int(v)
    return int(str(v))


class Checker:
    def __init__(self, tables, check_files):
        self.tables = tables
        self.check_files = check_files
        self.problems = []
        vm_case = {str(u): pk for u, pk in Case.objects.values_list("case_uid", "id")}
        self.case = {}
        for r in tables.get("ri_cases") or []:
            if str(r["case_uid"]) in vm_case:
                self.case[_int(r["id"])] = vm_case[str(r["case_uid"])]
        vm_people = {}
        for pk, name in Personnel.objects.values_list("id", "name"):
            vm_people.setdefault(name.lower(), []).append(pk)
        self.person = {}
        for r in tables.get("ri_personnel") or []:
            found = vm_people.get(str(r["name"]).lower()) or []
            if len(found) == 1:
                self.person[_int(r["id"])] = found[0]
        self.src_master = {_int(r["id"]): r for r in tables.get("ri_master_records") or []}
        self.vm_master = {m.pk: m for m in MasterRecord.objects.all()}
        self.vm_case_ids = set(vm_case.values())
        self.vm_person_ids = {pk for ids in vm_people.values() for pk in ids}

    def bad(self, where, msg):
        self.problems.append(f"integrity {where}: {msg}")

    # ---- 單一個值：來源 → 應有的 VM 值
    def _mapped(self, table, value, where, what):
        try:
            return table[_int(value)]
        except (KeyError, ValueError, TypeError):
            self.bad(where, f"{what} {value!r} has no VM counterpart")
            return None

    def expect_case_id(self, src, vm, where):
        if src is None:
            if vm is not None:
                self.bad(where, f"expected no case, VM has {vm!r}")
            return
        want = self._mapped(self.case, src, where, "case id")
        if want is not None and not self._same_number(vm, want):
            self.bad(where, f"case id is {vm!r}, expected VM case {want} (Alpha {src!r})")
        if vm is not None and self._as_int(vm) not in self.vm_case_ids:
            self.bad(where, f"case id {vm!r} does not exist on the VM")

    def expect_person_id(self, src, vm, where):
        if src is None or src == "":
            if vm != src:
                self.bad(where, f"expected {src!r}, VM has {vm!r}")
            return
        want = self._mapped(self.person, src, where, "personnel id")
        if want is not None and not self._same_number(vm, want):
            self.bad(where, f"personnel id is {vm!r}, expected VM personnel {want} (Alpha {src!r})")
        if vm is not None and self._as_int(vm) not in self.vm_person_ids:
            self.bad(where, f"personnel id {vm!r} does not exist on the VM")

    def expect_master_id(self, src, vm, where):
        if src is None:
            if vm is not None:
                self.bad(where, f"expected no master, VM has {vm!r}")
            return
        s = self.src_master.get(self._as_int(src))
        m = self.vm_master.get(self._as_int(vm))
        if s is None:
            self.bad(where, f"Alpha master {src!r} is not in the export")
        elif m is None:
            self.bad(where, f"master {vm!r} does not exist on the VM")
        elif (m.entity_type, (m.code or "").lower(), m.name.lower()) != (s["entity_type"], (s.get("code") or "").lower(), str(s["name"]).lower()):
            self.bad(where, f"master {vm!r} is {m.entity_type}:{m.code or m.name}, expected {s['entity_type']}:{s.get('code') or s['name']}")

    def expect_actor(self, src, vm, where):
        m = _ACTOR_TEXT.match(src) if isinstance(src, str) else None
        if not m:
            if vm != src:
                self.bad(where, f"actor is {vm!r}, expected unchanged {src!r}")
            return
        want = self._mapped(self.person, m.group(1), where, "actor personnel")
        if want is not None and vm != f"personnel:{want}":
            self.bad(where, f"actor is {vm!r}, expected 'personnel:{want}' (Alpha {src!r})")

    def expect_case_key(self, src, vm, where):
        m = _CASE_KEY.match(src) if isinstance(src, str) else None
        if not m:
            if vm != src:
                self.bad(where, f"key is {vm!r}, expected unchanged {src!r}")
            return
        want = self._mapped(self.case, m.group(1), where, "key case id")
        if want is not None and vm != f"{want}{m.group(2)}":
            self.bad(where, f"key is {vm!r}, expected '{want}{m.group(2)}' (Alpha {src!r})")

    @staticmethod
    def _as_int(v):
        try:
            return _int(v)
        except (ValueError, TypeError):
            return None

    @classmethod
    def _same_number(cls, vm, want):
        return vm is not None and cls._as_int(vm) == want

    # ---- 列
    def case_row(self, src, vm, where, snapshot=False):
        if snapshot:   # 回收桶的 case_snapshot 自己帶 id
            self.expect_case_id(src.get("id"), vm.get("id"), f"{where}.id")
        self.expect_case_id(src.get("parent_case_id"), vm.get("parent_case_id"), f"{where}.parent_case_id")
        for col in CASE_MASTER_FIELDS:
            self.expect_master_id(src.get(col), vm.get(col), f"{where}.{col}")
        self.expect_person_id(src.get("owner_personnel_id"), vm.get("owner_personnel_id"), f"{where}.owner_personnel_id")
        for col in CASE_ACTORS:
            if col in src or col in vm:
                self.expect_actor(src.get(col), vm.get(col), f"{where}.{col}")
        self.payload(src.get("payload"), vm.get("payload"), f"{where}.payload")

    def payload(self, src, vm, where):
        if not isinstance(src, dict):
            return
        if not isinstance(vm, dict):
            self.bad(where, "payload is not an object on the VM")
            return
        if "ownerPersonnelId" in src:
            self.expect_person_id(src["ownerPersonnelId"], vm.get("ownerPersonnelId"), f"{where}.ownerPersonnelId")
        for name, field, check in (("splitParties", "personnelId", self.expect_person_id),
                                   ("accountingNotifications", "accountingPersonnelId", self.expect_person_id),
                                   ("paymentEntries", "createdBy", self.expect_actor)):
            s_list, v_list = src.get(name), vm.get(name)
            if not isinstance(s_list, list):
                continue
            if not isinstance(v_list, list) or len(v_list) != len(s_list):
                self.bad(where, f"{name} length differs")
                continue
            for i, (s, v) in enumerate(zip(s_list, v_list)):
                if isinstance(s, dict) and field in s:
                    check(s[field], v.get(field) if isinstance(v, dict) else None, f"{where}.{name}[{i}].{field}")
        keys_s, keys_v = src.get("confirmedProductionKeys"), vm.get("confirmedProductionKeys")
        if isinstance(keys_s, list):
            if not isinstance(keys_v, list) or len(keys_v) != len(keys_s):
                self.bad(where, "confirmedProductionKeys length differs")
            else:
                for i, (s, v) in enumerate(zip(keys_s, keys_v)):
                    self.expect_case_key(s, v, f"{where}.confirmedProductionKeys[{i}]")

    def run(self, export_row):
        cases = {str(c.case_uid): c for c in Case.objects.all()}
        for r in self.tables.get("ri_cases") or []:
            c = cases.get(str(r["case_uid"]))
            if c is None:
                self.bad(f"case {r['case_uid']}", "not on the VM")
                continue
            self.case_row(r, export_row("ri_cases", c), f"case {r['case_uid']}")

        docs = {str(d.pk): d for d in CaseDocument.objects.all()}
        for r in self.tables.get("ri_case_documents") or []:
            d = docs.get(str(r["id"]))
            where = f"document {r['id']}"
            if d is None:
                self.bad(where, "not on the VM")
                continue
            self.expect_case_id(r["case_id"], d.case_id, f"{where}.case_id")
            for col in DOCUMENT_ACTORS:
                self.expect_actor(r.get(col), getattr(d, col), f"{where}.{col}")
            if self.check_files:
                self.file(d, where)

        recycle = {}
        for item in DraftRecycleBin.objects.all():
            recycle.setdefault((item.original_case_id, item.original_case_version), []).append(item)
        for r in self.tables.get("ri_draft_recycle_bin") or []:
            where = f"recycle case {r['original_case_id']} v{r['original_case_version']}"
            want = self._mapped(self.case, r["original_case_id"], where, "original_case_id")
            found = recycle.get((want, self._as_int(r["original_case_version"]))) or []
            if len(found) != 1:
                self.bad(where, f"expected 1 VM row for VM case {want}, found {len(found)}")
                continue
            vm = export_row("ri_draft_recycle_bin", found[0])
            self.expect_case_id(r["original_case_id"], vm["original_case_id"], f"{where}.original_case_id")
            for col in RECYCLE_ACTORS:
                self.expect_actor(r.get(col), vm.get(col), f"{where}.{col}")
            snap_s, snap_v = r.get("case_snapshot"), vm.get("case_snapshot")
            if isinstance(snap_s, dict):
                if not isinstance(snap_v, dict):
                    self.bad(where, "case_snapshot is not an object on the VM")
                else:
                    self.case_row(snap_s, snap_v, f"{where}.case_snapshot", snapshot=True)
                    if self._as_int(snap_v.get("id")) != vm["original_case_id"]:
                        self.bad(where, f"case_snapshot.id {snap_v.get('id')!r} is not original_case_id {vm['original_case_id']}")

        excl = {str(e.pk): e for e in ProductionExclusion.objects.all()}
        for r in self.tables.get("ri_production_exclusions") or []:
            e = excl.get(str(r["id"]))
            where = f"exclusion {r['id']}"
            if e is None:
                self.bad(where, "not on the VM")
                continue
            self.expect_case_id(r["case_id"], e.case_id, f"{where}.case_id")
            self.expect_case_key(r["installment_key"], e.installment_key, f"{where}.installment_key")
            self.expect_case_key(r.get("reinsurer_key"), e.reinsurer_key, f"{where}.reinsurer_key")
            for key in (e.installment_key, e.reinsurer_key):   # key 開頭必須就是這筆排除的案件
                m = _CASE_KEY.match(key or "")
                if key is not None and (not m or int(m.group(1)) != e.case_id):
                    self.bad(where, f"key {key!r} does not start with its case id {e.case_id}")

        reports = {str(p.report_uid): p for p in ProductionReport.objects.all()}
        for r in self.tables.get("ri_production_reports") or []:
            p = reports.get(str(r["report_uid"]))
            where = f"report {r['report_uid']}"
            if p is None:
                self.bad(where, "not on the VM")
                continue
            for col in ("rows", "excluded_rows"):
                s_rows, v_rows = r.get(col) or [], getattr(p, col) or []
                if len(s_rows) != len(v_rows):
                    self.bad(where, f"{col} length differs")
                    continue
                for i, (s, v) in enumerate(zip(s_rows, v_rows)):
                    if not isinstance(s, dict):
                        continue
                    w = f"{where}.{col}[{i}]"
                    if "caseId" in s:
                        self.expect_case_id(s["caseId"], v.get("caseId"), f"{w}.caseId")
                    for k in REPORT_ROW_KEYS:
                        if k in s:
                            self.expect_case_key(s[k], v.get(k), f"{w}.{k}")

        targets = {(t.period_type, t.period_key): t for t in DashboardTarget.objects.all()}
        for r in self.tables.get("ri_dashboard_targets") or []:
            t = targets.get((r["period_type"], r["period_key"]))
            if t is not None:
                for col in TARGET_ACTORS:
                    self.expect_actor(r.get(col), getattr(t, col), f"target {r['period_type']}:{r['period_key']}.{col}")
        return self.problems

    def file(self, d, where):
        if not storage.exists(d.storage_key):
            self.bad(where, f"file {d.storage_key} is not in the VM document store")
            return
        h, n = hashlib.sha256(), 0
        with storage.open_read(d.storage_key) as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                n += len(chunk)
        if n != d.byte_size or h.hexdigest() != d.sha256:
            self.bad(where, f"stored file size/SHA-256 ({n}, {h.hexdigest()[:12]}…) does not match the record")


def check(tables, check_files, export_row):
    return Checker(tables, check_files).run(export_row)
