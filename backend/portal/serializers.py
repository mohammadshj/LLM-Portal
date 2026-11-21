from rest_framework import serializers

from .capabilities import runtime_model
from .models import Conversation, LanguageModel, Message


class ModelSerializer(serializers.ModelSerializer):
    reasoning_supported = serializers.BooleanField(read_only=True, allow_null=True)

    def to_representation(self, instance):
        return super().to_representation(runtime_model(instance))

    class Meta:
        model = LanguageModel
        fields = [
            "id",
            "name",
            "provider",
            "context_window",
            "max_output_tokens",
            "thinking_levels",
            "thinking_default",
            "reasoning_supported",
        ]


class MessageSerializer(serializers.ModelSerializer):
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
            "thinking_level",
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
        fields = ["id", "title", "created_at", "is_processing"]


class SendSerializer(serializers.Serializer):
    thinking = serializers.DictField(
        child=serializers.RegexField(
            r"\A[a-zA-Z0-9][a-zA-Z0-9_.-]{0,31}\Z", max_length=32
        ),
        required=False,
    )
    request_id = serializers.UUIDField(required=False)
    content = serializers.CharField(max_length=12000, trim_whitespace=True)
    model_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=3
    )

    def validate_model_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("مدل تکراری مجاز نیست.")
        return value
