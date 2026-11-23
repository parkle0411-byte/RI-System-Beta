from django.contrib import admin
from django.urls import include, path
from masterdata.market_views import LloydsRatingsView

from personnel.account_views import AccountView
from cases.accounting_views import AccountingView
from cases.claims_views import ClaimsView
from cases.claim_loss_snapshot_views import ClaimLossSnapshotView
from production.views import ProductionReportView
from reminders.views import CaseRemindersView
from dashboard.views import DashboardTargetsView, DashboardView
from cases.document_generation_views import DocumentGenerationLogView
from cases.document_views import CaseDocumentsView
from cases.generated_document_views import GeneratedCaseDocumentView
from cases.placing_views import PlacingSlipView
from cases.recycle_views import DraftRecycleBinView
from cases.reference_views import ReconciliationReferencesView
from cases.views import CasesView
from cases.facility_declaration_views import FacilityDeclarationsView, FacilityDeclarationAnnounceView
from cases.facility_declaration_documents import FacilityDeclarationDocumentsView
from cases.facility_placement_views import FacilityPlacementView, FacilityAnnounceView, FacilityRenewalView
from cases.insured_views import InsuredMasterView
from cases.personnel_history_views import CasePersonnelHistoryView
from cases.workflow_views import AnnounceView, WorkflowView
from personnel.views import PersonnelOptionsView, PersonnelView

from .auth_views import AppContextView, ChangePasswordView, CsrfView, LoginView, LogoutView, SessionActivityView, SessionStatusView
from .password_reset import PasswordResetConfirmView, PasswordResetView
from .reference_views import SystemReferenceView
from .views import HealthView

urlpatterns = [
    path("api/", include("legacy.urls")),  # /api/legacy、/api/legacy/imports、/api/legacy/options
    path("api/system-reference", SystemReferenceView.as_view(), name="system-reference"),
    path("admin/", admin.site.urls),
    path("health/", HealthView.as_view(), name="health"),
    path("api/auth/csrf", CsrfView.as_view(), name="auth-csrf"),
    path("api/auth/login", LoginView.as_view(), name="auth-login"),
    path("api/auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("api/auth/session", SessionStatusView.as_view(), name="auth-session-status"),
    path("api/auth/activity", SessionActivityView.as_view(), name="auth-session-activity"),
    path("api/auth/change-password", ChangePasswordView.as_view(), name="auth-change-password"),
    path("api/auth/password-reset", PasswordResetView.as_view(), name="auth-password-reset"),
    path("api/auth/password-reset/confirm", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    path("api/app-context", AppContextView.as_view(), name="app-context"),
    path("api/fx-rates", include("fxrates.urls")),
    path("api/master-data/lloyds-ratings", LloydsRatingsView.as_view(), name="lloyds-ratings"),
    path("api/master-data", include("masterdata.urls")),
    path("api/audit-log", include("audit.urls")),
    path("api/insured-masters", InsuredMasterView.as_view(), name="insured-masters"),
    path("api/cases", CasesView.as_view(), name="cases"),
    path("api/facility-declarations", FacilityDeclarationsView.as_view(), name="facility-declarations"),
    path("api/facility-declaration-announce", FacilityDeclarationAnnounceView.as_view(), name="facility-declaration-announce"),
    path("api/facility-declaration-documents", FacilityDeclarationDocumentsView.as_view(), name="facility-declaration-documents"),
    path("api/facility-placement", FacilityPlacementView.as_view(), name="facility-placement"),
    path("api/facility-announce", FacilityAnnounceView.as_view(), name="facility-announce"),
    path("api/facility-renewal", FacilityRenewalView.as_view(), name="facility-renewal"),
    path("api/case-personnel-history", CasePersonnelHistoryView.as_view(), name="case-personnel-history"),
    path("api/case-reconciliation-references", ReconciliationReferencesView.as_view(), name="case-reconciliation-references"),
    path("api/draft-recycle-bin", DraftRecycleBinView.as_view(), name="draft-recycle-bin"),
    path("api/case-documents", CaseDocumentsView.as_view(), name="case-documents"),
    path("api/generated-case-documents", GeneratedCaseDocumentView.as_view(), name="generated-case-documents"),
    path("api/placing-slips", PlacingSlipView.as_view(), name="placing-slips"),
    path("api/case-announce", AnnounceView.as_view(), name="case-announce"),
    path("api/case-workflow", WorkflowView.as_view(), name="case-workflow"),
    path("api/accounting", AccountingView.as_view(), name="accounting"),
    path("api/claims", ClaimsView.as_view(), name="claims"),
    path("api/claim-loss-snapshot", ClaimLossSnapshotView.as_view(), name="claim-loss-snapshot"),
    path("api/document-generation-log", DocumentGenerationLogView.as_view(), name="document-generation-log"),
    path("api/case-reminders", CaseRemindersView.as_view(), name="case-reminders"),
    path("api/production-report", ProductionReportView.as_view(), name="production-report"),
    path("api/dashboard", DashboardView.as_view(), name="dashboard"),
    path("api/dashboard-targets", DashboardTargetsView.as_view(), name="dashboard-targets"),
    path("api/personnel", PersonnelView.as_view(), name="personnel"),
    path("api/personnel-options", PersonnelOptionsView.as_view(), name="personnel-options"),
    # 2026-11-17：帳號的建立／停用／啟用／重設密碼合為一個網址，以 action 區分（personnel/account_views.py）
    path("api/personnel-accounts", AccountView.as_view(), name="personnel-accounts"),
]
