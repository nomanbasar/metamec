import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserNotification(models.Model):
    TYPE_APPLICATION_RECEIVED = "application_received"
    TYPE_APPLICATION_APPROVED = "application_approved"
    TYPE_APPLICATION_REJECTED = "application_rejected"
    TYPE_DOCUMENT_REQUIRED = "document_required"
    TYPE_DOCUMENT_APPROVED = "document_approved"
    TYPE_DOCUMENT_REJECTED = "document_rejected"
    TYPE_KYC_SUBMITTED = "kyc_submitted"
    TYPE_KYC_APPROVED = "kyc_approved"
    TYPE_KYC_REJECTED = "kyc_rejected"
    TYPE_CHAT_MESSAGE = "chat_message"
    TYPE_APPOINTMENT_BOOKED = "appointment_booked"
    TYPE_APPOINTMENT_REMINDER = "appointment_reminder"
    TYPE_E_SIGN_PENDING = "e_sign_pending"
    TYPE_E_SIGN_COMPLETED = "e_sign_completed"
    TYPE_CO_APPLICANT_INVITE = "co_applicant_invite"
    TYPE_PAYMENT_REMINDER = "payment_reminder"
    TYPE_GENERAL = "general"

    NOTIFICATION_TYPE_CHOICES = (
        (TYPE_APPLICATION_RECEIVED, "Application Received"),
        (TYPE_APPLICATION_APPROVED, "Application Approved"),
        (TYPE_APPLICATION_REJECTED, "Application Rejected"),
        (TYPE_DOCUMENT_REQUIRED, "Document Required"),
        (TYPE_DOCUMENT_APPROVED, "Document Approved"),
        (TYPE_DOCUMENT_REJECTED, "Document Rejected"),
        (TYPE_KYC_SUBMITTED, "KYC Submitted"),
        (TYPE_KYC_APPROVED, "KYC Approved"),
        (TYPE_KYC_REJECTED, "KYC Rejected"),
        (TYPE_CHAT_MESSAGE, "Chat Message"),
        (TYPE_APPOINTMENT_BOOKED, "Appointment Booked"),
        (TYPE_APPOINTMENT_REMINDER, "Appointment Reminder"),
        (TYPE_E_SIGN_PENDING, "E-sign Pending"),
        (TYPE_E_SIGN_COMPLETED, "E-sign Completed"),
        (TYPE_CO_APPLICANT_INVITE, "Co-applicant Invite"),
        (TYPE_PAYMENT_REMINDER, "Payment Reminder"),
        (TYPE_GENERAL, "General"),
    )

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"

    PRIORITY_CHOICES = (
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="app_notifications",
    )

    title = models.CharField(max_length=180)
    message = models.TextField()

    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPE_CHOICES,
        default=TYPE_GENERAL,
    )

    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_NORMAL,
    )

    action_screen = models.CharField(max_length=100, blank=True, null=True)
    action_api = models.CharField(max_length=255, blank=True, null=True)
    object_id = models.CharField(max_length=100, blank=True, null=True)
    object_type = models.CharField(max_length=100, blank=True, null=True)

    metadata = models.JSONField(default=dict, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "notification_type"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["notification_type"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.title}"

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at", "updated_at"])