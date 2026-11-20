from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from .thinking import CONTRACTS, LEVELS, POLICIES, validate_capabilities
from .validators import validate_connection_url, validate_key_env


class Account(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_limit = models.PositiveBigIntegerField(default=100000)
    tokens_used = models.PositiveBigIntegerField(default=0, editable=False)

    def __str__(self):
        return self.user.username


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_account(sender, instance, created, raw, using, **kwargs):
    if created and not raw:
        Account.objects.using(using).get_or_create(user_id=instance.pk)


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

    streaming_enabled = models.BooleanField(
        default=True, verbose_name="ارسال درخواست جریانی"
    )

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

    tokenizer_name = models.SlugField(
        blank=True, help_text="نام فایل tokenizer.json محلی و تأییدشده، بدون پسوند"
    )
    output_parameter = models.CharField(
        max_length=24,
        default="max_tokens",
        choices=[(p, p) for p in ("max_tokens", "max_completion_tokens")],
    )
    stream_usage_option = models.BooleanField(
        default=True,
        help_text="ارسال stream_options.include_usage در صورت پشتیبانی سرویس",
    )
    thinking_contract = models.CharField(
        max_length=16, default="none", choices=[(c, c) for c in CONTRACTS]
    )
    thinking_levels = models.JSONField(default=list, blank=True)
    thinking_default = models.CharField(
        max_length=8, blank=True, choices=[(v, v) for v in LEVELS]
    )
    reasoning_policy = models.CharField(
        max_length=12, choices=POLICIES, default="hidden"
    )
    provider_output_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="سقف خروجی مستند همین endpoint",
    )
    framing_tokens = models.PositiveIntegerField(
        default=32,
        validators=[MinValueValidator(32), MaxValueValidator(4096)],
        help_text="حاشیهٔ تخمین بایتی برای هر پیام و کل درخواست",
    )

    def clean(self):
        super().clean()
        validate_capabilities(self)
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
    input_tokens = models.PositiveIntegerField(null=True, default=0)
    output_tokens = models.PositiveIntegerField(null=True, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    thinking_level = models.CharField(max_length=8, blank=True)
    reasoning_content = models.TextField(null=True)
    reasoning_origin = models.CharField(max_length=64, blank=True)
    reasoning_tokens = models.PositiveIntegerField(null=True)
    total_tokens = models.PositiveBigIntegerField(null=True)
    # User rows are turns; each selected model gets a child row before dispatch.
    parent = models.ForeignKey(
        "self", null=True, on_delete=models.CASCADE, related_name="replies"
    )
    request_id = models.UUIDField(null=True)
    status = models.CharField(max_length=12, default="completed")
    error = models.CharField(max_length=240, blank=True)
    usage_source = models.CharField(max_length=12, default="none")
    reserved_tokens = models.PositiveBigIntegerField(default=0)
    # Saved at admission so later model edits cannot change an in-flight budget.
    input_bound = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True, db_index=True)
    cancel_requested = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["conversation"],
                condition=models.Q(role="user", status="running"),
                name="one_running_turn_per_chat",
            ),
            models.UniqueConstraint(
                fields=["conversation", "request_id"], name="unique_chat_request"
            ),
            models.UniqueConstraint(
                fields=["parent", "model"], name="unique_reply_model"
            ),
        ]


class ModelUsage(models.Model):
    """Aggregate counters survive message retention cleanup."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    model = models.ForeignKey(LanguageModel, on_delete=models.PROTECT)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)

    # Part of reported totals whose input/output breakdown was unavailable.
    unsplit_tokens = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "model"], name="unique_user_model_usage"
            )
        ]
