from django.contrib import admin

from .models import (
    AgentAvailability,
    ChatConversation,
    ChatMessage,
    SupportAgent,
    SupportAppointment,
    ChatTemplateFolder,
    ChatTemplate,
)

@admin.register(ChatConversation)
class ChatConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "admin",
        "application",
        "title",
        "status",
        "last_message_at",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "customer__full_name",
        "customer__email_address",
        "admin__full_name",
        "admin__email_address",
        "application__application_number",
        "title",
    )
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "conversation",
        "sender",
        "message_type",
        "created_at",
        "read_at",
    )
    list_filter = ("message_type", "created_at", "read_at")
    search_fields = (
        "conversation__id",
        "sender__full_name",
        "sender__email_address",
        "message",
    )
    readonly_fields = ("id", "created_at")


@admin.register(SupportAgent)
class SupportAgentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "email",
        "title",
        "speciality",
        "rating",
        "reviews_count",
        "is_active",
        "sort_order",
    )
    list_filter = ("is_active", "speciality", "created_at")
    search_fields = ("name", "email", "title", "speciality")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(AgentAvailability)
class AgentAvailabilityAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "agent",
        "weekday",
        "start_time",
        "end_time",
        "slot_duration_minutes",
        "break_start_time",
        "break_end_time",
        "is_active",
    )
    list_filter = ("weekday", "is_active")
    search_fields = ("agent__name", "agent__email")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(SupportAppointment)
class SupportAppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "agent",
        "call_type",
        "appointment_date",
        "start_time",
        "end_time",
        "status",
        "created_at",
    )
    list_filter = ("call_type", "status", "appointment_date", "created_at")
    search_fields = (
        "customer__full_name",
        "customer__email_address",
        "agent__name",
        "application__application_number",
    )
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "cancelled_at",
        "completed_at",
        "rescheduled_at",
    )


@admin.register(ChatTemplateFolder)
class ChatTemplateFolderAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "parent",
        "created_by",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "created_at",
        "updated_at",
    )

    search_fields = (
        "name",
        "created_by__email",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    ordering = ("name",)

    raw_id_fields = (
        "created_by",
    )


@admin.register(ChatTemplate)
class ChatTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "language",
        "folder",
        "status",
        "created_by",
        "created_at",
    )

    list_filter = (
        "category",
        "language",
        "status",
        "created_at",
    )

    search_fields = (
        "name",
        "message",
        "footer_text",
        "created_by__email",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )

    ordering = ("name",)

    raw_id_fields = (
        "created_by",
    )

    fieldsets = (
        (
            "Template Information",
            {
                "fields": (
                    "id",
                    "name",
                    "category",
                    "language",
                    "folder",
                    "status",
                )
            },
        ),
        (
            "Message",
            {
                "fields": (
                    "message",
                    "footer_text",
                )
            },
        ),
        (
            "Header / Attachment",
            {
                "fields": (
                    "header_type",
                    "header_text",
                    "header_file",
                )
            },
        ),
        (
            "Buttons",
            {
                "fields": (
                    "buttons",
                )
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )