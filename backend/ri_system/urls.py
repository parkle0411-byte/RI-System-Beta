from django.contrib import admin
from django.urls import include, path

from personnel.account_views import CreateAccountView, DisableAccountView, EnableAccountView, ResetPasswordView
from cases.accounting_views import AccountingView
from cases.claims_views import ClaimsView
from production.views import ProductionReportView
from dashboard.views import DashboardTargetsView, DashboardView
from cases.document_generation_views import DocumentGenerationLogView, RenderDocumentPdfView
from cases.document_views import CaseDocumentsView
from cases.recycle_views import DraftRecycleBinView
from cases.views import CasesView
from cases.workflow_views import AnnounceView, WorkflowView
from personnel.views import PersonnelOptionsView, PersonnelView

from .auth_views import AppContextView, ChangePasswordView, CsrfView, LoginView, LogoutView
from .views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/auth/csrf", CsrfView.as_view(), name="auth-csrf"),
    path("api/auth/login", LoginView.as_view(), name="auth-login"),
    path("api/auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("api/auth/change-password", ChangePasswordView.as_view(), name="auth-change-password"),
    path("api/app-context", AppContextView.as_view(), name="app-context"),
    path("api/fx-rates", include("fxrates.urls")),
    path("api/master-data", include("masterdata.urls")),
    path("api/audit-log", include("audit.urls")),
    path("api/cases", CasesView.as_view(), name="cases"),
    path("api/draft-recycle-bin", DraftRecycleBinView.as_view(), name="draft-recycle-bin"),
    path("api/case-documents", CaseDocumentsView.as_view(), name="case-documents"),
    path("api/case-announce", AnnounceView.as_view(), name="case-announce"),
    path("api/case-workflow", WorkflowView.as_view(), name="case-workflow"),
    path("api/accounting", AccountingView.as_view(), name="accounting"),
    path("api/claims", ClaimsView.as_view(), name="claims"),
    path("api/render-document-pdf", RenderDocumentPdfView.as_view(), name="render-document-pdf"),
    path("api/document-generation-log", DocumentGenerationLogView.as_view(), name="document-generation-log"),
    path("api/production-report", ProductionReportView.as_view(), name="production-report"),
    path("api/dashboard", DashboardView.as_view(), name="dashboard"),
    path("api/dashboard-targets", DashboardTargetsView.as_view(), name="dashboard-targets"),
    path("api/personnel", PersonnelView.as_view(), name="personnel"),
    path("api/personnel-options", PersonnelOptionsView.as_view(), name="personnel-options"),
    path("api/personnel-accounts", CreateAccountView.as_view(), name="personnel-account-create"),
    path("api/personnel-accounts/disable", DisableAccountView.as_view(), name="personnel-account-disable"),
    path("api/personnel-accounts/enable", EnableAccountView.as_view(), name="personnel-account-enable"),
    path("api/personnel-accounts/reset-password", ResetPasswordView.as_view(), name="personnel-account-reset"),
]
