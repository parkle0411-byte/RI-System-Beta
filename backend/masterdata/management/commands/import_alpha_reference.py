"""
一次性匯入 Hatchable Alpha 的參考資料（主檔 / 人員 / 匯率）。

依 DATA-CONVERSION-MAP.md 的規則：
  - 不讀取、不搬移任何帳號憑證；人員不帶 email、不帶登入綁定（account_status 一律 not_configured）。
  - 案件、文件、業績報表不在此匯入範圍。
  - 只新增，不覆寫：自然鍵已存在的列一律略過並在報告中列出，避免蓋掉 VM 上後來的修改。
  - 全程單一交易；預設為 dry-run（跑完回滾），加 --apply 才會真的寫入。
  - 結束時做對帳：筆數與內容雜湊必須與來源一致，否則整批回滾。

用法：
  manage.py import_alpha_reference - < alpha_export.json            # dry-run
  manage.py import_alpha_reference - --apply < alpha_export.json    # 實際寫入
"""
import hashlib
import json
import sys
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fxrates.models import FxRate
from masterdata.models import MasterRecord
from personnel.models import Personnel

IMPORT_ACTOR = "alpha-import"


def digest(rows):
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def parse_ts(value):
    return datetime.fromisoformat(value) if value else None


class Command(BaseCommand):
    help = "Import Alpha reference data (master records, personnel, FX rates). Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("source", help="JSON export path, or '-' for stdin")
        parser.add_argument("--apply", action="store_true", help="Actually write (default is dry-run)")

    def handle(self, *args, **opts):
        raw = sys.stdin.read() if opts["source"] == "-" else open(opts["source"], encoding="utf-8").read()
        data = json.loads(raw)
        for key in ("master", "personnel", "fx"):
            if not isinstance(data.get(key), list):
                raise CommandError(f"Export is missing list '{key}'.")

        report = {"master": [0, 0], "personnel": [0, 0], "fx": [0, 0]}  # [created, skipped]
        skipped = []

        class Rollback(Exception):
            pass

        try:
            with transaction.atomic():
                self.import_master(data["master"], report, skipped)
                self.import_personnel(data["personnel"], report, skipped)
                self.import_fx(data["fx"], report, skipped)
                self.reconcile(data)
                if not opts["apply"]:
                    raise Rollback()
        except Rollback:
            pass

        mode = "APPLIED" if opts["apply"] else "DRY-RUN (rolled back)"
        self.stdout.write(f"\n== {mode} ==")
        for name, (created, skip) in report.items():
            self.stdout.write(f"  {name:10s} created={created:3d} skipped_existing={skip}")
        for line in skipped:
            self.stdout.write(f"  skipped: {line}")
        self.stdout.write("  reconciliation: OK (counts and content hashes match the source)")

    def import_master(self, rows, report, skipped):
        for row in rows:
            if MasterRecord.objects.filter(entity_type=row["entityType"], name=row["name"]).exists() or (
                row["code"] and MasterRecord.objects.filter(entity_type=row["entityType"], code=row["code"]).exists()
            ):
                report["master"][1] += 1
                skipped.append(f"master {row['entityType']}:{row['name']}")
                continue
            is_active = bool(row["isActive"])
            record = MasterRecord.objects.create(
                entity_type=row["entityType"],
                code=row["code"] or None,
                name=row["name"],
                display_order=row["displayOrder"],
                is_active=is_active,
                payload=row["payload"] or {},
                row_version=row["rowVersion"],
                created_by=IMPORT_ACTOR,
                updated_by=IMPORT_ACTOR,
                deactivated_by=None if is_active else IMPORT_ACTOR,
                deactivated_at=None if is_active else parse_ts(row.get("deactivatedAt")),
            )
            if row.get("createdAt"):
                # auto_now_add 會蓋掉建立時間；保留 Alpha 的原始建立時間
                MasterRecord.objects.filter(pk=record.pk).update(created_at=parse_ts(row["createdAt"]))
            report["master"][0] += 1

    def import_personnel(self, rows, report, skipped):
        for row in rows:
            if Personnel.objects.filter(name=row["name"], department=row["department"]).exists():
                report["personnel"][1] += 1
                skipped.append(f"personnel {row['name']} ({row['department']})")
                continue
            is_active = bool(row["isActive"])
            Personnel.objects.create(
                name=row["name"],
                email=None,  # 不帶 email
                department=row["department"],
                role_code=row["roleCode"],
                is_active=is_active,
                is_split_eligible=bool(row["isSplitEligible"]),
                account_status="not_configured",  # 不帶任何帳號狀態
                supervisor_name=row.get("supervisorName"),
                supervisor_email=None,
                row_version=row["rowVersion"],
                created_by=IMPORT_ACTOR,
                updated_by=IMPORT_ACTOR,
                deactivated_by=None if is_active else IMPORT_ACTOR,
                deactivated_at=None if is_active else parse_ts(row.get("deactivatedAt")),
            )
            report["personnel"][0] += 1

    def import_fx(self, rows, report, skipped):
        for row in rows:
            if FxRate.objects.filter(year_month=row["yearMonth"], currency=row["currency"]).exists():
                report["fx"][1] += 1
                skipped.append(f"fx {row['yearMonth']} {row['currency']}")
                continue
            FxRate.objects.create(
                year_month=row["yearMonth"],
                currency=row["currency"],
                rate=Decimal(row["rate"]),
                row_version=row["rowVersion"],
                is_locked=bool(row["isLocked"]),
                created_by=IMPORT_ACTOR,
                updated_by=IMPORT_ACTOR,
            )
            report["fx"][0] += 1

    def reconcile(self, data):
        """來源的每一筆，在目標端必須存在且內容一致；不一致就丟例外讓整批回滾。"""
        src = sorted(
            [[r["entityType"], r["code"] or None, r["name"], r["displayOrder"], bool(r["isActive"]), r["payload"] or {}]
             for r in data["master"]],
            key=lambda x: (x[0], x[2]),
        )
        dst = []
        for r in data["master"]:
            m = MasterRecord.objects.get(entity_type=r["entityType"], name=r["name"])
            dst.append([m.entity_type, m.code, m.name, m.display_order, m.is_active, m.payload])
        dst.sort(key=lambda x: (x[0], x[2]))
        if digest(src) != digest(dst):
            raise CommandError("Reconciliation failed: master records differ from source.")

        psrc = sorted([[r["name"], r["department"], r["roleCode"], bool(r["isActive"]), bool(r["isSplitEligible"]),
                        r.get("supervisorName")] for r in data["personnel"]])
        pdst = []
        for r in data["personnel"]:
            p = Personnel.objects.get(name=r["name"], department=r["department"])
            pdst.append([p.name, p.department, p.role_code, p.is_active, p.is_split_eligible, p.supervisor_name])
        if digest(psrc) != digest(sorted(pdst)):
            raise CommandError("Reconciliation failed: personnel differ from source.")

        fsrc = sorted([[r["yearMonth"], r["currency"], str(Decimal(r["rate"]))] for r in data["fx"]])
        fdst = []
        for r in data["fx"]:
            f = FxRate.objects.get(year_month=r["yearMonth"], currency=r["currency"])
            fdst.append([f.year_month, f.currency, str(f.rate)])
        if digest(fsrc) != digest(sorted(fdst)):
            raise CommandError("Reconciliation failed: FX rates differ from source.")
