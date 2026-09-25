"""
重新啟用被停用的登入帳號。

  manage.py enable_ri_account --personnel-id 5

沿用原本的密碼，但本人第一次登入必須先改密碼。若本人忘記原密碼，啟用後再執行 reset_ri_password。
"""
from django.core.management.base import BaseCommand, CommandError

from audit.services import CLI_ACTOR
from personnel.accounts import AccountError, enable_account


class Command(BaseCommand):
    help = "Re-enable a disabled Personnel login account (password change required at next login)."

    def add_arguments(self, parser):
        parser.add_argument("--personnel-id", type=int, required=True)

    def handle(self, *args, **opts):
        try:
            person, user = enable_account(personnel_id=opts["personnel_id"], actor=CLI_ACTOR, source="cli")
        except AccountError as e:
            raise CommandError(e.message)
        self.stdout.write(self.style.SUCCESS(f"Account for {person.name} (username: {user.username}) re-enabled."))
        self.stdout.write("  The old password still works, but must be changed at the next login.")
