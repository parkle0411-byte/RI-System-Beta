from django.urls import path
from .views import MasterDataView

urlpatterns = [
    path("", MasterDataView.as_view(), name="master-data"),
]
