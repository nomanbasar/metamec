from django.contrib import admin

from .models import UserNotification


@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "title",
        "notification_type",
        "priority",
        "is_read",
        "created_at",
    )
    list_filter = (
        "notification_type",
        "priority",
        "is_read",
        "created_at",
    )
    search_fields = (
        "user__full_name",
        "user__email_address",
        "user__email",
        "title",
        "message",
        "object_id",
        "object_type",
    )
    readonly_fields = ("id", "created_at", "updated_at", "read_at")