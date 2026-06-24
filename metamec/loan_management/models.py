import uuid
from django.conf import settings
from django.db import models


class LoanTemplate(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"

    STATUS_CHOICES = (
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180, unique=True)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_loan_templates",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class LoanTemplateSection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    template = models.ForeignKey(
        LoanTemplate,
        on_delete=models.CASCADE,
        related_name="sections",
    )

    title = models.CharField(max_length=180)
    description = models.TextField()
    order = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"{self.template.name} - {self.title}"


class LoanType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=120, unique=True)

    # Figma অনুযায়ী icon image হবে
    icon_image = models.FileField(upload_to="loan_type_icons/", blank=True, null=True)

    description = models.TextField(blank=True, null=True)

    template = models.ForeignKey(
        LoanTemplate,
        on_delete=models.PROTECT,
        related_name="loan_types",
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_loan_types",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name