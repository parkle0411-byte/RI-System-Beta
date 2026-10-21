from django.contrib import admin

from ri_system.admin_site import ReadOnlyModelAdmin

from .models import MasterRecord, MarketRatingProfile


@admin.register(MasterRecord)
class MasterRecordAdmin(ReadOnlyModelAdmin):
    list_display = ("entity_type", "code", "name", "display_order", "is_active", "updated_at")
    list_filter = ("entity_type", "is_active")
    search_fields = ("name", "code")
    ordering = ("entity_type", "display_order", "id")


@admin.register(MarketRatingProfile)
class MarketRatingProfileAdmin(ReadOnlyModelAdmin):
    list_display = ("market_code", "row_version", "updated_by", "updated_at")
