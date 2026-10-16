from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Assistant, Conversation, CrawlJob, Message, Source


User = get_user_model()


class RegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=10, max_length=128)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value


class ProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()


class AssistantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assistant
        fields = [
            "id", "public_id", "name", "description", "instructions", "language", "tone",
            "welcome_message", "fallback_response", "is_active", "widget_enabled", "widget_color",
            "retrieval_top_k", "similarity_threshold", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "public_id", "created_at", "updated_at"]

    def validate_widget_color(self, value):
        import re
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise serializers.ValidationError("Enter a six-digit hexadecimal color.")
        return value


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = ["id", "kind", "title", "url", "status", "error_message", "created_at"]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    assistant_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "assistant_id", "channel", "created_at", "updated_at"]
        read_only_fields = fields


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "created_at"]
        read_only_fields = fields


class CrawlJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = CrawlJob
        fields = ["id", "start_url", "mode", "status", "discovered_pages", "error_message", "created_at", "updated_at"]
        read_only_fields = fields


class CrawlJobCreateSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=2048)
    mode = serializers.ChoiceField(choices=["manual", "automatic"], default="manual")


class CrawlProcessSerializer(serializers.Serializer):
    selected_urls = serializers.ListField(
        child=serializers.URLField(max_length=2048),
        allow_empty=False,
        max_length=500,
    )


class SourceCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["text"], required=False)
    title = serializers.CharField(max_length=255, required=False)
    content = serializers.CharField(max_length=2_000_000, required=False)
    file = serializers.FileField(required=False)


class WidgetInitRequestSerializer(serializers.Serializer):
    assistant_id = serializers.UUIDField()
    conversation_id = serializers.UUIDField(required=False)


class WidgetInitResponseSerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField()
    assistant_name = serializers.CharField()
    welcome_message = serializers.CharField()
    color = serializers.CharField()
    messages = MessageSerializer(many=True)


class WidgetMessageRequestSerializer(serializers.Serializer):
    assistant_id = serializers.UUIDField()
    conversation_id = serializers.UUIDField()
    question = serializers.CharField(max_length=12000, trim_whitespace=True)


class WidgetMessageResponseSerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField()
    answer = serializers.CharField()
    sources = serializers.ListField(child=serializers.DictField(), required=False)
    usage = serializers.DictField(required=False)


class TelegramConnectRequestSerializer(serializers.Serializer):
    bot_token = serializers.CharField(write_only=True, max_length=1024)


class TelegramStatusSerializer(serializers.Serializer):
    connected = serializers.BooleanField()
    bot_username = serializers.CharField(allow_blank=True)
    webhook_configured = serializers.BooleanField()
    last_error = serializers.CharField(allow_blank=True)


class TelegramWebhookSerializer(serializers.Serializer):
    update_id = serializers.IntegerField()
    message = serializers.JSONField()


class TelegramWebhookResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    duplicate = serializers.BooleanField(required=False)
    ignored = serializers.BooleanField(required=False)
