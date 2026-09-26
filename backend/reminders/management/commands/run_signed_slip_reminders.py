"""每天的提醒排程（由主機的 cron 呼叫，見 scripts/install_reminder_cron.sh）。輸出與 Alpha 的 API 回應相同格式的 JSON。"""
import json

from django.core.management.base import BaseCommand

from reminders.runner import run_signed_slip


class Command(BaseCommand):
    help = "Run the signed slip reminders for today (Asia/Taipei)."

    def add_arguments(self, parser):
        parser.add_argument("--today", help="YYYY-MM-DD（測試用；預設是台北的今天）")

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(run_signed_slip(options.get("today")), ensure_ascii=False))
