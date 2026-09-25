"""
重設某位 Personnel 的登入密碼（忘記密碼時使用），並踢掉他所有已登入的 session。

  manage.py reset_ri_password --personnel-id 5

新密碼隨機產生，只在終端機顯示一次。帳號必須是 active。
"""
from django.core.management.base import BaseCommand, CommandError

from audit.services import CLI_ACTOR
from personnel.accounts import AccountError, reset_password


class Command(BaseCommand):
    help = "Reset a Personnel login password and end its sessions."

    def add_arguments(self, parser):
        parser.add_argument("--personnel-id", type=int, required=True)

    def handle(self, *args, **opts):
        try:
            person, user, password, ended = reset_password(personnel_id=opts["personnel_id"], actor=CLI_ACTOR, source="cli")
        except AccountError as e:
            raise CommandError(e.message)
        self.stdout.write(self.style.SUCCESS(f"Password reset for {person.name} (username: {user.username})"))
        self.stdout.write(f"  password : {password}")
        self.stdout.write("  Shown ONCE. Ask the user to change it after the next login.")
