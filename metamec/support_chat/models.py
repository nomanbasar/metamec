import os
import uuid

from django.conf import settings
from django.db import models

from loan_applications.models import LoanApplication


def chat_attachment_path(instance, filename):
    original_name = os.path.basename(filename)
    safe_name = original_name.replace(" ", "_")
    conversation_id = instance.conversation_id or "conversation"
    return f"chat/{conversation_id}/{uuid.uuid4()}_{safe_name}"


class ChatConversation(models.Model):
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = (
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="customer_chat_conversations",
    )

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="admin_chat_conversations",
        blank=True,
        null=True,
    )

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.SET_NULL,
        related_name="chat_conversations",
        blank=True,
        null=True,
    )

    title = models.CharField(max_length=180, default="Support Chat")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)

    last_message = models.CharField(max_length=500, blank=True, null=True)
    last_message_at = models.DateTimeField(blank=True, null=True)

    customer_last_read_at = models.DateTimeField(blank=True, null=True)
    admin_last_read_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["admin", "status"]),
            models.Index(fields=["last_message_at"]),
        ]

    def __str__(self):
        return f"{self.title} - {self.customer}"


class ChatMessage(models.Model):
    MESSAGE_TEXT = "text"
    MESSAGE_FILE = "file"
    MESSAGE_SYSTEM = "system"

    MESSAGE_TYPE_CHOICES = (
        (MESSAGE_TEXT, "Text"),
        (MESSAGE_FILE, "File"),
        (MESSAGE_SYSTEM, "System"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="chat_messages",
        blank=True,
        null=True,
    )

    message_type = models.CharField(
        max_length=20,
        choices=MESSAGE_TYPE_CHOICES,
        default=MESSAGE_TEXT,
    )

    message = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to=chat_attachment_path, blank=True, null=True)

    read_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["sender", "created_at"]),
        ]

    def __str__(self):
        return f"{self.conversation_id} - {self.sender} - {self.message_type}"