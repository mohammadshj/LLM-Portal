from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import User

from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join

from .capabilities import FLAGS, LIMITS, resolve, runtime_model, reasoning_evidence
from .reasoning_admin import TITLES
from . import billing
from .billing_admin import PriceForm, money_field, manage_credit, ledger_link
from django.db.models import Sum, Count, Max, Q, F
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
    initial_credit = money_field(
        "اعتبار اولیه (تومان، خالی برای پیش‌فرض)", required=False
    )
    credit_reason = forms.CharField(
        label="دلیل تخصیص اعتبار", required=False, max_length=240
    )


class EditUserForm(PortalUserFields, UserChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["role"] = (
            "admin" if self.instance.is_staff and self.instance.is_superuser else "user"
        )
        self.initial["token_limit"] = self.instance.account.token_limit


class BalanceFilter(admin.SimpleListFilter):
    title = "اعتبار آزاد"
    parameter_name = "credit_state"

    def lookups(self, request, model_admin):
        return [("empty", "تمام‌شده"), ("low", "کمتر یا برابر ده درصد")]

    def queryset(self, request, queryset):
        if self.value() not in ("empty", "low"):
            return queryset
        rows = queryset.annotate(
            available=F("account__credit_limit_rial")
            - F("account__credit_used_rial")
            - F("account__credit_reserved_rial")
        )
        return (
            rows.filter(available=0)
            if self.value() == "empty"
            else rows.filter(
                available__gt=0, available__lte=F("account__credit_limit_rial") / 10
            )
        )


admin.site.unregister(User)


@admin.register(User)
class PortalUserAdmin(UserAdmin):
    add_form = AddUserForm
    form = EditUserForm
    add_fieldsets = (
        *UserAdmin.add_fieldsets,
        (
            "دسترسی و سهمیه",
            {
                "fields": (
                    "role",
                    "is_active",
                    "initial_credit",
                    "credit_reason",
                    "token_limit",
                )
            },
        ),
    )
    fieldsets = (
        UserAdmin.fieldsets[0],
        UserAdmin.fieldsets[1],
        (
            "دسترسی و سهمیه",
            {
                "fields": (
                    "role",
                    "is_active",
                    "token_limit",
                    "consumed_tokens",
                    "credit_details",
                    "credit_history",
                    "model_report",
                )
            },
        ),
        UserAdmin.fieldsets[3],
    )
    actions = [manage_credit]
    readonly_fields = (
        "credit_details",
        "credit_history",
        "model_report",
        "consumed_tokens",
        "last_login",
        "date_joined",
    )
    list_display = (
        "username",
        "email",
        "role_label",
        "is_active",
        "credit_details",
        "last_use",
    )
    list_filter = ("is_active", BalanceFilter)
    filter_horizontal = ()

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("account")
            .annotate(
                last_usage=Max(
                    "credit_entries__created_at", filter=Q(credit_entries__kind="usage")
                )
            )
        )

    @admin.display(description="آخرین مصرف")
    def last_use(self, obj):
        return obj.last_usage

    @admin.display(description="اعتبار کل / مصرف / مانده / رزرو (تومان) · درصد مصرف")
    def credit_details(self, obj):
        data = billing.balance(obj.account)
        amounts = " / ".join(
            str(billing.toman(data[k]))
            for k in (
                "credit_limit_rial",
                "credit_used_rial",
                "credit_remaining_rial",
                "credit_reserved_rial",
            )
        )
        return f"{amounts} · {100 * obj.account.credit_used_rial // (obj.account.credit_limit_rial or 1)}٪"

    @admin.display(description="تاریخچهٔ اعتبار")
    def credit_history(self, obj):
        return format_html(
            '<a href="{}">تغییر اعتبار</a> · {}',
            reverse("admin:portal_user_credit", args=[obj.pk]),
            ledger_link(user_id=obj.pk),
        )

    def get_urls(self):
        return [
            path(
                "<int:pk>/credit/",
                self.admin_site.admin_view(self.credit_view),
                name="portal_user_credit",
            ),
            *super().get_urls(),
        ]

    def credit_view(self, request, pk):
        if not self.has_change_permission(request):
            raise PermissionDenied
        obj = get_object_or_404(User, pk=pk)
        response = manage_credit(self, request, User.objects.filter(pk=obj.pk))
        return response or redirect("admin:auth_user_change", obj.pk)

    @admin.display(description="گزارش تفکیکی مدل‌ها و بازه زمانی")
    def model_report(self, obj):
        return format_html(
            '<a href="/?billing=user-model-usage&amp;user={}">گزارش مصرف این کاربر</a>',
            obj.pk,
        )

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
        if not change and form.cleaned_data.get("initial_credit") is not None:
            obj.initial_credit_grant = (
                billing.rial(form.cleaned_data["initial_credit"]),
                form.cleaned_data.get("credit_reason") or "تخصیص هنگام ایجاد کاربر",
                request.user,
            )
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
    fields = ["user", "tokens_used", "token_limit"]
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
            for side in ("input", "output"):
                if side + "_toman" in form.changed_data:
                    fields.append(side + "_price_per_million_rial")
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
    form = PriceForm
    list_display = [
        "name",
        "provider",
        "connection",
        "model_id",
        "enabled",
        "prices",
        "model_stats",
    ]
    list_filter = ["provider", "connection", "enabled", "auto_thinking"]
    search_fields = ["name", "model_id"]
    autocomplete_fields = ["connection"]
    readonly_fields = ["effective_capabilities", "discovery_data", "profile_summary"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("connection")
            .annotate(
                n_users=Count(
                    "credittransaction__user",
                    distinct=True,
                    filter=Q(credittransaction__kind="usage"),
                ),
                n_requests=Count(
                    "credittransaction", filter=Q(credittransaction__kind="usage")
                ),
                spend=Sum(
                    "credittransaction__amount_rial",
                    filter=Q(credittransaction__kind="usage"),
                ),
            )
        )

    @admin.display(description="ورودی / خروجی (تومان برای یک میلیون)")
    def prices(self, obj):
        return (
            "تعرفه ناقص"
            if None
            in (obj.input_price_per_million_rial, obj.output_price_per_million_rial)
            else f"{billing.toman(obj.input_price_per_million_rial)} / {billing.toman(obj.output_price_per_million_rial)}"
        )

    @admin.display(description="کاربران / درخواست / مصرف (تومان)")
    def model_stats(self, obj):
        return format_html(
            '<a href="/?billing=user-model-usage&amp;model={}">{} / {} / {}</a>',
            obj.pk,
            obj.n_users,
            obj.n_requests,
            billing.toman(-(obj.spend or 0)),
        )

    fieldsets = [
        ("تعرفه فروش", {"fields": ["input_toman", "output_toman"]}),
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
