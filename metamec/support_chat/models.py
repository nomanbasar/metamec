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
    


def default_support_call_types():
    return ["phone_call", "live_chat"]


def support_agent_avatar_path(instance, filename):
    original_name = os.path.basename(filename)
    safe_name = original_name.replace(" ", "_")
    return f"support_agents/{instance.id}/{uuid.uuid4()}_{safe_name}"


class SupportAgent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="support_agent_profile",
        blank=True,
        null=True,
    )

    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True, null=True)
    phone_number = models.CharField(max_length=40, blank=True, null=True)

    title = models.CharField(max_length=150, default="Senior Loan Advisor")
    speciality = models.CharField(max_length=150, default="Homeowner Loans")

    rating = models.DecimalField(max_digits=3, decimal_places=1, default=4.9)
    reviews_count = models.PositiveIntegerField(default=312)

    avatar = models.FileField(upload_to=support_agent_avatar_path, blank=True, null=True)

    available_call_types = models.JSONField(default=default_support_call_types)
    is_active = models.BooleanField(default=True)

    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class AgentAvailability(models.Model):
    WEEKDAY_MONDAY = 0
    WEEKDAY_TUESDAY = 1
    WEEKDAY_WEDNESDAY = 2
    WEEKDAY_THURSDAY = 3
    WEEKDAY_FRIDAY = 4
    WEEKDAY_SATURDAY = 5
    WEEKDAY_SUNDAY = 6

    WEEKDAY_CHOICES = (
        (WEEKDAY_MONDAY, "Monday"),
        (WEEKDAY_TUESDAY, "Tuesday"),
        (WEEKDAY_WEDNESDAY, "Wednesday"),
        (WEEKDAY_THURSDAY, "Thursday"),
        (WEEKDAY_FRIDAY, "Friday"),
        (WEEKDAY_SATURDAY, "Saturday"),
        (WEEKDAY_SUNDAY, "Sunday"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    agent = models.ForeignKey(
        SupportAgent,
        on_delete=models.CASCADE,
        related_name="availability_rules",
    )

    weekday = models.PositiveSmallIntegerField(choices=WEEKDAY_CHOICES)

    start_time = models.TimeField()
    end_time = models.TimeField()

    slot_duration_minutes = models.PositiveIntegerField(default=30)

    break_start_time = models.TimeField(blank=True, null=True)
    break_end_time = models.TimeField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["weekday", "start_time"]
        indexes = [
            models.Index(fields=["agent", "weekday", "is_active"]),
        ]

    def __str__(self):
        return f"{self.agent.name} - {self.get_weekday_display()} {self.start_time}-{self.end_time}"


class SupportAppointment(models.Model):
    CALL_PHONE = "phone_call"
    CALL_LIVE_CHAT = "live_chat"

    CALL_TYPE_CHOICES = (
        (CALL_PHONE, "Phone Call"),
        (CALL_LIVE_CHAT, "Live Chat"),
    )

    STATUS_SCHEDULED = "scheduled"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_MISSED = "missed"
    STATUS_RESCHEDULED = "rescheduled"

    STATUS_CHOICES = (
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_MISSED, "Missed"),
        (STATUS_RESCHEDULED, "Rescheduled"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="support_appointments",
    )

    agent = models.ForeignKey(
        SupportAgent,
        on_delete=models.CASCADE,
        related_name="appointments",
    )

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.SET_NULL,
        related_name="support_appointments",
        blank=True,
        null=True,
    )

    call_type = models.CharField(max_length=30, choices=CALL_TYPE_CHOICES)

    appointment_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)

    note = models.TextField(blank=True, null=True)
    cancel_reason = models.TextField(blank=True, null=True)

    reminder_minutes_before = models.PositiveIntegerField(default=30)

    cancelled_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    rescheduled_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["appointment_date", "start_time"]
        indexes = [
            models.Index(fields=["customer", "appointment_date"]),
            models.Index(fields=["agent", "appointment_date", "start_time"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.customer} - {self.agent.name} - {self.appointment_date} {self.start_time}"



def chat_template_attachment_path(instance, filename):
    original_name = os.path.basename(filename)
    safe_name = original_name.replace(" ", "_")
    return f"chat_templates/{instance.id}/{uuid.uuid4()}_{safe_name}"


class ChatTemplateFolder(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(max_length=255)

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="subfolders",
        blank=True,
        null=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_chat_template_folders",
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ChatTemplate(models.Model):
    CATEGORY_MARKETING = "marketing"
    CATEGORY_UTILITY = "utility"

    CATEGORY_CHOICES = (
        (CATEGORY_MARKETING, "Marketing"),
        (CATEGORY_UTILITY, "Utility"),
    )

    HEADER_HEADLINE = "headline"
    HEADER_IMAGE = "image"
    HEADER_VIDEO = "video"
    HEADER_PDF = "pdf"

    HEADER_TYPE_CHOICES = (
        (HEADER_HEADLINE, "Headline"),
        (HEADER_IMAGE, "Image"),
        (HEADER_VIDEO, "Video"),
        (HEADER_PDF, "PDF"),
    )

    STATUS_DRAFT = "draft"
    STATUS_PENDING_REVIEW = "pending_review"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_PENDING_REVIEW, "Pending Review"),
    )

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(max_length=512)

    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
    )

    language = models.CharField(max_length=50)

    message = models.TextField(max_length=1024)

    header_type = models.CharField(
        max_length=20,
        choices=HEADER_TYPE_CHOICES,
        blank=True,
        null=True,
    )

    header_text = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    header_file = models.FileField(
        upload_to=chat_template_attachment_path,
        blank=True,
        null=True,
    )

    footer_text = models.CharField(
        max_length=60,
        blank=True,
        null=True,
    )

    buttons = models.JSONField(default=list, blank=True)

    folder = models.ForeignKey(
        ChatTemplateFolder,
        on_delete=models.SET_NULL,
        related_name="templates",
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_chat_templates",
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name 