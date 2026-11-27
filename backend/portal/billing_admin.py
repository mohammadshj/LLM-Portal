"""Toman-denominated forms; every posting goes through the account lock."""

from uuid import uuid4

from django import forms
from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.db import transaction
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html

from . import billing
from .models import BillingPolicy, CreditTransaction
from .reasoning_admin import CatalogModelForm
from .billing_reports import export


def money_field(label, maximum=billing.MAX_CREDIT, **kwargs):
    return forms.DecimalField(
        label=label,
        min_value=0,
        max_value=billing.toman(maximum),
        decimal_places=1,
        **kwargs,
    )


class PriceForm(CatalogModelForm):
    input_toman = money_field(
        "ورودی؛ تومان برای یک میلیون توکن", billing.MAX_PRICE, required=False
    )
    output_toman = money_field(
        "خروجی؛ تومان برای یک میلیون توکن", billing.MAX_PRICE, required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for side in ("input", "output"):
            self.initial[side + "_toman"] = billing.toman(
                getattr(self.instance, side + "_price_per_million_rial")
            )

    def save(self, commit=True):
        for side in ("input", "output"):
            value = self.cleaned_data[side + "_toman"]
            setattr(
                self.instance,
                side + "_price_per_million_rial",
                billing.rial(value, billing.MAX_PRICE) if value is not None else None,
            )
        return super().save(commit)


class CreditForm(forms.Form):
    operation = forms.ChoiceField(
        label="عملیات",
        choices=[
            ("grant", "افزایش"),
            ("decrease", "کاهش"),
            ("set", "تنظیم اعتبار کل"),
            ("refund", "بازپرداخت مصرف"),
        ],
    )
    amount = money_field("مبلغ (تومان)")
    reason = forms.CharField(label="دلیل", max_length=240)
    refund_of = forms.IntegerField(
        label="شناسه تراکنش مصرف برای بازپرداخت", required=False, min_value=1
    )
    reference = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)


@admin.action(description="مدیریت اعتبار کاربران انتخاب‌شده")
def manage_credit(modeladmin, request, queryset):
    form = CreditForm(request.POST if "confirm_credit" in request.POST else None)
    if form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                for pk in queryset.order_by("pk").values_list("pk", flat=True):
                    billing.change_credit(
                        pk,
                        data["operation"],
                        billing.rial(data["amount"]),
                        str(data["reference"]),
                        data["reason"],
                        request.user,
                        data["refund_of"],
                    )
            modeladmin.message_user(request, "عملیات اعتبار ثبت شد.")
            return None
        except ValidationError as exc:
            form.add_error(None, exc)
    return TemplateResponse(
        request,
        "admin/portal/manage_credit.html",
        {
            **modeladmin.admin_site.each_context(request),
            "form": form,
            "title": "مدیریت اعتبار",
            "ids": list(queryset.values_list("pk", flat=True)),
            "selection": ACTION_CHECKBOX_NAME,
        },
    )


def ledger_link(user_id=None, model_id=None):
    query = f"user__id__exact={user_id}" if user_id else f"model__id__exact={model_id}"
    return format_html(
        '<a href="{}?{}">تراکنش‌ها و جزئیات مصرف</a>',
        reverse("admin:portal_credittransaction_changelist"),
        query,
    )


class PolicyForm(forms.ModelForm):
    amount = money_field("اعتبار پیش‌فرض کاربر جدید (تومان)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["amount"] = billing.toman(self.instance.default_credit_rial)

    def save(self, commit=True):
        self.instance.default_credit_rial = billing.rial(self.cleaned_data["amount"])
        return super().save(commit)


@admin.register(BillingPolicy)
class PolicyAdmin(admin.ModelAdmin):
    form = PolicyForm
    fields = ["amount"]

    def has_add_permission(self, request):
        return not BillingPolicy.objects.exists() and super().has_add_permission(
            request
        )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreditTransaction)
class LedgerAdmin(admin.ModelAdmin):
    fields = (
        "id",
        "user",
        "model",
        "kind",
        "amount",
        "remaining",
        "calculated",
        "uncovered",
        "created_at",
        "created_by",
        "description",
        "request_id",
        "reply_id",
        "reference",
        "refund_of",
        "status",
        "source",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "total_tokens",
        "prices",
        "hold",
    )
    readonly_fields = fields
    list_display = (
        "id",
        "user",
        "model",
        "kind",
        "amount",
        "remaining",
        "source",
        "created_at",
        "created_by",
    )
    list_select_related = ("user", "model", "created_by")
    list_filter = (
        "kind",
        "source",
        "status",
        "created_at",
        ("user", admin.RelatedOnlyFieldListFilter),
        ("model", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("user__username", "model__name", "reference", "description")
    date_hierarchy = "created_at"
    actions = ["csv"]

    @admin.display(description="مبلغ (تومان)")
    def amount(self, obj):
        return billing.toman(obj.amount_rial)

    @admin.display(description="مانده (تومان)")
    def remaining(self, obj):
        return billing.toman(obj.balance_after_rial)

    @admin.display(description="هزینه محاسبه‌شده (تومان)")
    def calculated(self, obj):
        return billing.toman(obj.calculated_rial)

    @admin.display(description="پوشش‌نداده (تومان)")
    def uncovered(self, obj):
        return billing.toman(obj.uncovered_rial)

    @admin.display(description="رزرو اولیه (تومان)")
    def hold(self, obj):
        return billing.toman(obj.reserved_rial)

    @admin.display(description="تعرفه ورودی / خروجی (تومان)")
    def prices(self, obj):
        return (
            f"{billing.toman(obj.input_price)} / {billing.toman(obj.output_price)}"
            if obj.input_price is not None
            else "—"
        )

    @admin.action(description="دریافت CSV")
    def csv(self, request, queryset):
        fields = [
            "id",
            "created_at",
            "user__username",
            "model__name",
            "kind",
            "amount_rial",
            "balance_after_rial",
            "description",
            "created_by__username",
            "reference",
        ]
        return export(queryset.values(*fields), fields, request)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
