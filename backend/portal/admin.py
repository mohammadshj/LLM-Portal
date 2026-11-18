from django.contrib import admin

from .models import Account, LanguageModel, ModelConnection


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["user", "token_limit", "tokens_used"]
    search_fields = ["user__username"]
    readonly_fields = ["tokens_used"]


@admin.register(LanguageModel)
class LanguageModelAdmin(admin.ModelAdmin):
    list_display = ["name", "provider", "connection", "model_id", "enabled"]
    list_filter = ["provider", "connection", "enabled"]
    search_fields = ["name", "model_id"]
    autocomplete_fields = ["connection"]


@admin.register(ModelConnection)
class ModelConnectionAdmin(admin.ModelAdmin):
    list_display = ["name", "base_url", "api_key_env", "enabled"]
    list_filter = ["enabled"]
    search_fields = ["name"]
