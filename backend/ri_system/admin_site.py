"""
唯讀的 Django admin（/admin/）：只給 System Administrator 檢視資料，不能新增、修改或刪除。

設計：
  - 登入沿用 SPA 的同一個 session（同一套登入、限流、密碼規則）；/admin/login/ 只是導向 SPA 的登入頁。
    不需要（也不使用）Django 的 is_staff / 權限；進入條件見 RIAdminSite.has_permission。
  - 唯讀分三層，任何一層失守都不會單獨造成資料被改：
      1. 站點層：除了登出，所有非 GET/HEAD/OPTIONS 的請求一律 403（admin_view）。
      2. ModelAdmin 層：ReadOnlyModelAdmin 的新增／修改／刪除權限都是 False，也沒有批次動作。
      3. 註冊層：站點只接受 ReadOnlyModelAdmin 的註冊；其他一律忽略。所以 Django 內建的
         User／Group（含密碼雜湊）不會出現在這裡，也不可能被不小心註冊成可編輯。
  - 資料庫層面，Audit／Snapshot 本來就是 append-only（trigger 與權限），與這裡無關。
"""
import json
from functools import update_wrapper

from django.contrib import admin
from django.contrib.auth import logout as auth_logout
from django.db.models import JSONField
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html

from .authz import AuthError, has_permission, load_principal

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SPA_LOGIN = "/login"


class RIAdminSite(admin.AdminSite):
    site_header = "RI System 資料檢視（唯讀）"
    site_title = "RI System"
    index_title = "資料檢視（唯讀）"

    def has_permission(self, request):
        """在職、帳號啟用、已完成改密碼的 System Administrator（accounts.manage）才能進入。"""
        try:
            person = load_principal(request)
        except AuthError:
            return False
        return not person.must_change_password and has_permission(person, "accounts.manage")

    def register(self, model_or_iterable, admin_class=None, **options):
        if admin_class is None or not issubclass(admin_class, ReadOnlyModelAdmin):
            return  # 只接受唯讀的 admin；例如 Django 內建的 User／Group 會在這裡被忽略
        super().register(model_or_iterable, admin_class, **options)

    def admin_view(self, view, cacheable=False):
        inner = super().admin_view(view, cacheable)

        def guarded(request, *args, **kwargs):
            if request.method not in SAFE_METHODS and request.path != reverse("admin:logout"):
                return HttpResponseForbidden("The administration site is read-only.")
            return inner(request, *args, **kwargs)

        return update_wrapper(guarded, view)

    def login(self, request, extra_context=None):
        if request.user.is_authenticated:  # 已登入但不是（可用的）System Administrator
            return HttpResponse(
                "The administration site is only available to an active System Administrator "
                "who has already set a personal password.",
                status=403, content_type="text/plain; charset=utf-8",
            )
        target = request.GET.get("next", "")
        target = target if target.startswith("/admin/") else "/admin/"
        return redirect(f"{SPA_LOGIN}?redirect={target}")

    def logout(self, request, extra_context=None):
        auth_logout(request)
        return redirect(SPA_LOGIN)

    def password_change(self, request, extra_context=None):
        return redirect("/")  # 改密碼在主系統的「修改密碼」，規則與強制改密碼流程都在那裡

    def password_change_done(self, request, extra_context=None):
        return redirect("/")


class ReadOnlyModelAdmin(admin.ModelAdmin):
    actions = None
    list_per_page = 50
    show_full_result_count = False  # 稽核表可能很大，不做全表 COUNT

    def __init__(self, model, admin_site):
        super().__init__(model, admin_site)
        # JSON 欄位在詳細頁用縮排格式顯示（欄位名稱加 __pretty）
        for field in model._meta.fields:
            if isinstance(field, JSONField):
                setattr(self, f"{field.name}__pretty", self._pretty(field.name))

    @staticmethod
    def _pretty(name):
        def render(obj):
            value = getattr(obj, name)
            if value is None:
                return "—"
            text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
            return format_html('<pre style="white-space: pre-wrap; margin: 0; max-width: 100%">{}</pre>', text)

        render.short_description = name
        return render

    def get_fields(self, request, obj=None):
        return [
            f"{f.name}__pretty" if isinstance(f, JSONField) else f.name
            for f in self.model._meta.fields
        ]

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj)

    def has_module_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
