"""
為一位 Personnel 建立登入帳號（Django User），並綁定到該人員。

  manage.py create_ri_account --personnel-id 5 --username p.l --email p.l@example.com

實際邏輯在 personnel/accounts.py（與管理員畫面共用）。
- 只能為「在職」且「尚未綁定帳號」的 Personnel 建立。
- 角色權限來自 Personnel.role_code（見 ri_system/authz.py），這裡不另外指定。
- 初始密碼由系統隨機產生，只在終端機顯示一次，不會寫入任何檔案或日誌。
"""
from django.core.management.base import BaseCommand, CommandError

from audit.services import CLI_ACTOR
from personnel.accounts import AccountError, create_account


class Command(BaseCommand):
    help = "Create a login account for a Personnel record."

    def add_arguments(self, parser):
        parser.add_argument("--personnel-id", type=int, required=True)
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default="")

    def handle(self, *args, **opts):
        try:
            person, user, password, _generated = create_account(
                personnel_id=opts["personnel_id"], username=opts["username"], email=opts["email"],
                actor=CLI_ACTOR, source="cli",
            )
        except AccountError as e:
            raise CommandError(e.message)
        self.stdout.write(self.style.SUCCESS(f"Account created for {person.name} ({person.department}, role={person.role_code})"))
        self.stdout.write(f"  username : {user.username}")
        self.stdout.write(f"  password : {password}")
        self.stdout.write("  This password is shown ONCE. The user is required to change it at the first login.")
