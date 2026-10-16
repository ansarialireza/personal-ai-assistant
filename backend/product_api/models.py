import uuid

from django.conf import settings
from django.db import models


class Assistant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistants")
    remote_assistant_id = models.UUIDField(unique=True)
    remote_knowledge_base_id = models.PositiveBigIntegerField()
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    language = models.CharField(max_length=64, default="English")
    tone = models.CharField(max_length=64, default="Helpful")
    welcome_message = models.CharField(max_length=500, default="Hi! How can I help?")
    fallback_response = models.CharField(max_length=500, default="I don't have enough information to answer that.")
    is_active = models.BooleanField(default=True)
    widget_enabled = models.BooleanField(default=False)
    widget_color = models.CharField(max_length=7, default="#CCFF00")
    retrieval_top_k = models.PositiveSmallIntegerField(default=5)
    similarity_threshold = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class Source(models.Model):
    class Kind(models.TextChoices):
        TEXT = "text", "Text"
        FILE = "file", "File"
        WEBSITE = "website", "Website"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        INDEXED = "indexed", "Indexed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assistant = models.ForeignKey(Assistant, on_delete=models.CASCADE, related_name="sources")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=255)
    url = models.URLField(max_length=2048, blank=True)
    content = models.TextField(blank=True)
    remote_document_id = models.PositiveBigIntegerField(null=True, blank=True)
    file_path = models.CharField(max_length=1024, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assistant = models.ForeignKey(Assistant, on_delete=models.CASCADE, related_name="conversations")
    remote_conversation_id = models.UUIDField(null=True, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    channel = models.CharField(max_length=32, default="web")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["assistant", "channel", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_assistant_channel_external_conversation",
            )
        ]


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField(max_length=12000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class CrawlJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DISCOVERING = "discovering", "Discovering"
        DISCOVERED = "discovered", "Discovered"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Mode(models.TextChoices):
        MANUAL = "manual", "Manual selection"
        AUTOMATIC = "automatic", "Automatic"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assistant = models.ForeignKey(Assistant, on_delete=models.CASCADE, related_name="crawl_jobs")
    start_url = models.URLField(max_length=2048)
    mode = models.CharField(max_length=16, choices=Mode.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    discovered_pages = models.JSONField(default=list)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ChannelConnection(models.Model):
    assistant = models.OneToOneField(Assistant, on_delete=models.CASCADE, related_name="telegram")
    encrypted_bot_token = models.TextField()
    webhook_secret_hash = models.CharField(max_length=64)
    bot_username = models.CharField(max_length=255, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)


class ChannelEvent(models.Model):
    connection = models.ForeignKey(ChannelConnection, on_delete=models.CASCADE, related_name="events")
    update_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["connection", "update_id"], name="unique_telegram_update")
        ]
