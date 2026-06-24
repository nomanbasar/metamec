import re
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from loan_management.models import LoanType


class LoanApplication(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_PENDING_DOCUMENTS = "pending_documents"
    STATUS_KYC_REQUIRED = "kyc_required"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_PENDING_DOCUMENTS, "Pending Documents"),
        (STATUS_KYC_REQUIRED, "KYC Required"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_COMPLETED, "Completed"),
    )

    EMPLOYMENT_EMPLOYED = "employed"
    EMPLOYMENT_SELF_EMPLOYED = "self_employed"
    EMPLOYMENT_OTHER = "other"

    EMPLOYMENT_CHOICES = (
        (EMPLOYMENT_EMPLOYED, "Employed"),
        (EMPLOYMENT_SELF_EMPLOYED, "Self-employed"),
        (EMPLOYMENT_OTHER, "Other"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="loan_applications",
    )

    loan_type = models.ForeignKey(
        LoanType,
        on_delete=models.PROTECT,
        related_name="applications",
    )

    application_number = models.CharField(max_length=30, unique=True, blank=True)

    # Step 2: Loan Details
    loan_amount = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    loan_term = models.CharField(max_length=80, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    # Step 3: Property Details
    property_value = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    mortgage_balance = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    mortgage_payment = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)
    mortgage_lender = models.CharField(max_length=180, blank=True, null=True)
    term_remaining = models.CharField(max_length=80, blank=True, null=True)
    interest_rate = models.CharField(max_length=50, blank=True, null=True)

    # Step 4: Employment Info
    employment_type = models.CharField(
        max_length=30,
        choices=EMPLOYMENT_CHOICES,
        blank=True,
        null=True,
    )
    annual_income = models.DecimalField(max_digits=14, decimal_places=2, blank=True, null=True)

    # Step 5: Credit History
    has_ccj = models.BooleanField(blank=True, null=True)
    has_defaults = models.BooleanField(blank=True, null=True)
    has_active_dmp = models.BooleanField(blank=True, null=True)
    has_active_iva = models.BooleanField(blank=True, null=True)

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    current_step = models.PositiveIntegerField(default=1)

    submitted_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    TOTAL_STEPS = 6

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.application_number or str(self.id)

    def save(self, *args, **kwargs):
        if not self.application_number:
            self.application_number = self.generate_application_number()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_application_number():
        year = timezone.now().year
        prefix = f"LS-{year}-"

        last_application = (
            LoanApplication.objects
            .filter(application_number__startswith=prefix)
            .order_by("-created_at")
            .first()
        )

        next_number = 1

        if last_application and last_application.application_number:
            match = re.search(r"(\d+)$", last_application.application_number)
            if match:
                next_number = int(match.group(1)) + 1

        while True:
            application_number = f"{prefix}{next_number:03d}"
            if not LoanApplication.objects.filter(application_number=application_number).exists():
                return application_number
            next_number += 1

    @property
    def progress_percent(self):
        step = self.current_step or 1

        if step < 1:
            step = 1

        if step > self.TOTAL_STEPS:
            step = self.TOTAL_STEPS

        return int(round((step / self.TOTAL_STEPS) * 100))