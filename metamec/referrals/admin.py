from django.contrib import admin

from .models import ReferralProfile, ReferralRecord


@admin.register(ReferralProfile)
class ReferralProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "referral_code",
        "is_active",
        "created_at",
    )
    search_fields = (
        "user__full_name",
        "user__email_address",
        "referral_code",
    )
    list_filter = ("is_active", "created_at")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ReferralRecord)
class ReferralRecordAdmin(admin.ModelAdmin):
    list_display = (
        "referrer",
        "referred_user",
        "status",
        "referral_code_snapshot",
        "signup_at",
        "joined_at",
    )
    search_fields = (
        "referrer__full_name",
        "referrer__email_address",
        "referred_user__full_name",
        "referred_user__email_address",
        "referral_code_snapshot",
    )
    list_filter = ("status", "signup_at", "joined_at")
    readonly_fields = (
        "id",
        "signup_at",
        "joined_at",
        "created_at",
        "updated_at",
    )