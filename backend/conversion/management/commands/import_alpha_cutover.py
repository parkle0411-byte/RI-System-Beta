"""
切換時把 Alpha 的匯出檔轉入 VM（規則見 conversion/importer.py）。預設 dry-run，加 --apply 才提交。

  manage.py import_alpha_cutover /path/alpha_export.json --files /path/documents            # dry-run
  manage.py import_alpha_cutover /path/alpha_export.json --files /path/documents --apply    # 實際寫入
"""
import json
import sys

from django.core.management.base import BaseCommand, CommandError

from conversion.importer import ConversionError, Importer


class Command(BaseCommand):
    help = "Convert an Alpha export into the VM (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("export", help="Alpha export JSON path, or '-' for stdin")
        parser.add_argument("--files", help="directory holding the document files (file name = storage_key)")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--json", action="store_true", help="print the report as JSON")

    def handle(self, *args, **opts):
        raw = sys.stdin.read() if opts["export"] == "-" else open(opts["export"], encoding="utf-8").read()
        try:
            report = Importer(json.loads(raw), opts.get("files"), apply=opts["apply"]).run()
        except ConversionError as exc:
            self.stdout.write(json.dumps({"ok": False, "error": exc.code, "problems": exc.problems}, ensure_ascii=False, indent=1, default=str))
            raise CommandError(f"conversion stopped: {exc.code} ({len(exc.problems)} problem(s)); nothing was written")
        if opts["json"]:
            self.stdout.write(json.dumps({"ok": True, **report}, ensure_ascii=False, default=str))
            return
        self.stdout.write(f"\n== {report['mode']} {'(rolled back)' if report['mode'] == 'DRY-RUN' else '(committed)'} · batch {report.get('batchUid')} ==")
        for table, n in report["sourceCounts"].items():
            self.stdout.write(f"  {table:26s} source={n:5d} created={report['created'].get(table, 0):5d} "
                              f"matched={report['matched'].get(table, 0):4d} deferred={report['deferred'].get(table, 0):4d}")
        self.stdout.write(f"  control totals: {json.dumps(report['controlTotals'], ensure_ascii=False)}")
        if report["signatureIssues"]:
            self.stdout.write(f"  WARNING: {len(report['signatureIssues'])} report(s) whose Alpha signature does not match their rows")
        self.stdout.write("  reconciliation: OK (counts, round-trip content, integrity and control totals)")
