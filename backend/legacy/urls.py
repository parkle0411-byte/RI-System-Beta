from django.urls import path
from .views import TransactionsView,ImportView,OptionsView

# 2026-11-10：網址不變（/api/legacy、/api/legacy/imports、/api/legacy/options）；
# 改由 ri_system/urls.py 以 "api/" 掛載，避免 '/imports'、'/options' 開頭斜線的 urls.W002 警告。
urlpatterns=[path('legacy',TransactionsView.as_view()),path('legacy/imports',ImportView.as_view()),path('legacy/options',OptionsView.as_view())]
