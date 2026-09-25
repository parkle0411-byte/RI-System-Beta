"""
重設某位 Personnel 的登入密碼（忘記密碼時使用），並踢掉他所有已登入的 session。

  manage.py reset_ri_password --personnel-id 5

新密碼隨機產生，只在終端機顯示一次。帳號必須是 active。
"""
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from personnel.management.commands.create_ri_account import generate_password
from personnel.models import Personnel


class Command(BaseCommand):
    help = "Reset a Personnel login password and end its sessions."

    def add_arguments(self, parser):
        parser.add_argument("--personnel-id", type=int, required=True)

    def handle(self, *args, **opts):
        User = get_user_model()
        with transaction.atomic():
            try:
                person = Personnel.objects.select_for_update().get(pk=opts["personnel_id"])
            except Personnel.DoesNotExist:
                raise CommandError(f"Personnel {opts['personnel_id']} does not exist.")
            if not person.auth_user_id or person.account_status != "active":
                raise CommandError(f"{person.name} has no active account.")
            user = User.objects.get(pk=int(person.auth_user_id))
            password = generate_password()
            user.set_password(password)
            user.save(update_fields=["password"])
            for session in Session.objects.all():
                if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                    session.delete()
        self.stdout.write(self.style.SUCCESS(f"Password reset for {person.name} (username: {user.username})"))
        self.stdout.write(f"  password : {password}")
        self.stdout.write("  Shown ONCE. Ask the user to change it after the next login.")
