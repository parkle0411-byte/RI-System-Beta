from ri_system.admin_site import ReadOnlyModelAdmin
from django.contrib import admin

from .models import Case, CaseDocument, DraftRecycleBin, ReferenceSequence


@admin.register(Case)
class CaseAdmin(ReadOnlyModelAdmin):
    list_display = ("id", "tw_ref", "status", "case_kind", "reinsured_name_snapshot", "currency",
                    "effective_date", "owner_personnel", "updated_at")
    list_filter = ("status", "case_kind", "reinsurance_structure", "is_archived", "currency")
    search_fields = ("=tw_ref", "reinsured_name_snapshot", "class_name_snapshot", "ae_name_snapshot")
    list_select_related = ("owner_personnel",)
    ordering = ("-updated_at", "-id")


@admin.register(CaseDocument)
class CaseDocumentAdmin(ReadOnlyModelAdmin):
    list_display = ("filename", "kind", "case", "byte_size", "uploaded_by", "uploaded_at")
    list_filter = ("kind",)
    search_fields = ("filename",)
    list_select_related = ("case",)
    ordering = ("-uploaded_at",)


@admin.register(ReferenceSequence)
class ReferenceSequenceAdmin(ReadOnlyModelAdmin):
    list_display = ("prefix", "last_value", "updated_at")


@admin.register(DraftRecycleBin)
class DraftRecycleBinAdmin(ReadOnlyModelAdmin):
    list_display = ("id", "original_case", "original_case_version", "deleted_by", "deleted_at", "restore_deadline", "restored_at")
    list_filter = ("restored_at",)
    list_select_related = ("original_case",)
    ordering = ("-deleted_at", "-id")
