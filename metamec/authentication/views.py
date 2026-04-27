from datetime import timedelta
import random

from django.utils import timezone
from django.core.mail import send_mail
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from .models import OTP, PasswordReset
from .serializers import SignupSerializer, LoginSerializer

User = get_user_model()


def generate_otp():
    return str(random.randint(100000, 999999))


def create_otp(user, otp_type):
    otp = OTP.objects.create(
        user=user,
        email_address=user.email_address,
        otp_code=generate_otp(),
        otp_type=otp_type,
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    send_mail(
        subject="LoanSphere Verification Code",
        message=f"Your verification code is: {otp.otp_code}",
        from_email="noreply@loansphere.com",
        recipient_list=[user.email_address],
        fail_silently=False,
    )

    return otp


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)

    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)

        if serializer.is_valid():
            user = serializer.save()
            otp = create_otp(user, "email_verification")

            return Response(
                {
                    "message": "Account created successfully. Verification OTP sent.",
                    "user_id": str(user.id),
                    "email_address": user.email_address,
                    "dev_otp": otp.otp_code,
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")
        otp_code = request.data.get("otp_code")

        try:
            user = User.objects.get(email_address=email_address)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        otp = OTP.objects.filter(
            user=user,
            otp_code=otp_code,
            otp_type="email_verification",
            is_verified=False,
        ).order_by("-created_at").first()

        if not otp:
            return Response({"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if otp.is_expired():
            return Response({"error": "OTP expired."}, status=status.HTTP_400_BAD_REQUEST)

        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save()

        user.is_email_verified = True
        user.save()

        return Response({"message": "Email verified successfully."}, status=status.HTTP_200_OK)


class ResendEmailOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")

        try:
            user = User.objects.get(email_address=email_address)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_email_verified:
            return Response({"message": "Email already verified."}, status=status.HTTP_200_OK)

        otp = create_otp(user, "email_verification")

        return Response(
            {
                "message": "New OTP sent.",
                "dev_otp": otp.otp_code,
            },
            status=status.HTTP_200_OK,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})

        if serializer.is_valid():
            user = serializer.validated_data["user"]

            if not user.is_email_verified:
                return Response(
                    {"error": "Please verify your email before login."},
                    status=status.HTTP_403_FORBIDDEN,
                )

            tokens = get_tokens_for_user(user)

            return Response(
                {
                    "message": "Login successful.",
                    "user": {
                        "id": str(user.id),
                        "full_name": user.full_name,
                        "email_address": user.email_address,
                        "phone_number": user.phone_number,
                        "role": user.role,
                        "is_admin": user.is_staff or user.is_superuser,
                    },
                    "tokens": tokens,
                },
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")

        try:
            user = User.objects.get(email_address=email_address)
        except User.DoesNotExist:
            return Response(
                {"message": "If this email exists, reset OTP has been sent."},
                status=status.HTTP_200_OK,
            )

        otp = create_otp(user, "password_reset")

        PasswordReset.objects.create(
            user=user,
            otp=otp,
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        return Response(
            {
                "message": "Reset OTP sent.",
                "dev_otp": otp.otp_code,
            },
            status=status.HTTP_200_OK,
        )


class VerifyPasswordResetOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")
        otp_code = request.data.get("otp_code")

        try:
            user = User.objects.get(email_address=email_address)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        otp = OTP.objects.filter(
            user=user,
            otp_code=otp_code,
            otp_type="password_reset",
            is_verified=False,
        ).order_by("-created_at").first()

        if not otp:
            return Response({"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if otp.is_expired():
            return Response({"error": "OTP expired."}, status=status.HTTP_400_BAD_REQUEST)

        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save()

        return Response({"message": "OTP verified. You can reset password now."}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")
        otp_code = request.data.get("otp_code")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if new_password != confirm_password:
            return Response({"error": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        if not new_password or len(new_password) < 8:
            return Response({"error": "Password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email_address=email_address)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        otp = OTP.objects.filter(
            user=user,
            otp_code=otp_code,
            otp_type="password_reset",
            is_verified=True,
        ).order_by("-created_at").first()

        if not otp:
            return Response({"error": "OTP verification required."}, status=status.HTTP_400_BAD_REQUEST)

        password_reset = PasswordReset.objects.filter(
            user=user,
            otp=otp,
            is_used=False,
        ).order_by("-created_at").first()

        if not password_reset:
            return Response({"error": "Invalid reset request."}, status=status.HTTP_400_BAD_REQUEST)

        if password_reset.is_expired():
            return Response({"error": "Reset request expired."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()

        password_reset.is_used = True
        password_reset.used_at = timezone.now()
        password_reset.save()

        return Response({"message": "Password reset successful."}, status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        return Response(
            {
                "id": str(user.id),
                "full_name": user.full_name,
                "email_address": user.email_address,
                "phone_number": user.phone_number,
                "role": user.role,
                "is_email_verified": user.is_email_verified,
                "is_admin": user.is_staff or user.is_superuser,
            },
            status=status.HTTP_200_OK,
        )