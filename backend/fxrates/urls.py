from django.urls import path

from .views import FxRatesView

urlpatterns = [
    path("", FxRatesView.as_view(), name="fx-rates"),
]
