import uuid

from django.conf import settings
from django.db import models

from loan_applications.models import LoanApplication


class AdminApplicationNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="admin_notes",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_application_notes",
        blank=True,
        null=True,
    )

    note = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.application.application_number} - Admin Note"