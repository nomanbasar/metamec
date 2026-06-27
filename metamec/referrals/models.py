import random
import string
import uuid

from django.conf import settings
from django.db import models


class ReferralProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_profile",
    )

    referral_code = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["referral_code"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.referral_code}"


class ReferralRecord(models.Model):
    STATUS_PENDING = "pending"
    STATUS_JOINED_ACTIVE = "joined_active"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_JOINED_ACTIVE, "Joined & Active"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_records_sent",
    )

    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="referral_record_received",
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    referral_code_snapshot = models.CharField(max_length=20)
    referral_link_snapshot = models.URLField(max_length=500)

    signup_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["referrer", "status"]),
            models.Index(fields=["referred_user"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["referred_user"],
                name="unique_referral_record_per_referred_user",
            )
        ]

    def __str__(self):
        return f"{self.referrer} -> {self.referred_user} - {self.status}"