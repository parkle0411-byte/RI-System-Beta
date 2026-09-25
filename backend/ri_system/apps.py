from django.contrib.admin.apps import AdminConfig


class RIAdminConfig(AdminConfig):
    """以唯讀的站點取代 Django 內建的 admin（INSTALLED_APPS 用這個）。見 admin_site.py。"""

    default_site = "ri_system.admin_site.RIAdminSite"
