from django.contrib import admin

from .models import ChatConversation, ChatMessage


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