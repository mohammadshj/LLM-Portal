from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import User

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.urls import path
from django.utils.html import format_html, format_html_join

from .capabilities import FLAGS, LIMITS, resolve, runtime_model, reasoning_evidence
from .reasoning_admin import CatalogModelForm, TITLES
from .discovery import sync_models
from .discovery_http import DiscoveryError, ERRORS
from .models import Account, LanguageModel, Message, ModelConnection


class PortalUserFields(forms.Form):
    role = forms.ChoiceField(
        label="نقش",
        choices=[("user", "User — کاربر"), ("admin", "Admin — مدیر")],
        initial="user",
    )
    token_limit = Account._meta.get_field("token_limit").formfield(
        label="سقف توکن",
        required=False,
        help_text="خالی هنگام ایجاد یعنی سهمیهٔ پیش‌فرض. هنگام ویرایش، خالی گذاشتن سقف فعلی را حفظ می‌کند.",
    )


class AddUserForm(PortalUserFields, AdminUserCreationForm):
    pass


class EditUserForm(PortalUserFields, UserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["role"] = (
            "admin" if self.instance.is_staff and self.instance.is_superuser else "user"
        )
        self.initial["token_limit"] = self.instance.account.token_limit


admin.site.unregister(User)


@admin.register(User)
class PortalUserAdmin(UserAdmin):
    add_form = AddUserForm
    form = EditUserForm
    add_fieldsets = (
        *UserAdmin.add_fieldsets,
        ("دسترسی و سهمیه", {"fields": ("role", "is_active", "token_limit")}),
    )
    fieldsets = (
        UserAdmin.fieldsets[0],
        UserAdmin.fieldsets[1],
        (
            "دسترسی و سهمیه",
            {"fields": ("role", "is_active", "token_limit", "consumed_tokens")},
        ),
        UserAdmin.fieldsets[3],
    )
    readonly_fields = ("consumed_tokens", "last_login", "date_joined")
    list_display = ("username", "email", "role_label", "is_active")
    list_filter = ("is_active",)
    filter_horizontal = ()

    @admin.display(description="نقش")
    def role_label(self, obj):
        return "Admin" if obj.is_staff and obj.is_superuser else "User"

    @admin.display(description="توکن مصرف‌شده")
    def consumed_tokens(self, obj):
        return obj.account.tokens_used

    def save_model(self, request, obj, form, change):
        # The admin change form is atomic. Serialize edits with admission and settlement.
        if change:
            Account.objects.select_for_update().get(user_id=obj.pk)
        obj.is_staff = obj.is_superuser = form.cleaned_data["role"] == "admin"
        super().save_model(request, obj, form, change)
        limit = form.cleaned_data["token_limit"]
        if limit is not None and (not change or "token_limit" in form.changed_data):
            Account.objects.filter(user_id=obj.pk).update(token_limit=limit)
        if change and not obj.is_active and "is_active" in form.changed_data:
            Message.objects.filter(
                conversation__user=obj, role="user", status="running"
            ).update(cancel_requested=True)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["user", "token_limit", "tokens_used"]
    search_fields = ["user__username"]
    readonly_fields = ["user", "tokens_used"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.save(update_fields=["token_limit"])


class CatalogAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        # Do not write a stale catalog snapshot back when an operator edits another field.
        if change:
            fields = [f.name for f in obj._meta.fields if f.name in form.changed_data]
            if getattr(form, "override_changed", False):
                fields.append("reasoning_overrides")
            if (
                isinstance(obj, LanguageModel)
                and obj.legacy_alias
                and {"connection", "model_id"}.intersection(fields)
            ):
                obj.legacy_alias = False
                fields.append("legacy_alias")
            obj.save(update_fields=fields)
        else:
            super().save_model(request, obj, form, change)


@admin.register(LanguageModel)
class LanguageModelAdmin(CatalogAdmin):
    form = CatalogModelForm
    list_display = ["name", "provider", "connection", "model_id", "enabled"]
    list_filter = ["provider", "connection", "enabled", "auto_thinking"]
    search_fields = ["name", "model_id"]
    autocomplete_fields = ["connection"]
    readonly_fields = ["effective_capabilities", "discovery_data", "profile_summary"]
    fieldsets = [
        (None, {"fields": ["name", "provider", "connection", "model_id", "enabled"]}),
        (
            "تنظیم استدلال (Reasoning Configuration)",
            {
                "fields": [
                    "auto_thinking",
                    "profile_summary",
                    "reasoning_policy",
                    "pin",
                    "reasoning",
                    "wire",
                    "reasoning_mandatory",
                    "reasoning_toggle",
                    "default_enabled",
                    "efforts",
                    "custom_efforts",
                    "default_effort",
                    "effort_required",
                    "toggle_required",
                    "budget_required",
                    "budget_min",
                    "budget_max",
                    "budget_presets",
                    "default_budget",
                ]
            },
        ),
        (
            "بودجه و پروتکل گفتگو",
            {
                "fields": [
                    "context_window",
                    "max_output_tokens",
                    "provider_output_limit",
                    "output_parameter",
                    "stream_usage_option",
                    "tokenizer_name",
                    "framing_tokens",
                ]
            },
        ),
        (
            "تنظیمات سازگاری قدیمی",
            {
                "classes": ["collapse"],
                "fields": [
                    "thinking_contract",
                    "thinking_levels",
                    "thinking_default",
                    "thinking_budgets",
                ],
            },
        ),
        (
            "جزئیات فنی کشف",
            {
                "classes": ["collapse"],
                "fields": [
                    "effective_capabilities",
                    "capability_overrides",
                    "discovery_data",
                ],
            },
        ),
    ]

    @admin.display(description="پروفایل مؤثر، منبع و تعارض‌ها")
    def profile_summary(self, obj):
        if not obj or not obj.pk:
            return "پس از ثبت مدل یا همگام‌سازی، پروفایل اینجا نمایش داده می‌شود."
        profile = runtime_model(obj).reasoning_profile.public()
        rows = []
        for key, item in reasoning_evidence(obj, TITLES).items():
            competing = " · ".join(
                f"{name}: {value}" for name, value in item["conflicts"].items()
            )
            rows.append(
                (
                    TITLES[key],
                    item["value"],
                    item["source"],
                    item["verification"],
                    competing or "—",
                )
            )
        table = format_html_join(
            "", "<tr><th>{}</th><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", rows
        )
        return format_html(
            "<p>{} · {}</p><table><tr><th>قابلیت</th><th>مقدار</th><th>منبع</th><th>وضعیت تأیید</th><th>دادهٔ متفاوت کاتالوگ</th></tr>{}</table>",
            profile["mode"],
            ", ".join(c["type"] for c in profile["controls"]),
            table,
        )

    @admin.display(description="قابلیت مؤثر و منبع اطلاعات")
    def effective_capabilities(self, obj):
        if not obj:
            return "—"
        facts, sources = resolve(obj)
        rows = format_html_join(
            "",
            "<tr><th>{}</th><td>{}</td><td>{}</td></tr>",
            (
                (
                    key,
                    facts[key] if facts.get(key) is not None else "نامعلوم",
                    sources.get(key, "—"),
                )
                for key in (
                    *FLAGS,
                    *LIMITS,
                    "efforts",
                    "default_effort",
                    "wire",
                    "reasoning_mandatory",
                    "default_enabled",
                    "router_budget_supported",
                    "reasoning_toggle",
                    "budget_tokens",
                )
            ),
        )
        return format_html("<table>{}</table>", rows)


class ConnectionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["discovery_type"].required = False

    def clean_discovery_type(self):
        return self.cleaned_data["discovery_type"] or "compatible"


@admin.register(ModelConnection)
class ModelConnectionAdmin(CatalogAdmin):
    form = ConnectionForm
    list_display = [
        "name",
        "base_url",
        "discovery_type",
        "enabled",
        "last_synced_at",
        "sync_status",
    ]
    list_filter = ["enabled", "discovery_type"]
    search_fields = ["name"]
    readonly_fields = [
        "sync_started_at",
        "last_synced_at",
        "sync_status",
        "sync_result",
    ]

    @admin.display(description="وضعیت همگام‌سازی")
    def sync_status(self, obj):
        result = obj.sync_result
        return ERRORS.get(result.get("code")) or {
            "ok": "کامل",
            "partial": "بخشی از ردیف‌ها نامعتبر بود",
            "running": "در حال اجرا",
        }.get(result.get("status"), "هنوز اجرا نشده")

    def get_urls(self):
        return [
            path(
                "<int:pk>/sync-models/",
                self.admin_site.admin_view(self.sync_view),
                name="portal_connection_sync",
            ),
            *super().get_urls(),
        ]

    def sync_view(self, request, pk):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        obj = get_object_or_404(ModelConnection, pk=pk)
        if not self.has_change_permission(
            request, obj
        ) or not self.admin_site.has_permission(request):
            raise PermissionDenied
        try:
            result = sync_models(pk)
            self.message_user(
                request,
                "افزوده: {added}، به‌روزشده: {updated}، بدون تغییر: {unchanged}، ردیف خطادار: {errors}، غایب: {absent}".format(
                    **result
                ),
                messages.WARNING if result["errors"] else messages.SUCCESS,
            )
            if result["registry"] in ("stale", "unavailable"):
                self.message_user(
                    request,
                    "Registry در دسترس نبود. نتیجهٔ استفاده از حافظهٔ محلی در گزارش ثبت شد.",
                    messages.WARNING,
                )
        except DiscoveryError as exc:
            self.message_user(request, str(exc), messages.ERROR)
        return redirect("admin:portal_modelconnection_change", pk)
