"""
為「啟用 Audit 之前就已存在」的業務資料補上基線紀錄。

  - 每一筆現有資料補一份 snapshot（該筆目前的 row_version）。
      alpha-import 匯入的 → reason = alpha_import；其他（VM 上早期的測試資料）→ reason = audit_baseline
  - alpha-import 匯入的資料另外補一筆 Audit 事件（action = import_reference, source = data_migration），
    對應 DATA-CONVERSION-MAP.md：「每筆匯入的業務資料都有 immutable snapshot 與 Audit Log event」。
  - 可重複執行：已經有 snapshot 的資料會略過。預設 dry-run，加 --apply 才寫入。
  - 事件時間就是「補紀錄的當下」，不假造成過去的日期（DATA-CONVERSION-MAP：歷史只從匯入事件起算）。
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from audit.models import EntitySnapshot
from audit.services import record_audit, record_snapshot
from fxrates.models import FxRate
from fxrates.views import fx_state
from masterdata.models import MasterRecord
from masterdata.views import master_state
from personnel.audit_state import personnel_state
from personnel.models import Personnel

IMPORT_ACTOR = {"id": "alpha-import", "name": "Alpha reference import", "role": "system"}
IMPORT_METADATA = {"sourceProject": "proj_FVUqiQUe3m0G", "sourceSystem": "Hatchable Alpha", "displayVersion": "V 0.003"}


class Command(BaseCommand):
    help = "Backfill snapshots / audit events for pre-audit records. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        counts = {}

        class Rollback(Exception):
            pass

        try:
            with transaction.atomic():
                sets = [
                    ("master_record", MasterRecord.objects.order_by("id"), master_state),
                    ("personnel", Personnel.objects.order_by("id"), personnel_state),
                    ("fx_rate", FxRate.objects.order_by("id"), fx_state),
                ]
                for entity_type, queryset, state_fn in sets:
                    snapshots = audits = skipped = 0
                    for row in queryset:
                        if EntitySnapshot.objects.filter(
                            entity_type=entity_type, entity_id=str(row.pk), entity_version=row.row_version
                        ).exists():
                            skipped += 1
                            continue
                        imported = row.created_by == "alpha-import"
                        state = state_fn(row)
                        record_snapshot(
                            entity_type=entity_type, entity_id=row.pk, version=row.row_version,
                            reason="alpha_import" if imported else "audit_baseline",
                            data=state, created_by=row.created_by,
                        )
                        snapshots += 1
                        if imported:
                            record_audit(
                                entity_type=entity_type, entity_id=row.pk, action="import_reference",
                                before=None, after=state, actor=IMPORT_ACTOR, source="data_migration",
                                metadata=IMPORT_METADATA,
                            )
                            audits += 1
                    counts[entity_type] = (snapshots, audits, skipped)
                if not opts["apply"]:
                    raise Rollback()
        except Rollback:
            pass

        self.stdout.write("== " + ("APPLIED" if opts["apply"] else "DRY-RUN (rolled back)") + " ==")
        for entity_type, (snap, aud, skip) in counts.items():
            self.stdout.write(f"  {entity_type:14s} snapshots={snap:3d} audit_events={aud:3d} already_covered={skip}")
