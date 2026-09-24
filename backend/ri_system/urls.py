from django.contrib import admin
from django.urls import include, path

from .views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/fx-rates", include("fxrates.urls")),
    path("api/master-data", include("masterdata.urls")),
]
