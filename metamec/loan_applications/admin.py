from django.contrib import admin

from .models import LoanApplication


@admin.register(LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application_number",
        "user",
        "loan_type",
        "loan_amount",
        "loan_term",
        "status",
        "current_step",
        "submitted_at",
        "created_at",
    )
    list_filter = (
        "status",
        "loan_type",
        "employment_type",
        "created_at",
    )
    search_fields = (
        "application_number",
        "user__email_address",
        "user__full_name",
        "loan_type__name",
    )
    readonly_fields = (
        "id",
        "application_number",
        "created_at",
        "updated_at",
        "submitted_at",
    )