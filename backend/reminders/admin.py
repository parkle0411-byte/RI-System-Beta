from django.contrib import admin

from ri_system.admin_site import ReadOnlyModelAdmin

from .models import PaymentAlert, SignedSlipAlert


@admin.register(SignedSlipAlert)
class SignedSlipAlertAdmin(ReadOnlyModelAdmin):
    list_display = ("alert_on", "case", "status", "days_since_effective", "created_at")
    list_filter = ("status",)
    list_select_related = ("case",)
    ordering = ("-alert_on", "-created_at")


@admin.register(PaymentAlert)
class PaymentAlertAdmin(ReadOnlyModelAdmin):
    list_display = ("alert_date", "case", "alert_kind", "status", "created_at")
    list_filter = ("status", "alert_kind")
    list_select_related = ("case",)
    ordering = ("-alert_date", "-created_at")
