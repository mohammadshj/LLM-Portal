from rest_framework import serializers

from .models import Conversation, LanguageModel, Message


class ModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = LanguageModel
        fields = ["id", "name", "provider", "context_window", "max_output_tokens"]


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
            "input_tokens",
            "output_tokens",
            "created_at",
        ]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at"]


class SendSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=12000, trim_whitespace=True)
    model_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=3
    )

    def validate_model_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("مدل تکراری مجاز نیست.")
        return value
