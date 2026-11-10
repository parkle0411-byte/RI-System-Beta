from django.contrib import admin
from ri_system.admin_site import ReadOnlyModelAdmin
from .models import ImportBatch,LegacyTransaction,LegacyAudit,NumberCounter,LegacyReason
for model in (ImportBatch,LegacyTransaction,LegacyAudit,NumberCounter,LegacyReason):
    admin.site.register(model,ReadOnlyModelAdmin)
