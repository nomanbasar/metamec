import os
import uuid

from django.db import models

from loan_applications.models import LoanApplication


def loan_document_upload_path(instance, filename):
    original_name = os.path.basename(filename)
    safe_name = original_name.replace(" ", "_")
    application_number = instance.application.application_number or str(instance.application.id)
    return f"loan_documents/{application_number}/{uuid.uuid4()}_{safe_name}"


class LoanApplicationDocument(models.Model):
    DOC_PASSPORT_DRIVING_LICENSE = "passport_driving_license"
    DOC_RECENT_PHOTOGRAPH = "recent_photograph"
    DOC_PAYSLIPS_3_MONTHS = "payslips_3_months"
    DOC_LATEST_TAX_RETURN = "latest_tax_return"
    DOC_BANK_STATEMENT = "bank_statement"

    DOCUMENT_TYPE_CHOICES = (
        (DOC_PASSPORT_DRIVING_LICENSE, "Passport / Driving License"),
        (DOC_RECENT_PHOTOGRAPH, "Recent Photograph"),
        (DOC_PAYSLIPS_3_MONTHS, "Last 3 Months Payslips"),
        (DOC_LATEST_TAX_RETURN, "Latest Tax Return"),
        (DOC_BANK_STATEMENT, "Bank Statement"),
    )

    STATUS_UPLOADED = "uploaded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="documents",
    )

    document_type = models.CharField(max_length=80, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to=loan_document_upload_path)

    original_file_name = models.CharField(max_length=255, blank=True, null=True)
    file_size = models.PositiveIntegerField(default=0)
    mime_type = models.CharField(max_length=120, blank=True, null=True)

    status = models.CharField(max_length=30, default=STATUS_UPLOADED)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["uploaded_at"]
        unique_together = ("application", "document_type")

    def __str__(self):
        return f"{self.application.application_number} - {self.document_type}"