from django.conf import settings
from django.db import models


class Account(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_limit = models.PositiveBigIntegerField(default=100000)
    tokens_used = models.PositiveBigIntegerField(default=0, editable=False)

    def __str__(self):
        return self.user.username


class LanguageModel(models.Model):
    name = models.CharField(max_length=100)
    provider = models.CharField(
        max_length=20, choices=[("demo", "نمایشی"), ("openai", "OpenAI-compatible")]
    )
    model_id = models.CharField(max_length=150)
    context_window = models.PositiveIntegerField(default=8192)
    max_output_tokens = models.PositiveIntegerField(default=512)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Conversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(
        max_length=10, choices=[("user", "user"), ("assistant", "assistant")]
    )
    content = models.TextField()
    model = models.ForeignKey(
        LanguageModel, null=True, blank=True, on_delete=models.PROTECT
    )
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class ModelUsage(models.Model):
    """Aggregate counters survive message retention cleanup."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    model = models.ForeignKey(LanguageModel, on_delete=models.PROTECT)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "model"], name="unique_user_model_usage"
            )
        ]
