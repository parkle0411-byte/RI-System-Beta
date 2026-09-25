from django.contrib import admin
from django.urls import include, path

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
]
