from django.urls import path
from .views import (
    SignupView,
    VerifyEmailView,
    ResendEmailOTPView,
    LoginView,
    ForgotPasswordView,
    VerifyPasswordResetOTPView,
    ResetPasswordView,
    ResendForgotPasswordOTPView,
    MeView,
)

urlpatterns = [
    path("signup/", SignupView.as_view(), name="signup"),
    path("verify-email/", VerifyEmailView.as_view(), name="verify_email"),
    path("resend-signup-otp/", ResendEmailOTPView.as_view(), name="resend_signup_otp"),

    path("login/", LoginView.as_view(), name="login"),
    path("me/", MeView.as_view(), name="me"),

    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot_password"),
    path("verify-reset-otp/", VerifyPasswordResetOTPView.as_view(), name="verify_reset_otp"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset_password"),
    path("resend-forgot-password-otp/", ResendForgotPasswordOTPView.as_view(), name="resend_forgot_password_otp"),
]