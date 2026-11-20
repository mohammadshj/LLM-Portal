from django import forms
from django.contrib import admin

from .models import Account, LanguageModel, ModelConnection
from .thinking import LEVELS


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["user", "token_limit", "tokens_used"]
    search_fields = ["user__username"]
    readonly_fields = ["tokens_used"]


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
