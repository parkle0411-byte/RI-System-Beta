"""
補上「分期案件已確認的期別」缺少的保費交易（SoA / Transactions）。

背景：2026-09-29 起，有分期的案件每關一期 Production 月報就產生「該期」的交易；
在那之前要等所有期別都確認才一次產生，所以更早關帳的期別留下「已確認、但沒有交易」的案件。
這個指令對每個案件用與關帳相同的判斷（production.closing.transaction_batches）補上缺的期別：

  - 只處理有分期（installmentEnabled）、狀態 Announced／Confirmed、沒有待沖銷的案件
  - 該期所有 Production key 都已確認、而且這期還沒有有效交易，才補；舊的整案全額交易已涵蓋所有期別，不重複補
  - 每個案件補完 row_version + 1，寫 Snapshot（reason = production_case_confirmed）與 Audit（source = maintenance）
  - 可重複執行（補過的期別不會再補）。預設 dry-run，加 --apply 才寫入；執行前請先備份資料庫。
"""
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from audit.services import CLI_ACTOR, record_audit, record_snapshot
from cases.calc.jsnum import get, is_array, js_num_str, js_or, js_to_number, js_to_string, js_truthy, json_roundtrip
from cases.calc.accounting import build_premium_transactions
from cases.models import Case
from production.calc import production_keys_for_case
from production.closing import _confirmed_has, transaction_batches
from production.views import case_source


class Command(BaseCommand):
    help = "Add the missing premium transactions of confirmed installments. Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **opts):
        plans = []
        for case in Case.objects.filter(status__in=("posted", "closed"), recycled_at__isnull=True, is_archived=False).order_by("pk"):
            source = case_source(case)
            payload = json_roundtrip(case.payload or {})
            if get(payload, "installmentEnabled") is not True or js_truthy(get(payload, "pendingReversalOffset")):
                continue
            if not production_keys_for_case(source):
                continue
            confirmed = get(payload, "confirmedProductionKeys")
            confirmed = confirmed if is_array(confirmed) else []
            remaining = any(not _confirmed_has(confirmed, key) for key in production_keys_for_case(source))
            transaction_case = {**payload, "twRef": js_or(get(source, "tw_ref"), get(payload, "twRef"), "")}
            base = payload["transactions"] if is_array(payload.get("transactions")) else []
            batches = [b for b in transaction_batches(source, payload, confirmed, remaining, case.status == "closed", base, transaction_case) if b]
            if not batches:
                continue
            cycle = js_to_number(js_or(get(payload, "reversalCycle"), 0))
            new_transactions = [
                {**t, "txNo": f"{js_to_string(get(t, 'txNo'))}-C{js_num_str(cycle)}"} if cycle > 0 else t
                for entry in batches for t in build_premium_transactions(transaction_case, entry)
            ]
            plans.append((case, payload, base + new_transactions, [b["id"] for b in batches], len(new_transactions)))

        report = [{"caseId": c.pk, "twRef": c.tw_ref, "status": c.status, "installments": ids, "newTransactions": n} for c, _p, _t, ids, n in plans]
        self.stdout.write(json.dumps({"apply": opts["apply"], "cases": report}, ensure_ascii=False, indent=2))
        if not opts["apply"]:
            self.stdout.write("Dry-run: nothing was written. Re-run with --apply (after a database backup).")
            return

        with transaction.atomic():
            for case, payload, transactions, ids, _count in plans:
                locked = Case.objects.select_for_update().get(pk=case.pk)
                if locked.row_version != case.row_version:
                    raise RuntimeError(f"Case {case.pk} changed while running; nothing was written. Run again.")
                before = {"status": locked.status, "rowVersion": locked.row_version, "payload": locked.payload}
                payload["transactions"] = transactions
                locked.payload = payload
                locked.row_version += 1
                locked.updated_by = CLI_ACTOR["id"]
                locked.save()
                after = {"status": locked.status, "rowVersion": locked.row_version, "payload": payload}
                record_snapshot(entity_type="case", entity_id=locked.case_uid, version=locked.row_version,
                                reason="production_case_confirmed",
                                data={"caseUid": str(locked.case_uid), "twRef": locked.tw_ref, **after}, created_by=CLI_ACTOR["id"])
                record_audit(entity_type="case", entity_id=locked.case_uid, action="backfill_installment_transactions",
                             before=before, after=after, actor=CLI_ACTOR, source="maintenance",
                             metadata={"installments": ids})
        self.stdout.write(f"Applied to {len(plans)} case(s).")
