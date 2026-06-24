from django.contrib import admin

from .models import AdminApplicationNote


@admin.register(AdminApplicationNote)
class AdminApplicationNoteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "created_by",
        "created_at",
    )
    list_filter = (
        "created_at",
    )
    search_fields = (
        "application__application_number",
        "note",
    )
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )