from django.contrib import admin

from ri_system.admin_site import ReadOnlyModelAdmin

from .models import Personnel


@admin.register(Personnel)
class PersonnelAdmin(ReadOnlyModelAdmin):
    list_display = ("name", "department", "role_code", "is_active", "is_split_eligible", "account_status",
                    "must_change_password", "updated_at")
    list_filter = ("department", "role_code", "is_active", "account_status", "must_change_password")
    search_fields = ("name", "email")
    ordering = ("name", "id")
