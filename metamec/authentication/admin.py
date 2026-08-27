from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, OTP, PasswordReset


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)
    list_display = (
        "id",
        "email_address",
        "full_name",
        "phone_number",
        "role",
        "login_count",
        "is_email_verified",
        "is_staff",
        "is_active",
        "created_at",
    )
    list_filter = ("role", "is_email_verified", "is_staff", "is_active")
    search_fields = ("email_address", "full_name", "phone_number")

    fieldsets = (
        ("Login Info", {"fields": ("email_address", "password")}),
        ("Personal Info", {"fields": ("full_name", "phone_number")}),
        ("Agreement", {"fields": ("agreed_terms_business", "agreed_privacy_policy")}),
        ("Permissions", {"fields": ("role", "is_email_verified", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )

    readonly_fields = ("created_at", "updated_at", "last_login")

    add_fieldsets = (
        ("Create User", {
            "classes": ("wide",),
            "fields": (
                "email_address",
                "full_name",
                "phone_number",
                "password1",
                "password2",
                "role",
                "is_email_verified",
                "is_staff",
                "is_active",
            ),
        }),
    )


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ("id","email_address", "otp_code", "otp_type", "is_verified", "expires_at", "created_at")
    search_fields = ("email_address", "otp_code")
    list_filter = ("otp_type", "is_verified")


@admin.register(PasswordReset)
class PasswordResetAdmin(admin.ModelAdmin):
    list_display = ("id","user", "is_used", "expires_at", "used_at", "created_at")
    list_filter = ("is_used",)