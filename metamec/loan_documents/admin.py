from django.contrib import admin

from .models import LoanApplicationDocument


@admin.register(LoanApplicationDocument)
class LoanApplicationDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "document_type",
        "original_file_name",
        "file_size",
        "status",
        "uploaded_at",
    )
    list_filter = (
        "document_type",
        "status",
        "uploaded_at",
    )
    search_fields = (
        "application__application_number",
        "application__user__email_address",
        "application__user__full_name",
        "original_file_name",
    )
    readonly_fields = (
        "id",
        "uploaded_at",
        "updated_at",
    )