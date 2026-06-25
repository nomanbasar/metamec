from django.contrib import admin

from .models import CustomerKYC


@admin.register(CustomerKYC)
class CustomerKYCAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "application",
        "document_type",
        "status",
        "provider",
        "created_at",
    )
    list_filter = ("status", "provider", "document_type")
    search_fields = (
        "user__email_address",
        "user__full_name",
        "application__application_number",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "submitted_at",
        "reviewed_at",
    )