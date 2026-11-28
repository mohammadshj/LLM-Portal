from rest_framework import serializers

from .capabilities import runtime_model
from .models import Conversation, LanguageModel, Message


class ModelSerializer(serializers.ModelSerializer):
    reasoning_profile = serializers.SerializerMethodField()

    def get_reasoning_profile(self, model):
        return model.reasoning_profile.public()

    reasoning_supported = serializers.BooleanField(read_only=True, allow_null=True)

    def to_representation(self, instance):
        model = runtime_model(instance)
        data = super().to_representation(model)
        if (
            self.context.get("request")
            and self.context["request"].query_params.get("catalog") == "1"
        ):
            conn = instance.connection
            data["provider_group"] = (
                conn.get_discovery_type_display()
                if conn
                else instance.get_provider_display()
            )
            data["available"] = (
                model.can_chat
                and data["reasoning_profile"]["available"]
                and (instance.provider == "demo" or bool(conn and conn.enabled))
            )
        return data

    class Meta:
        model = LanguageModel
        fields = [
            "id",
            "name",
            "provider",
            "input_price_per_million_rial",
            "output_price_per_million_rial",
            "context_window",
            "max_output_tokens",
            "thinking_levels",
            "thinking_default",
            "reasoning_supported",
            "reasoning_profile",
        ]


class MessageSerializer(serializers.ModelSerializer):
    free_tariff = serializers.SerializerMethodField()

    def get_free_tariff(self, obj):
        return obj.input_price_snapshot_rial == obj.output_price_snapshot_rial == 0

    elapsed_ms = serializers.IntegerField(read_only=True, allow_null=True)

    model_name = serializers.CharField(
        source="model.name", default=None, read_only=True
    )

    class Meta:
        model = Message
        fields = [
            "id",
            "role",
            "content",
            "model_name",
            "model_id",
            "parent_id",
            "status",
            "request_id",
            "error",
            "usage_source",
            "elapsed_ms",
            "cost_rial",
            "free_tariff",
            "feedback",
            "cached_input_tokens",
            "limited_output_tokens",
            "input_price_snapshot_rial",
            "output_price_snapshot_rial",
            "billing_status",
            "billing_source",
            "thinking_level",
            "reasoning_settings",
            "reasoning_content",
            "reasoning_tokens",
            "total_tokens",
            "input_tokens",
            "output_tokens",
            "created_at",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    is_processing = serializers.BooleanField(read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at", "is_processing", "pinned"]


class BranchSelectionSerializer(serializers.Serializer):
    version_id = serializers.IntegerField(min_value=1)
    expected_leaf = serializers.IntegerField(
        min_value=1, allow_null=True, required=False
    )


class SendSerializer(serializers.Serializer):
    edit_of = serializers.IntegerField(min_value=1, required=False)
    expected_leaf = serializers.IntegerField(
        min_value=1, allow_null=True, required=False
    )
    reasoning = serializers.DictField(child=serializers.DictField(), required=False)
    thinking = serializers.DictField(
        child=serializers.RegexField(
            r"\A[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}\Z", max_length=32
        ),
        required=False,
    )
    request_id = serializers.UUIDField(required=False)
    content = serializers.CharField(max_length=12000, trim_whitespace=True)
    model_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=3,
        required=False,
    )

    def validate_model_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("مدل تکراری مجاز نیست.")
        return value
