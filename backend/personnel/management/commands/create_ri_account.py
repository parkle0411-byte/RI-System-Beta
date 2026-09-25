"""
為一位 Personnel 建立登入帳號（Django User），並綁定到該人員。

  manage.py create_ri_account --personnel-id 5 --username p.l --email p.l@example.com

- 只能為「在職」且「尚未綁定帳號」的 Personnel 建立。
- 角色權限來自 Personnel.role_code（見 ri_system/authz.py），這裡不另外指定。
- 初始密碼由系統隨機產生，只在終端機顯示一次，不會寫入任何檔案或日誌。
- 不建立 staff / superuser；Django admin 不對外開放。
"""
import secrets
import string

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from personnel.models import Personnel

ALPHABET = string.ascii_letters + string.digits + "!@#%^*-_=+"


def generate_password(length=20):
    while True:
        pwd = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if any(c.islower() for c in pwd) and any(c.isupper() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


class Command(BaseCommand):
    help = "Create a login account for a Personnel record."

    def add_arguments(self, parser):
        parser.add_argument("--personnel-id", type=int, required=True)
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default="")

    def handle(self, *args, **opts):
        User = get_user_model()
        username = opts["username"].strip().lower()  # 帳號一律小寫，登入時也不分大小寫
        email = opts["email"].strip().lower()
        if not username:
            raise CommandError("--username is required.")

        with transaction.atomic():
            try:
                person = Personnel.objects.select_for_update().get(pk=opts["personnel_id"])
            except Personnel.DoesNotExist:
                raise CommandError(f"Personnel {opts['personnel_id']} does not exist.")
            if not person.is_active:
                raise CommandError(f"{person.name} is inactive; activate the Personnel record first.")
            if person.auth_user_id:
                raise CommandError(f"{person.name} already has an account bound (status: {person.account_status}).")
            if User.objects.filter(username__iexact=username).exists():
                raise CommandError(f"Username '{username}' is already in use.")
            if email and Personnel.objects.filter(email__iexact=email).exclude(pk=person.pk).exists():
                raise CommandError(f"Email '{email}' already belongs to another Personnel record.")

            password = generate_password()
            user = User.objects.create_user(username=username, email=email, password=password)
            now = timezone.now()
            person.auth_user_id = str(user.pk)
            person.account_status = "active"
            person.account_invited_by = "cli"
            person.account_invited_at = now
            person.account_activated_at = now
            person.account_disabled_by = None
            person.account_disabled_at = None
            if email:
                person.email = email
            person.row_version += 1
            person.updated_by = "cli"
            person.save()

        self.stdout.write(self.style.SUCCESS(f"Account created for {person.name} ({person.department}, role={person.role_code})"))
        self.stdout.write(f"  username : {username}")
        self.stdout.write(f"  password : {password}")
        self.stdout.write("  This password is shown ONCE. Ask the user to change it after the first login.")
