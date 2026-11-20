from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import User

from .models import Account, LanguageModel, Message, ModelConnection
from .thinking import LEVELS


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


class LanguageModelForm(forms.ModelForm):
    thinking_levels = forms.MultipleChoiceField(
        choices=[(v, v) for v in LEVELS],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="سطح‌های مجاز Thinking",
    )

    class Meta:
        model = LanguageModel
        fields = "__all__"


@admin.register(LanguageModel)
class LanguageModelAdmin(admin.ModelAdmin):
    form = LanguageModelForm
    list_display = ["name", "provider", "connection", "model_id", "enabled"]
    list_filter = ["provider", "connection", "enabled"]
    search_fields = ["name", "model_id"]
    autocomplete_fields = ["connection"]


@admin.register(ModelConnection)
class ModelConnectionAdmin(admin.ModelAdmin):
    list_display = ["name", "base_url", "api_key_env", "enabled"]
    list_filter = ["enabled"]
    search_fields = ["name"]
