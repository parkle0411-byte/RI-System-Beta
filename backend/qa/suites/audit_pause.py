"""Pause/resume checks; business writes and test events are rolled back."""
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from rest_framework.test import APIRequestFactory, force_authenticate
from audit.models import AuditLog, EntitySnapshot
from audit.services import record_audit, audit_recording_enabled
from audit.views import AuditLogView
from masterdata.models import MasterRecord
from masterdata.views import MasterDataView
from personnel.models import Personnel
from ri_system.auth_views import AppContextView

factory = APIRequestFactory()
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)

def invoke(view, method, path, user, body=None):
    request = getattr(factory, method)(path, body or {}, format="json")
    # Real requests pass SessionMiddleware; the idle-session state (2026-10-13) reads request.session.
    from django.contrib.sessions.backends.db import SessionStore
    request.session = SessionStore()
    force_authenticate(request, user=user)
    return view.as_view()(request)

initial = AuditLog.objects.count()
with transaction.atomic():
    tag = uuid4().hex
    user = get_user_model().objects.create_user(username="zz_pause_" + tag)
    person = Personnel.objects.create(name="ZZ Pause " + tag, department="admin", role_code="admin", auth_user_id=str(user.pk), account_status="active", created_by="test", updated_by="test")
    with override_settings(AUDIT_LOG_ENABLED=True, AUDIT_LOG_PAUSED=True):
        check("paused status", not audit_recording_enabled())
        result = invoke(MasterDataView, "post", "/api/master-data", user, {"entityType": "class", "name": "ZZ Pause Class " + tag})
        check("business API creates master while paused", result.status_code == 201)
        master = MasterRecord.objects.get(name="ZZ Pause Class " + tag)
        check("snapshot retained while paused", EntitySnapshot.objects.filter(entity_type="master_record", entity_id=str(master.pk), entity_version=1).exists())
        check("business API writes no Audit", AuditLog.objects.count() == initial)
        result = invoke(MasterDataView, "put", "/api/master-data", user, {"id": master.pk, "entityType": "class", "name": master.name + " updated", "rowVersion": 1, "isActive": True})
        check("business update while paused", result.status_code == 200)
        check("update snapshot retained", EntitySnapshot.objects.filter(entity_type="master_record", entity_id=str(master.pk), entity_version=2).exists())
        check("update writes no Audit", AuditLog.objects.count() == initial)
        context = invoke(AppContextView, "get", "/api/app-context", user)
        check("context reports paused", context.status_code == 200 and context.data["auditLogRecordingEnabled"] is False)
        audit = invoke(AuditLogView, "get", "/api/audit-log", user)
        check("Audit API reports paused", audit.status_code == 200 and audit.data["recordingEnabled"] is False)
    with override_settings(AUDIT_LOG_ENABLED=True, AUDIT_LOG_PAUSED=False):
        check("resume status", audit_recording_enabled())
        event = record_audit(entity_type="test", entity_id=tag, action="resume_check", actor=None, after={"resumed": True})
        check("resuming records new events", event is not None and AuditLog.objects.count() == initial + 1)
    transaction.set_rollback(True)
check("test leaves no Audit events", AuditLog.objects.count() == initial)
print(str(len(checks)) + " passed (Audit pause/resume, business API, snapshots, status; rolled back)")
