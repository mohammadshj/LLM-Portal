from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .validators import validate_connection_url, validate_key_env


class Account(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_limit = models.PositiveBigIntegerField(default=100000)
    tokens_used = models.PositiveBigIntegerField(default=0, editable=False)

    def __str__(self):
        return self.user.username


class ModelConnection(models.Model):
    """Configuration only: the actual API key stays in the server environment."""

    name = models.CharField(max_length=100, unique=True, verbose_name="نام اتصال")
    base_url = models.URLField(
        max_length=500,
        validators=[validate_connection_url],
        verbose_name="آدرس پایهٔ API",
        help_text="آدرس کامل پایه، مثلاً https://api.example.com/v1؛ فقط سرویس‌های مورد اعتماد.",
    )
    api_key_env = models.CharField(
        max_length=100,
        blank=True,
        default="LLM_API_KEY",
        validators=[validate_key_env],
        verbose_name="نام متغیر کلید",
        help_text="فقط نام متغیر محیطی مانند LLM_SERVICE_API_KEY؛ برای سرویس بدون احراز هویت خالی بگذارید.",
    )
    enabled = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = "اتصال سرویس مدل"
        verbose_name_plural = "اتصال‌های سرویس مدل"

    def clean(self):
        super().clean()
        validate_connection_url(self.base_url)
        if self.api_key_env:
            validate_key_env(self.api_key_env)
        self.base_url = self.base_url.rstrip("/")

    def __str__(self):
        return self.name


class LanguageModel(models.Model):
    name = models.CharField(max_length=100)
    provider = models.CharField(
        max_length=20, choices=[("demo", "نمایشی"), ("openai", "OpenAI-compatible")]
    )
    connection = models.ForeignKey(
        ModelConnection,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="models",
        verbose_name="اتصال سرویس",
        help_text="برای مدل واقعی الزامی است؛ چند مدل می‌توانند یک اتصال داشته باشند.",
    )
    model_id = models.CharField(max_length=150)
    context_window = models.PositiveIntegerField(default=8192)
    max_output_tokens = models.PositiveIntegerField(default=512)
    enabled = models.BooleanField(default=True)

    def clean(self):
        super().clean()
        if self.provider == "openai" and not self.connection_id:
            raise ValidationError(
                {"connection": "برای مدل واقعی یک اتصال سرویس انتخاب کنید."}
            )
        if self.provider == "demo" and self.connection_id:
            raise ValidationError(
                {"connection": "مدل نمایشی به اتصال سرویس نیاز ندارد."}
            )

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
