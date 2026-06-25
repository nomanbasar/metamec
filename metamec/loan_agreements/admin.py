from django.contrib import admin

from .models import CoApplicantInvitation, LoanAgreement


@admin.register(LoanAgreement)
class LoanAgreementAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "borrower",
        "status",
        "co_applicant_status",
        "signed_at",
        "created_at",
    )
    list_filter = ("status", "co_applicant_status", "created_at")
    search_fields = (
        "application__application_number",
        "borrower__email_address",
        "borrower__full_name",
    )
    readonly_fields = ("id", "created_at", "updated_at", "signed_at")


@admin.register(CoApplicantInvitation)
class CoApplicantInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agreement",
        "name",
        "email",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "name",
        "email",
        "agreement__application__application_number",
    )
    readonly_fields = ("id", "token", "created_at", "updated_at", "accepted_at", "declined_at")