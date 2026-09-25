from django.contrib import admin
from django.urls import include, path

from personnel.account_views import CreateAccountView, DisableAccountView, EnableAccountView, ResetPasswordView
from cases.views import CasesView
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
    path("api/personnel", PersonnelView.as_view(), name="personnel"),
    path("api/personnel-options", PersonnelOptionsView.as_view(), name="personnel-options"),
    path("api/personnel-accounts", CreateAccountView.as_view(), name="personnel-account-create"),
    path("api/personnel-accounts/disable", DisableAccountView.as_view(), name="personnel-account-disable"),
    path("api/personnel-accounts/enable", EnableAccountView.as_view(), name="personnel-account-enable"),
    path("api/personnel-accounts/reset-password", ResetPasswordView.as_view(), name="personnel-account-reset"),
]
