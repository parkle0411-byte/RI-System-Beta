"""
Alpha → VM 切換時的資料轉換（2026-09-26 的決定）：
  - VM 重新編號，Alpha 的數字 ID 全部依對照表換成 VM 的 ID（remap.py 列出所有位置）。
  - 主檔、人員、匯率：用自然鍵對到 VM 現有的那一筆（主檔：類型＋代碼，沒有代碼用名稱；人員：姓名；匯率：月份＋幣別）。
    對到了但內容不同 → 整批停止，列出所有差異；對不到 → 新增。
  - 案件、文件、回收桶、Production、目標、流水號：VM 端必須是空的（測試資料在切換前先清掉），否則拒絕。
  - 帳號不搬（切換後重新建立）；人員的 email 不搬（沿用第一次匯入的規則）；Audit／Snapshot 歷史不搬，
    每筆匯入的資料在 VM 寫一份 Snapshot 與一筆 Audit（source = data_migration），歷史從轉換事件開始。
  - VM 還沒有的表（ri_payment_alerts、ri_signed_slip_alerts）：原始內容存在轉換批次的 item，之後依對照表匯入。
  - 預設 dry-run：全部在一個交易裡做完、對帳，然後回滾（只留下一筆 status = dry_run 的批次摘要）。
    --apply 才提交；任何一項對帳不符 → 整批回滾，已寫出的文件檔案也刪除。

對帳：
  1. 筆數：每張表來源筆數 = 匯入筆數（主檔／人員／匯率 = 對到的 + 新增的）
  2. 來回比對：匯入的每一筆轉回 Alpha 的 ID 與欄位後，內容必須與來源完全相同（canonical 之後比雜湊）
  3. 參照完整性（同 Alpha data-reconciliation.js 的檢查）
  4. 財務控制總數：各幣別的原始保費、交易筆數與金額、未結／已結筆數；文件總位元組；報表各狀態筆數
  5. 獨立完整性檢查（integrity.py）：不用 remap.py，自己用 case_uid／姓名／主檔自然鍵重建對照，逐一檢查每個 ID 位置、
     引用是否存在；--apply 時再檢查每份文件的檔案本體（大小、SHA-256）。補第 2 項「正反用同一組函式、漏換會互相抵消」的盲點
"""
import hashlib
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit, record_snapshot
from cases import storage
from cases.models import Case, CaseDocument, DraftRecycleBin, ReferenceSequence
from dashboard.models import DashboardTarget
from fxrates.models import FxRate
from masterdata.models import MasterRecord
from personnel.models import Personnel
from production.calc import production_source_signature
from production.models import ProductionExclusion, ProductionReport

from . import integrity, remap as rm
from .alpha_format import COLUMNS, PERSONNEL_SKIPPED, canonical, export_model_row, parse_time, row_hash, source_hash
from .models import MigrationBatch, MigrationItem

ACTOR = {"id": "alpha-cutover", "name": "Alpha cutover import", "role": "system"}
EMPTY_REQUIRED = {"ri_cases": Case, "ri_case_documents": CaseDocument, "ri_draft_recycle_bin": DraftRecycleBin,
                  "ri_production_reports": ProductionReport, "ri_production_exclusions": ProductionExclusion,
                  "ri_dashboard_targets": DashboardTarget, "ri_reference_sequences": ReferenceSequence}
DEFERRED_TABLES = ("ri_payment_alerts", "ri_signed_slip_alerts")
MASTER_FIELDS = ("entity_type", "code", "name", "display_order", "is_active", "payload")
PERSONNEL_FIELDS = ("name", "department", "role_code", "is_active", "is_split_eligible", "supervisor_name")
FX_FIELDS = ("year_month", "currency", "rate", "is_locked")


class ConversionError(Exception):
    def __init__(self, code, problems):
        super().__init__(code)
        self.code = code
        self.problems = problems


class _Rollback(Exception):
    pass


def _key(v):
    return str(v)


def _t(v):
    return parse_time(v)


def _num(value):
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _is_numeric_text(value):
    try:
        Decimal(str(value))
        return not isinstance(value, bool) and str(value).strip() != ""
    except InvalidOperation:
        return False


def control_totals(case_rows, doc_rows, report_rows):
    """Alpha data-reconciliation.js 的控制總數（對來源與目標各算一次，必須相同）。"""
    premium, tx = {}, {}
    for c in case_rows:
        cur = c.get("currency") or ""
        p = c.get("payload") if isinstance(c.get("payload"), dict) else {}
        entry = premium.setdefault(cur, {"caseCount": 0, "originalPremium": Decimal(0)})
        entry["caseCount"] += 1
        if _is_numeric_text(p.get("originalPremium")):
            entry["originalPremium"] += _num(p.get("originalPremium"))
        t = tx.setdefault(cur, {"transactionCount": 0, "transactionAmount": Decimal(0), "openCount": 0, "settledCount": 0})
        for item in p.get("transactions") or [] if isinstance(p.get("transactions"), list) else []:
            t["transactionCount"] += 1
            if isinstance(item, dict):
                if _is_numeric_text(item.get("amount")):
                    t["transactionAmount"] += _num(item.get("amount"))
                t["openCount"] += item.get("settlement") == "open"
                t["settledCount"] += item.get("settlement") == "settled"
    fmt = lambda d: {k: {kk: (format(vv.normalize(), "f") if isinstance(vv, Decimal) else vv) for kk, vv in v.items()} for k, v in sorted(d.items())}
    return {
        "premium": fmt(premium), "transactions": fmt(tx),
        "documentCount": len(doc_rows), "documentBytes": sum(int(d.get("byte_size") or 0) for d in doc_rows),
        "reportStatus": dict(sorted(Counter(r.get("status") for r in report_rows).items())),
    }


class Importer:
    def __init__(self, export, files_dir=None, apply=False, stdout=None):
        self.export = export
        self.tables = export.get("tables") or {}
        self.files_dir = Path(files_dir) if files_dir else None
        self.apply = apply
        self.maps = rm.Maps()
        self.items = []          # (entity_type, source_key, target_table, target_key, hash, status, issue, source_summary)
        self.written_files = []
        self.report = {"mode": "APPLY" if apply else "DRY-RUN", "created": Counter(), "matched": Counter(), "deferred": Counter()}
        self.now = timezone.now()

    # ------------------------------------------------------------ 入口
    def run(self):
        self._validate()
        self._require_empty()
        self.src_hash = source_hash(self.export)
        try:
            with transaction.atomic():
                self.batch = MigrationBatch.objects.create(
                    source_system=str((self.export.get("source") or {}).get("system") or "hatchable-alpha"),
                    source_version=str((self.export.get("source") or {}).get("version") or "") or None,
                    source_hash=self.src_hash, status="dry_run", created_by=ACTOR["id"],
                    source_counts={t: len(rows) for t, rows in self.tables.items()})
                self._reference_data()
                self._cases()
                self._documents()
                self._recycle()
                self._production()
                self._targets_and_sequences()
                self._deferred()
                self._reconcile()
                self._write_items_and_events()
                if not self.apply:
                    raise _Rollback()
                self.batch.status = "completed"
                self.batch.completed_at = timezone.now()
                self.batch.approved_by = ACTOR["id"]
                self.batch.approved_at = self.batch.completed_at
                self.batch.save()
        except _Rollback:
            self._dry_run_summary()
        except Exception:
            for key in self.written_files:
                storage.delete(key)
            raise
        self.report["batchUid"] = str(self.batch.batch_uid) if self.apply else self.report.get("batchUid")
        return self.report

    # ------------------------------------------------------------ 前置檢查
    def _validate(self):
        problems = []
        for table, rows in self.tables.items():
            if table not in COLUMNS:
                problems.append(f"unknown table {table}")
                continue
            if not isinstance(rows, list):
                problems.append(f"{table} is not a list")
                continue
            cols = COLUMNS[table]
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    problems.append(f"{table}[{i}] is not an object")
                elif cols is not None and set(cols) - set(row):
                    problems.append(f"{table}[{i}] is missing {sorted(set(cols) - set(row))}")
        for table in ("ri_master_records", "ri_personnel", "ri_fx_rates", "ri_cases"):
            if table not in self.tables:
                problems.append(f"export has no {table}")
        if problems:
            raise ConversionError("invalid_export", problems)

    def _require_empty(self):
        counts = {t: m.objects.count() for t, m in EMPTY_REQUIRED.items()}
        busy = {t: n for t, n in counts.items() if n}
        if busy:
            raise ConversionError("target_not_empty", [f"{t} has {n} row(s); clear the VM test data first" for t, n in busy.items()])

    def _rows(self, table):
        return self.tables.get(table) or []

    def _item(self, entity, source_key, table, target_key, row, status="converted", issue=None, summary=None, skip=()):
        self.items.append([entity, _key(source_key), table, _key(target_key) if target_key is not None else None,
                           row_hash(entity, row, skip), status, issue, summary or {}])

    # ------------------------------------------------------------ 主檔／人員／匯率
    def _match_or_create(self, table, rows, find, fields, create, what, skip=()):
        conflicts = []
        for row in rows:
            existing = find(row)
            if existing is not None:
                mine = canonical(table, export_model_row(table, existing), skip)
                theirs = canonical(table, row, skip)
                diff = [f for f in fields if mine.get(f) != theirs.get(f)]
                if diff:
                    conflicts.append({"table": table, "alphaId": row["id"], "vmId": existing.pk, "match": what(row),
                                      "fields": {f: {"alpha": theirs.get(f), "vm": mine.get(f)} for f in diff}})
                    continue
                self.report["matched"][table] += 1
                yield row, existing, False
            else:
                obj = create(row)
                self.report["created"][table] += 1
                yield row, obj, True
        if conflicts:
            raise ConversionError("reference_conflict", conflicts)

    def _reference_data(self):
        def find_master(r):
            qs = MasterRecord.objects.filter(entity_type=r["entity_type"])
            cands = list(qs.filter(code__iexact=r["code"])) if r.get("code") else list(qs.filter(name__iexact=r["name"]))
            if not r.get("code"):
                cands = [c for c in cands if not c.code] or cands
            exact = [c for c in cands if (c.code if r.get("code") else c.name).lower() == (r["code"] if r.get("code") else r["name"]).lower()]
            if len(exact) > 1:
                raise ConversionError("ambiguous_match", [f"master {r['entity_type']} {r.get('code') or r['name']} matches {len(exact)} VM rows"])
            return exact[0] if exact else None

        def create_master(r):
            obj = MasterRecord.objects.create(
                entity_type=r["entity_type"], code=r.get("code") or None, name=r["name"], display_order=r["display_order"],
                is_active=r["is_active"], payload=r.get("payload") or {}, row_version=r["row_version"],
                created_by=r["created_by"], updated_by=r["updated_by"], deactivated_by=r.get("deactivated_by"),
                deactivated_at=_t(r.get("deactivated_at")))
            MasterRecord.objects.filter(pk=obj.pk).update(created_at=_t(r["created_at"]), updated_at=_t(r["updated_at"]))
            return obj

        masters = list(self._match_or_create("ri_master_records", self._rows("ri_master_records"), find_master, MASTER_FIELDS,
                                             create_master, lambda r: f"{r['entity_type']}:{r.get('code') or r['name']}"))

        def find_person(r):
            exact = [p for p in Personnel.objects.filter(name__iexact=r["name"]) if p.name.lower() == r["name"].lower()]
            if len(exact) > 1:
                raise ConversionError("ambiguous_match", [f"personnel {r['name']} matches {len(exact)} VM rows"])
            return exact[0] if exact else None

        def create_person(r):
            obj = Personnel.objects.create(
                name=r["name"], email=None, department=r["department"], role_code=r["role_code"], is_active=r["is_active"],
                is_split_eligible=r["is_split_eligible"], account_status="not_configured", supervisor_name=r.get("supervisor_name"),
                supervisor_email=None, row_version=r["row_version"], created_by=r["created_by"], updated_by=r["updated_by"],
                deactivated_by=r.get("deactivated_by"), deactivated_at=_t(r.get("deactivated_at")))
            Personnel.objects.filter(pk=obj.pk).update(created_at=_t(r["created_at"]), updated_at=_t(r["updated_at"]))
            return obj

        people = list(self._match_or_create("ri_personnel", self._rows("ri_personnel"), find_person, PERSONNEL_FIELDS,
                                            create_person, lambda r: r["name"], skip=PERSONNEL_SKIPPED))

        def find_fx(r):
            return FxRate.objects.filter(year_month=r["year_month"], currency=r["currency"]).first()

        def create_fx(r):
            obj = FxRate.objects.create(
                year_month=r["year_month"], currency=r["currency"], rate=Decimal(str(r["rate"])), row_version=r["row_version"],
                is_locked=r["is_locked"], locked_by=r.get("locked_by"), locked_at=_t(r.get("locked_at")), lock_reason=r.get("lock_reason"),
                created_by=r["created_by"], updated_by=r["updated_by"])
            FxRate.objects.filter(pk=obj.pk).update(created_at=_t(r["created_at"]), updated_at=_t(r["updated_at"]))
            return obj

        fxs = list(self._match_or_create("ri_fx_rates", self._rows("ri_fx_rates"), find_fx, FX_FIELDS, create_fx,
                                         lambda r: f"{r['year_month']} {r['currency']}"))

        self.maps.masters = {int(r["id"]): o.pk for r, o, _ in masters}
        self.maps.personnel = {int(r["id"]): o.pk for r, o, _ in people}
        self.reference = {"ri_master_records": masters, "ri_personnel": people, "ri_fx_rates": fxs}
        for table, entries in self.reference.items():
            for r, o, created in entries:
                self._item(table, r["id"], table, o.pk, r, summary={"created": created},
                           skip=PERSONNEL_SKIPPED if table == "ri_personnel" else ())
        # 操作者欄位（"personnel:<id>"）在新增的主檔／人員／匯率上也要換
        for table, cols in (("ri_master_records", ("created_by", "updated_by", "deactivated_by")),
                            ("ri_personnel", ("created_by", "updated_by", "deactivated_by")),
                            ("ri_fx_rates", ("created_by", "updated_by", "locked_by"))):
            for r, o, created in self.reference[table]:
                if created:
                    mapped = rm.remap_actor_row(r, self.maps, cols)
                    type(o).objects.filter(pk=o.pk).update(**{c: mapped.get(c) for c in cols})

    # ------------------------------------------------------------ 案件
    def _cases(self):
        rows = sorted(self._rows("ri_cases"), key=lambda r: (r.get("parent_case_id") is not None, int(r["id"])))
        ids = {int(r["id"]) for r in rows}
        missing = [r["id"] for r in rows if r.get("parent_case_id") is not None and int(r["parent_case_id"]) not in ids]
        if missing:
            raise ConversionError("orphan_endorsement", [f"case {i} points to a parent that is not in the export" for i in missing])
        self.case_objs = []
        for r in rows:
            m = rm.remap_case({k: v for k, v in r.items() if k not in ("id", "payload")}, self.maps)
            obj = Case.objects.create(
                case_uid=r["case_uid"], legacy_case_id=r.get("legacy_case_id"),
                parent_case_id=m.get("parent_case_id"),
                tw_ref=r.get("tw_ref"), case_kind=r["case_kind"], status=r["status"], reinsurance_structure=r.get("reinsurance_structure"),
                class_master_id=m.get("class_master_id"), class_code_snapshot=r.get("class_code_snapshot"),
                class_name_snapshot=r.get("class_name_snapshot"), reinsured_master_id=m.get("reinsured_master_id"),
                reinsured_name_snapshot=r.get("reinsured_name_snapshot"), ae_master_id=m.get("ae_master_id"),
                ae_name_snapshot=r.get("ae_name_snapshot"), owner_personnel_id=m.get("owner_personnel_id"),
                currency=r.get("currency"), effective_date=r.get("effective_date"), expiration_date=r.get("expiration_date"),
                payload={}, row_version=r["row_version"], is_archived=r["is_archived"], archived_by=m.get("archived_by"),
                archived_at=_t(r.get("archived_at")), recycled_by=m.get("recycled_by"), recycled_at=_t(r.get("recycled_at")),
                announced_by=m.get("announced_by"), announced_at=_t(r.get("announced_at")),
                created_by=m["created_by"], updated_by=m["updated_by"])
            self.maps.cases[int(r["id"])] = obj.pk
            self.case_objs.append((r, obj))
        for r, obj in self.case_objs:   # 全部案件都有 VM ID 之後，才能換 payload 裡的案件 key
            Case.objects.filter(pk=obj.pk).update(payload=rm.remap_payload(r.get("payload"), self.maps),
                                                  created_at=_t(r["created_at"]), updated_at=_t(r["updated_at"]))
            self._item("ri_cases", r["id"], "ri_cases", obj.pk, r, summary={"caseUid": str(r["case_uid"]), "twRef": r.get("tw_ref")})
        self.report["created"]["ri_cases"] = len(rows)

    def _documents(self):
        problems = []
        for r in self._rows("ri_case_documents"):
            data = self._file(r, problems)
            if data is None:
                continue
            m = rm.remap_document(r, self.maps)
            CaseDocument.objects.create(
                id=r["id"], case_id=m["case_id"], kind=r["kind"], reinsurers=r.get("reinsurers") or [], filename=r["filename"],
                content_type=r["content_type"], byte_size=int(r["byte_size"]), sha256=r["sha256"], storage_key=r["storage_key"],
                is_selected=r["is_selected"], uploaded_by=m.get("uploaded_by"))
            CaseDocument.objects.filter(pk=r["id"]).update(uploaded_at=_t(r["uploaded_at"]))
            if self.apply:
                if storage.exists(r["storage_key"]):
                    problems.append(f"document {r['id']}: {r['storage_key']} already exists in the VM document store")
                    continue
                storage.put(r["storage_key"], data)
                self.written_files.append(r["storage_key"])
            self._item("ri_case_documents", r["id"], "ri_case_documents", r["id"], r, summary={"storageKey": r["storage_key"]})
        if problems:
            raise ConversionError("document_problem", problems)
        self.report["created"]["ri_case_documents"] = len(self._rows("ri_case_documents"))

    def _file(self, r, problems):
        if self.files_dir is None:
            problems.append("document files directory was not given")
            return None
        path = (self.files_dir / r["storage_key"]).resolve()
        if self.files_dir.resolve() not in path.parents or not path.is_file():
            problems.append(f"document {r['id']}: file {r['storage_key']} is missing from the export")
            return None
        data = path.read_bytes()
        if len(data) != int(r["byte_size"]) or hashlib.sha256(data).hexdigest() != r["sha256"]:
            problems.append(f"document {r['id']}: size or SHA-256 does not match")
            return None
        return data

    def _recycle(self):
        for r in self._rows("ri_draft_recycle_bin"):
            m = rm.remap_recycle(r, self.maps)
            obj = DraftRecycleBin.objects.create(
                original_case_id=m["original_case_id"], original_case_version=r["original_case_version"],
                case_snapshot=m["case_snapshot"], deleted_by=m["deleted_by"], deleted_at=_t(r["deleted_at"]),
                restore_deadline=_t(r["restore_deadline"]), restored_by=m.get("restored_by"), restored_at=_t(r.get("restored_at")),
                permanently_deleted_by=m.get("permanently_deleted_by"), permanently_deleted_at=_t(r.get("permanently_deleted_at")))
            self._item("ri_draft_recycle_bin", r["id"], "ri_draft_recycle_bin", obj.pk, r, skip=("id",))
        self.report["created"]["ri_draft_recycle_bin"] = len(self._rows("ri_draft_recycle_bin"))

    def _production(self):
        for r in self._rows("ri_production_exclusions"):
            m = rm.remap_exclusion(r, self.maps)
            ProductionExclusion.objects.create(
                id=r["id"], case_id=m["case_id"], year_month=r["year_month"], scope=r["scope"], installment_key=m["installment_key"],
                reinsurer_key=m.get("reinsurer_key"), deferred_to=r["deferred_to"], reason=r["reason"], created_by=r["created_by"])
            ProductionExclusion.objects.filter(pk=r["id"]).update(created_at=_t(r["created_at"]))
            self._item("ri_production_exclusions", r["id"], "ri_production_exclusions", r["id"], r)
        self.signature_issues = []
        for r in self._rows("ri_production_reports"):
            if production_source_signature(r.get("rows") or []) != r["source_signature"]:
                self.signature_issues.append(str(r["report_uid"]))
            m = rm.remap_report(r, self.maps)
            obj = ProductionReport.objects.create(
                report_uid=r["report_uid"], year_month=r["year_month"], version=r["version"], status=r["status"], rows=m["rows"],
                excluded_rows=m["excluded_rows"], source_signature=production_source_signature(m["rows"]), row_version=r["row_version"],
                close_token=r.get("close_token"), created_by=r["created_by"], closed_by=r.get("closed_by"), closed_at=_t(r.get("closed_at")))
            ProductionReport.objects.filter(pk=obj.pk).update(created_at=_t(r["created_at"]))
            issue = "source signature does not match its rows in Alpha" if str(r["report_uid"]) in self.signature_issues else None
            self._item("ri_production_reports", r["report_uid"], "ri_production_reports", obj.pk, r, issue=issue, skip=("id",))
        for t in ("ri_production_exclusions", "ri_production_reports"):
            self.report["created"][t] = len(self._rows(t))

    def _targets_and_sequences(self):
        for r in self._rows("ri_dashboard_targets"):
            m = rm.remap_actor_row(r, self.maps, ("created_by", "updated_by", "deactivated_by"))
            obj = DashboardTarget.objects.create(
                period_type=r["period_type"], period_key=r["period_key"], amount=Decimal(str(r["amount"])), is_active=r["is_active"],
                row_version=r["row_version"], created_by=m["created_by"], updated_by=m["updated_by"],
                deactivated_by=m.get("deactivated_by"), deactivated_at=_t(r.get("deactivated_at")))
            DashboardTarget.objects.filter(pk=obj.pk).update(created_at=_t(r["created_at"]), updated_at=_t(r["updated_at"]))
            self._item("ri_dashboard_targets", r["id"], "ri_dashboard_targets", obj.pk, r, skip=("id",))
        for r in self._rows("ri_reference_sequences"):
            ReferenceSequence.objects.create(prefix=r["prefix"], last_value=int(r["last_value"]))
            ReferenceSequence.objects.filter(prefix=r["prefix"]).update(updated_at=_t(r["updated_at"]))
            self._item("ri_reference_sequences", r["prefix"], "ri_reference_sequences", r["prefix"], r)
        for t in ("ri_dashboard_targets", "ri_reference_sequences"):
            self.report["created"][t] = len(self._rows(t))

    def _deferred(self):
        for table in DEFERRED_TABLES:
            for r in self._rows(table):
                case_id = r.get("case_id")
                vm_case = self.maps.cases.get(int(case_id)) if str(case_id).isdigit() else None
                self._item(table, r.get("id"), None, None, r, status="excluded",
                           issue="table not yet on the VM (reminders not migrated); import later using this batch's case map",
                           summary={"row": r, "vmCaseId": vm_case})
                self.report["deferred"][table] += 1

    # ------------------------------------------------------------ 對帳
    def _reconcile(self):
        problems = []
        inv = self.maps.inverse()
        # 1. 筆數
        target = {
            "ri_master_records": len(self.reference["ri_master_records"]), "ri_personnel": len(self.reference["ri_personnel"]),
            "ri_fx_rates": len(self.reference["ri_fx_rates"]), "ri_cases": Case.objects.count(),
            "ri_case_documents": CaseDocument.objects.count(), "ri_draft_recycle_bin": DraftRecycleBin.objects.count(),
            "ri_production_reports": ProductionReport.objects.count(), "ri_production_exclusions": ProductionExclusion.objects.count(),
            "ri_dashboard_targets": DashboardTarget.objects.count(), "ri_reference_sequences": ReferenceSequence.objects.count(),
        }
        for t, n in target.items():
            if n != len(self._rows(t)):
                problems.append(f"count {t}: source {len(self._rows(t))}, VM {n}")
        # 2. 來回比對（VM 的資料轉回 Alpha 的 ID 後，必須與來源相同）
        def compare(table, source_rows, vm_rows_by_key, key, back, skip=()):
            for r in source_rows:
                vm = vm_rows_by_key.get(key(r))
                if vm is None:
                    problems.append(f"{table} {key(r)}: not found on the VM")
                    continue
                if row_hash(table, back(export_model_row(table, vm)), skip) != row_hash(table, r, skip):
                    a, b = canonical(table, r, skip), canonical(table, back(export_model_row(table, vm)), skip)
                    problems.append(f"{table} {key(r)}: content differs in {sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))}")
        cases_by_uid = {str(c.case_uid): c for c in Case.objects.all()}
        compare("ri_cases", self._rows("ri_cases"), cases_by_uid, lambda r: str(r["case_uid"]), lambda x: rm.remap_case(x, inv))
        compare("ri_case_documents", self._rows("ri_case_documents"), {str(d.pk): d for d in CaseDocument.objects.all()},
                lambda r: str(r["id"]), lambda x: rm.remap_document(x, inv))
        recycle_by_case = {}
        for item in DraftRecycleBin.objects.all():
            recycle_by_case.setdefault(item.original_case_id, []).append(item)
        compare("ri_draft_recycle_bin", self._rows("ri_draft_recycle_bin"),
                {f"{inv.cases[k]}:{i.original_case_version}": i for k, v in recycle_by_case.items() for i in v},
                lambda r: f"{int(r['original_case_id'])}:{r['original_case_version']}", lambda x: rm.remap_recycle(x, inv), skip=("id",))
        compare("ri_production_exclusions", self._rows("ri_production_exclusions"),
                {str(e.pk): e for e in ProductionExclusion.objects.all()}, lambda r: str(r["id"]), lambda x: rm.remap_exclusion(x, inv))

        def report_back(x):
            y = rm.remap_report(x, inv)
            y["source_signature"] = production_source_signature(y["rows"])
            return y
        good_reports = [r for r in self._rows("ri_production_reports") if str(r["report_uid"]) not in self.signature_issues]
        compare("ri_production_reports", good_reports, {str(p.report_uid): p for p in ProductionReport.objects.all()},
                lambda r: str(r["report_uid"]), report_back, skip=("id",))
        compare("ri_dashboard_targets", self._rows("ri_dashboard_targets"),
                {f"{t.period_type}:{t.period_key}": t for t in DashboardTarget.objects.all()}, lambda r: f"{r['period_type']}:{r['period_key']}",
                lambda x: rm.remap_actor_row(x, inv, ("created_by", "updated_by", "deactivated_by")), skip=("id",))
        compare("ri_reference_sequences", self._rows("ri_reference_sequences"),
                {s.prefix: s for s in ReferenceSequence.objects.all()}, lambda r: r["prefix"], lambda x: x)
        for table, cols in (("ri_master_records", ("created_by", "updated_by", "deactivated_by")),
                            ("ri_personnel", ("created_by", "updated_by", "deactivated_by")),
                            ("ri_fx_rates", ("created_by", "updated_by", "locked_by"))):
            created = [(r, o) for r, o, c in self.reference[table] if c]
            skip = ("id",) + (tuple(PERSONNEL_SKIPPED) if table == "ri_personnel" else ())
            compare(table, [r for r, _ in created], {str(r["id"]): type(o).objects.get(pk=o.pk) for r, o in created},
                    lambda r: str(r["id"]), lambda x, c=cols: rm.remap_actor_row(x, inv, c), skip=skip)
        # 3. 參照完整性
        tw = Counter((c.tw_ref or "").strip().lower() for c in Case.objects.filter(recycled_at__isnull=True, is_archived=False) if (c.tw_ref or "").strip())
        problems += [f"duplicate TW Ref {k}" for k, n in tw.items() if n > 1]
        problems += [f"locked case {c.case_uid} has no TW Ref" for c in Case.objects.filter(status__in=("posted", "closed", "reversed"),
                     recycled_at__isnull=True, is_archived=False) if not (c.tw_ref or "").strip()]
        problems += [f"nested endorsement {c.case_uid}" for c in Case.objects.filter(parent_case__isnull=False, parent_case__parent_case__isnull=False)]
        # 4. 財務控制總數（來源與 VM 各算一次）
        source_totals = control_totals(self._rows("ri_cases"), self._rows("ri_case_documents"), self._rows("ri_production_reports"))
        vm_totals = control_totals([export_model_row("ri_cases", c) for c in Case.objects.all()],
                                   [export_model_row("ri_case_documents", d) for d in CaseDocument.objects.all()],
                                   [export_model_row("ri_production_reports", p) for p in ProductionReport.objects.all()])
        if source_totals != vm_totals:
            problems.append(f"control totals differ: source {source_totals} VM {vm_totals}")
        # 5. 獨立完整性檢查（不經 remap.py；--apply 時檔案已寫入文件庫，一併檢查）
        problems += integrity.check(self.tables, check_files=self.apply, export_row=export_model_row)
        self.report.update(sourceCounts={t: len(v) for t, v in self.tables.items()}, targetCounts=target, controlTotals=source_totals,
                           signatureIssues=self.signature_issues)
        self.batch.target_counts = target
        self.batch.control_totals = source_totals
        if problems:
            raise ConversionError("reconciliation_failed", problems)
        for it in self.items:
            if it[5] == "converted" and not it[6]:
                it[5] = "reconciled"

    # ------------------------------------------------------------ 紀錄
    def _write_items_and_events(self):
        MigrationItem.objects.bulk_create([
            MigrationItem(batch=self.batch, entity_type=e, source_key=s, target_table=t, target_key=k, source_hash=h,
                          status=st, issue=iss, source_summary=summ, target_summary={})
            for e, s, t, k, h, st, iss, summ in self.items])
        meta = {"batchUid": str(self.batch.batch_uid), "sourceHash": self.src_hash}
        for r, obj in self.case_objs:
            obj.refresh_from_db()
            data = export_model_row("ri_cases", obj)
            record_snapshot(entity_type="case", entity_id=obj.case_uid, version=obj.row_version, reason="alpha_cutover_import",
                            data=data, created_by=ACTOR["id"])
            record_audit(entity_type="case", entity_id=obj.case_uid, action="import_alpha_record", before=None, after=data,
                         actor=ACTOR, source="data_migration", metadata={**meta, "alphaId": r["id"]})
        for table in ("ri_master_records", "ri_personnel", "ri_fx_rates"):
            for r, obj, created in self.reference[table]:
                if created:
                    obj.refresh_from_db()
                    data = export_model_row(table, obj)
                    entity = {"ri_master_records": "master_record", "ri_personnel": "personnel", "ri_fx_rates": "fx_rate"}[table]
                    record_snapshot(entity_type=entity, entity_id=obj.pk, version=obj.row_version, reason="alpha_cutover_import",
                                    data=data, created_by=ACTOR["id"])
                    record_audit(entity_type=entity, entity_id=obj.pk, action="import_alpha_record", before=None, after=data,
                                 actor=ACTOR, source="data_migration", metadata={**meta, "alphaId": r["id"]})
        for obj in DashboardTarget.objects.all():
            data = export_model_row("ri_dashboard_targets", obj)
            record_snapshot(entity_type="dashboard_target", entity_id=obj.pk, version=obj.row_version, reason="alpha_cutover_import",
                            data=data, created_by=ACTOR["id"])
            record_audit(entity_type="dashboard_target", entity_id=obj.pk, action="import_alpha_record", before=None, after=data,
                         actor=ACTOR, source="data_migration", metadata=meta)
        for model, entity, key in ((CaseDocument, "case_document", "pk"), (ProductionReport, "production_report", "report_uid"),
                                   (ProductionExclusion, "production_exclusion", "pk"), (DraftRecycleBin, "draft_recycle_bin", "pk"),
                                   (ReferenceSequence, "reference_sequence", "prefix")):
            for obj in model.objects.all():
                table = model._meta.db_table
                record_audit(entity_type=entity, entity_id=getattr(obj, key), action="import_alpha_record", before=None,
                             after=export_model_row(table, obj), actor=ACTOR, source="data_migration", metadata=meta)
        record_audit(entity_type="data_migration_batch", entity_id=self.batch.batch_uid, action="import_alpha_cutover", before=None,
                     after={"sourceCounts": self.batch.source_counts, "targetCounts": self.batch.target_counts,
                            "controlTotals": self.batch.control_totals, "created": dict(self.report["created"]),
                            "matched": dict(self.report["matched"]), "deferred": dict(self.report["deferred"])},
                     actor=ACTOR, source="data_migration", metadata=meta)

    def _dry_run_summary(self):
        """dry-run：整批回滾之後，另外留一筆 dry_run 的批次摘要（沒有 item），方便事後查驗。"""
        batch = MigrationBatch.objects.create(
            source_system=self.batch.source_system, source_version=self.batch.source_version, source_hash=self.src_hash,
            status="dry_run", created_by=ACTOR["id"], source_counts=self.batch.source_counts, target_counts=self.batch.target_counts,
            control_totals=self.batch.control_totals)
        self.report["batchUid"] = str(batch.batch_uid)
