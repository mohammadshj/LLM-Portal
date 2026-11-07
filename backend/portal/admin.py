from django.contrib import admin

from .models import Account, LanguageModel


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ["user", "token_limit", "tokens_used"]
    search_fields = ["user__username"]
    readonly_fields = ["tokens_used"]


@admin.register(LanguageModel)
class LanguageModelAdmin(admin.ModelAdmin):
    list_display = ["name", "provider", "model_id", "enabled"]
