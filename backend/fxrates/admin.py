from django.contrib import admin

from ri_system.admin_site import ReadOnlyModelAdmin

from .models import FxRate


@admin.register(FxRate)
class FxRateAdmin(ReadOnlyModelAdmin):
    list_display = ("year_month", "currency", "rate", "is_locked", "row_version", "updated_at")
    list_filter = ("currency", "is_locked")
    search_fields = ("=year_month",)
    ordering = ("-year_month", "currency")
