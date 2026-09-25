"""
停用一位 Personnel 的登入帳號，並立刻踢掉他所有已登入的 session。

  manage.py disable_ri_account --personnel-id 5

帳號與 Personnel 的綁定會保留（狀態為 disabled），稽核時仍能對應到人。
"""
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from audit.services import CLI_ACTOR, record_audit, record_snapshot
from personnel.audit_state import personnel_state
from personnel.models import Personnel


class Command(BaseCommand):
    help = "Disable a Personnel login account and end its sessions."

    def add_arguments(self, parser):
        parser.add_argument("--personnel-id", type=int, required=True)

    def handle(self, *args, **opts):
        User = get_user_model()
        with transaction.atomic():
            try:
                person = Personnel.objects.select_for_update().get(pk=opts["personnel_id"])
            except Personnel.DoesNotExist:
                raise CommandError(f"Personnel {opts['personnel_id']} does not exist.")
            if not person.auth_user_id:
                raise CommandError(f"{person.name} has no account.")
            before = personnel_state(person)
            user = User.objects.get(pk=int(person.auth_user_id))
            user.is_active = False
            user.save(update_fields=["is_active"])
            ended = 0
            for session in Session.objects.all():
                if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                    session.delete()
                    ended += 1
            person.account_status = "disabled"
            person.account_disabled_by = "cli"
            person.account_disabled_at = timezone.now()
            person.row_version += 1
            person.updated_by = "cli"
            person.save()

            after = personnel_state(person)
            record_snapshot(
                entity_type="personnel", entity_id=person.pk, version=person.row_version,
                reason="personnel_account_disabled", data=after, created_by="cli",
            )
            record_audit(
                entity_type="personnel", entity_id=person.pk, action="disable_account",
                before=before, after=after, actor=CLI_ACTOR, source="cli",
                metadata={"username": user.username, "sessionsEnded": ended},
            )
        self.stdout.write(self.style.SUCCESS(f"Account for {person.name} disabled; {ended} session(s) ended."))
