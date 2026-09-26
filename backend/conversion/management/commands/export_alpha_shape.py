"""
把這個 VM 的資料庫匯出成「Alpha 匯出檔」的格式（conversion/alpha_format.py），文件檔案複製到 --files 目錄。
用途：切換演練（用一套測試環境扮演 Alpha），以及切換後保存一份與 Alpha 同格式的對照。唯讀，不改任何資料。

  manage.py export_alpha_shape /tmp/export.json --files /tmp/export-files
"""
import json
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand

from cases import storage
from cases.models import Case, CaseDocument, DraftRecycleBin, ReferenceSequence
from conversion.alpha_format import export_model_row
from dashboard.models import DashboardTarget
from fxrates.models import FxRate
from masterdata.models import MasterRecord
from personnel.models import Personnel
from production.models import ProductionExclusion, ProductionReport

MODELS = {"ri_master_records": MasterRecord, "ri_personnel": Personnel, "ri_fx_rates": FxRate, "ri_cases": Case,
          "ri_case_documents": CaseDocument, "ri_draft_recycle_bin": DraftRecycleBin, "ri_production_reports": ProductionReport,
          "ri_production_exclusions": ProductionExclusion, "ri_dashboard_targets": DashboardTarget,
          "ri_reference_sequences": ReferenceSequence}


class Command(BaseCommand):
    help = "Export this database in the Alpha export format (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("output")
        parser.add_argument("--files", required=True)
        parser.add_argument("--system", default="vm-rehearsal")

    def handle(self, *args, **opts):
        tables = {t: [export_model_row(t, o) for o in m.objects.order_by("pk")] for t, m in MODELS.items()}
        tables["ri_payment_alerts"] = []
        tables["ri_signed_slip_alerts"] = []
        files = Path(opts["files"])
        for d in CaseDocument.objects.all():
            target = files / d.storage_key
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(storage.path_for(d.storage_key), target)
        Path(opts["output"]).write_text(json.dumps({"source": {"system": opts["system"], "version": "rehearsal"}, "tables": tables},
                                                   ensure_ascii=False, default=str), encoding="utf-8")
        self.stdout.write("exported " + ", ".join(f"{t}={len(v)}" for t, v in tables.items()))
