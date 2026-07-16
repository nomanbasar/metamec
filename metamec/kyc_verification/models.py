import os
import uuid

from django.conf import settings
from django.db import models

from loan_applications.models import LoanApplication


def kyc_upload_path(instance, filename):
    original_name = os.path.basename(filename)
    safe_name = original_name.replace(" ", "_")
    user_id = instance.user_id or "unknown_user"
    return f"kyc/{user_id}/{uuid.uuid4()}_{safe_name}"


class CustomerKYC(models.Model):
    DOC_DRIVING_LICENSE = "driving_license"
    DOC_PASSPORT = "passport"

    DOCUMENT_TYPE_CHOICES = (
        (DOC_DRIVING_LICENSE, "Driving License"),
        (DOC_PASSPORT, "Passport"),
    )

    STATUS_NOT_STARTED = "not_started"
    STATUS_ID_UPLOADED = "id_uploaded"
    STATUS_SELFIE_UPLOADED = "selfie_uploaded"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = (
        (STATUS_NOT_STARTED, "Not Started"),
        (STATUS_ID_UPLOADED, "ID Uploaded"),
        (STATUS_SELFIE_UPLOADED, "Selfie Uploaded"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    )

    PROVIDER_MOCK = "mock"
    PROVIDER_ONFIDO = "onfido"
    PROVIDER_COMPLIANCE_ASSIST = "complianceassist"

    PROVIDER_CHOICES = (
        (PROVIDER_MOCK, "Mock"),
        (PROVIDER_ONFIDO, "Onfido"),
        (PROVIDER_COMPLIANCE_ASSIST, "ComplianceAssist"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kyc_verifications",
    )

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.SET_NULL,
        related_name="kyc_verifications",
        blank=True,
        null=True,
    )

    document_type = models.CharField(
        max_length=40,
        choices=DOCUMENT_TYPE_CHOICES,
        blank=True,
        null=True,
    )

    id_front_image = models.FileField(upload_to=kyc_upload_path, blank=True, null=True)
    id_back_image = models.FileField(upload_to=kyc_upload_path, blank=True, null=True)
    selfie_image = models.FileField(upload_to=kyc_upload_path, blank=True, null=True)

    provider = models.CharField(
        max_length=30,
        choices=PROVIDER_CHOICES,
        default=PROVIDER_MOCK,
    )

    provider_applicant_id = models.CharField(max_length=120, blank=True, null=True)
    provider_document_id = models.CharField(max_length=120, blank=True, null=True)
    provider_selfie_id = models.CharField(max_length=120, blank=True, null=True)
    provider_check_id = models.CharField(max_length=120, blank=True, null=True)
    provider_response = models.JSONField(blank=True, null=True)

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_STARTED,
    )

    submitted_at = models.DateTimeField(blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_kyc_verifications",
        blank=True,
        null=True,
    )

    admin_note = models.TextField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} - {self.status}"

    @property
    def has_id_documents(self):
        return bool(self.document_type and self.id_front_image and self.id_back_image)

    @property
    def has_selfie(self):
        return bool(self.selfie_image)

    # @property
    # def can_submit(self):
    #     return bool(
    #         self.has_id_documents
    #         and self.has_selfie
    #         and self.status not in [
    #             self.STATUS_UNDER_REVIEW,
    #             self.STATUS_APPROVED,
    #         ]
    #     )

    @property
    def can_submit(self):
        if self.provider == self.PROVIDER_COMPLIANCE_ASSIST:
            return bool(
                not self.provider_check_id
                and self.status not in [
                    self.STATUS_UNDER_REVIEW,
                    self.STATUS_APPROVED,
                ]
            )

        return bool(
            self.has_id_documents
            and self.has_selfie
            and self.status not in [
                self.STATUS_UNDER_REVIEW,
                self.STATUS_APPROVED,
            ]
        )
    



