import os
import uuid

from django.conf import settings
from django.db import models

from loan_applications.models import LoanApplication


def agreement_upload_path(instance, filename):
    original_name = os.path.basename(filename)
    safe_name = original_name.replace(" ", "_")

    application_number = "agreement"

    if getattr(instance, "application", None):
        application_number = instance.application.application_number or str(instance.application_id)
    elif getattr(instance, "agreement", None) and getattr(instance.agreement, "application", None):
        application_number = instance.agreement.application.application_number or str(instance.agreement.application_id)

    return f"loan_agreements/{application_number}/{uuid.uuid4()}_{safe_name}"


class LoanAgreement(models.Model):
    STATUS_AWAITING_SIGNATURE = "awaiting_signature"
    STATUS_SIGNED = "signed"

    STATUS_CHOICES = (
        (STATUS_AWAITING_SIGNATURE, "Awaiting Signature"),
        (STATUS_SIGNED, "Signed"),
    )

    CO_APPLICANT_NONE = "none"
    CO_APPLICANT_INVITED = "invited"
    CO_APPLICANT_SKIPPED = "skipped"
    CO_APPLICANT_ACCEPTED = "accepted"

    CO_APPLICANT_STATUS_CHOICES = (
        (CO_APPLICANT_NONE, "None"),
        (CO_APPLICANT_INVITED, "Invited"),
        (CO_APPLICANT_SKIPPED, "Skipped"),
        (CO_APPLICANT_ACCEPTED, "Accepted"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    application = models.OneToOneField(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="agreement",
    )

    borrower = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="loan_agreements",
    )

    lender_name = models.CharField(max_length=180, default="LoanSphere Financial Ltd.")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_AWAITING_SIGNATURE)

    signature_image = models.FileField(upload_to=agreement_upload_path, blank=True, null=True)
    signature_text = models.CharField(max_length=180, blank=True, null=True)
    accepted_terms = models.BooleanField(default=False)

    signed_pdf = models.FileField(upload_to=agreement_upload_path, blank=True, null=True)
    signed_at = models.DateTimeField(blank=True, null=True)
    signed_ip = models.GenericIPAddressField(blank=True, null=True)
    signed_user_agent = models.TextField(blank=True, null=True)

    co_applicant_status = models.CharField(
        max_length=30,
        choices=CO_APPLICANT_STATUS_CHOICES,
        default=CO_APPLICANT_NONE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.application.application_number} - {self.status}"


class CoApplicantInvitation(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_DECLINED, "Declined"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    agreement = models.ForeignKey(
        LoanAgreement,
        on_delete=models.CASCADE,
        related_name="co_applicant_invitations",
    )

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    name = models.CharField(max_length=150)
    email = models.EmailField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PENDING)

    invite_link = models.URLField(max_length=500, blank=True, null=True)
    message = models.TextField(blank=True, null=True)

    accepted_at = models.DateTimeField(blank=True, null=True)
    declined_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} - {self.email} - {self.status}"