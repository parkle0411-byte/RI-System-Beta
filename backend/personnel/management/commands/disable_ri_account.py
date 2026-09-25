"""
停用一位 Personnel 的登入帳號，並立刻踢掉他所有已登入的 session。

  manage.py disable_ri_account --personnel-id 5

帳號與 Personnel 的綁定會保留（狀態為 disabled），稽核時仍能對應到人。
"""
from django.core.management.base import BaseCommand, CommandError

from audit.services import CLI_ACTOR
from personnel.accounts import AccountError, disable_account


class Command(BaseCommand):
    help = "Disable a Personnel login account and end its sessions."

    def add_arguments(self, parser):
        parser.add_argument("--personnel-id", type=int, required=True)

    def handle(self, *args, **opts):
        try:
            person, user, ended = disable_account(personnel_id=opts["personnel_id"], actor=CLI_ACTOR, source="cli")
        except AccountError as e:
            raise CommandError(e.message)
        self.stdout.write(self.style.SUCCESS(f"Account for {person.name} disabled; {ended} session(s) ended."))
