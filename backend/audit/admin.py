from django.contrib import admin

from ri_system.admin_site import ReadOnlyModelAdmin

from .models import AuditLog, EntitySnapshot


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyModelAdmin):
    list_display = ("occurred_at", "entity_type", "entity_id", "action", "actor_name", "actor_role", "source")
    list_filter = ("entity_type", "action", "source", "actor_role", "occurred_at")
    search_fields = ("=entity_id", "actor_name", "=request_id")
    ordering = ("-occurred_at", "-id")


@admin.register(EntitySnapshot)
class EntitySnapshotAdmin(ReadOnlyModelAdmin):
    list_display = ("created_at", "entity_type", "entity_id", "entity_version", "snapshot_reason", "created_by")
    list_filter = ("entity_type", "snapshot_reason")
    search_fields = ("=entity_id",)
    ordering = ("-created_at", "-id")
