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
from django.db import transaction
from .utils import build_response
from .models import OTP, PasswordReset
from .serializers import SignupSerializer, LoginSerializer
from django.contrib.auth import authenticate
from .models import PasswordReset
from .utils import build_response
from .models import OTP
from .utils import build_response
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.permissions import IsAuthenticated
from loan_applications.models import LoanApplication
User = get_user_model()


def generate_otp():
    return str(random.randint(100000, 999999))


def create_otp(user, otp_type):
    otp = OTP.objects.create(
        user=user,
        email_address=user.email_address,
        otp_code=generate_otp(),
        otp_type=otp_type,
        expires_at=timezone.now() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
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

    @transaction.atomic
    def post(self, request):
        serializer = SignupSerializer(data=request.data)

        if not serializer.is_valid():
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()
        create_otp(user, "email_verification")

        return build_response(
            request,
            success=True,
            message="Signup successful. OTP sent to email.",
            data={
                "user_id": str(user.id),
                "email_address": user.email_address,
            },
            status_code=status.HTTP_201_CREATED,
        )


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")
        otp_code = request.data.get("otp_code")

        if not email_address or not otp_code:
            return build_response(
                request,
                success=False,
                message="Email address and OTP code are required",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email_address=email_address)
        except User.DoesNotExist:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        otp = OTP.objects.filter(
            user=user,
            email_address=email_address,
            otp_code=otp_code,
            otp_type="email_verification",
            is_verified=False,
        ).order_by("-created_at").first()

        if not otp:
            return build_response(
                request,
                success=False,
                message="Invalid OTP",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        
        if otp.attempt_count >= settings.OTP_MAX_ATTEMPTS:
            return build_response(
                request,
                success=False,
                message="Maximum OTP attempt limit reached",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if otp.is_expired():
            return build_response(
                request,
                success=False,
                message="OTP expired",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save()

        user.is_email_verified = True
        user.save()

        return build_response(
            request,
            success=True,
            message="Email verified successfully",
            data={
                "user_id": user.id,
                "email_address": user.email_address,
                "is_email_verified": user.is_email_verified,
            },
            status_code=status.HTTP_200_OK,
        )


class ResendEmailOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")

        if not email_address:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "email_address": ["This field is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        email_address = email_address.lower()
        purpose = "email_verify"

        user = User.objects.filter(email_address=email_address).first()
        if not user:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if user.is_email_verified:
            return build_response(
                request,
                success=False,
                message="Email already verified",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        last_otp = OTP.objects.filter(
            user=user,
            otp_type="email_verification",
        ).order_by("-created_at").first()

        if last_otp and last_otp.resend_count >= settings.OTP_MAX_RESEND:
            return build_response(
                request,
                success=False,
                message="Maximum OTP resend limit reached",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        resend_count = last_otp.resend_count if last_otp else 0

        otp = create_otp(user, "email_verification")
        otp.resend_count = resend_count + 1
        otp.save(update_fields=["resend_count"])

        return build_response(
            request,
            success=True,
            message="OTP resent successfully",
            data={
                "email_address": user.email_address,
                "purpose": purpose,
            },
            status_code=status.HTTP_200_OK,
        )

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")
        password = request.data.get("password")

        if not email_address or not password:
            return build_response(
                request,
                success=False,
                message="Email and password are required",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(
            request=request,
            username=email_address,
            password=password,
        )

        if not user:
            return build_response(
                request,
                success=False,
                message="Invalid email or password",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not user.is_active:
            return build_response(
                request,
                success=False,
                message="Account is inactive",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        if not user.is_email_verified:
            return build_response(
                request,
                success=False,
                message="Please verify your email first",
                data={
                    "is_email_verified": False
                },
                status_code=status.HTTP_403_FORBIDDEN,
            )



        browser, os_name = parse_user_agent(request)

        user.last_login = timezone.now()
        user.last_login_ip = get_client_ip(request)
        user.last_login_browser = browser
        user.last_login_os = os_name
        user.save(
            update_fields=[
                "last_login",
                "last_login_ip",
                "last_login_browser",
                "last_login_os",
                "updated_at",
            ]
        )
        # JWT token generate
        refresh = RefreshToken.for_user(user)

        return build_response(
            request,
            success=True,
            message="Login successful",
            data={
                "user": {
                    "user_id": user.id,
                    "full_name": user.full_name,
                    "email_address": user.email_address,
                    "phone_number": user.phone_number,
                    "role": user.role,
                    "is_email_verified": user.is_email_verified,
                    "is_admin": user.is_staff or user.is_superuser,
                },
                "tokens": {
                    "accessToken": str(refresh.access_token),
                    "refreshToken": str(refresh),
                },
            },
            status_code=status.HTTP_200_OK,
        )

class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")

        if not email_address:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "email_address": ["This field is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        email_address = email_address.lower()

        user = User.objects.filter(email_address=email_address).first()

        if not user:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        otp = create_otp(user, "password_reset")

        PasswordReset.objects.create(
            user=user,
            otp=otp,
            expires_at=timezone.now() + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )

        return build_response(
            request,
            success=True,
            message="Password reset OTP sent successfully",
            data={
                "email_address": user.email_address,
                "purpose": "password_reset",
            },
            status_code=status.HTTP_200_OK,
        )

class VerifyPasswordResetOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")
        otp_code = request.data.get("otp_code")

        errors = {}

        if not email_address:
            errors["email_address"] = ["This field is required."]
        if not otp_code:
            errors["otp_code"] = ["This field is required."]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        email_address = email_address.lower()

        user = User.objects.filter(email_address=email_address).first()

        if not user:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        otp = OTP.objects.filter(
            user=user,
            email_address=email_address,
            otp_code=otp_code,
            otp_type="password_reset",
            is_verified=False,
        ).order_by("-created_at").first()

        if not otp:
            return build_response(
                request,
                success=False,
                message="Invalid OTP",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if otp.attempt_count >= settings.OTP_MAX_ATTEMPTS:
            return build_response(
                request,
                success=False,
                message="Maximum OTP attempt limit reached",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if otp.is_expired():
            return build_response(
                request,
                success=False,
                message="OTP expired",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        otp.is_verified = True
        otp.verified_at = timezone.now()
        otp.save()

        refresh = RefreshToken.for_user(user)

        return build_response(
            request,
            success=True,
            message="OTP verified",
            data={
                "accessToken": str(refresh.access_token),
                "refreshToken": str(refresh),
                "user": {
                    "email": user.email_address,
                    "full_name": user.full_name,
                    "role": user.role,
                },
            },
            status_code=status.HTTP_200_OK,
        )
    
    
class ResetPasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        errors = {}

        if not new_password:
            errors["new_password"] = ["This field is required."]
        if not confirm_password:
            errors["confirm_password"] = ["This field is required."]

        if errors:
            return Response(
                {
                    "success": False,
                    "message": "Validation error",
                    "errors": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_password != confirm_password:
            return Response(
                {
                    "success": False,
                    "message": "Passwords do not match",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(new_password) < 8:
            return Response(
                {
                    "success": False,
                    "message": "Password must be at least 8 characters",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {
                "success": True,
                "message": "Password reset successful",
            },
            status=status.HTTP_200_OK,
        )



class ResendForgotPasswordOTPView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email_address = request.data.get("email_address")

        if not email_address:
            return Response(
                {
                    "success": False,
                    "message": "Validation error",
                    "errors": {
                        "email_address": ["This field is required."]
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        email_address = email_address.lower()

        user = User.objects.filter(email_address=email_address).first()

        if not user:
            return Response(
                {
                    "success": False,
                    "message": "User not found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        last_otp = OTP.objects.filter(
            user=user,
            otp_type="password_reset",
        ).order_by("-created_at").first()

        if last_otp and last_otp.resend_count >= settings.OTP_MAX_RESEND:
            return Response(
                {
                    "success": False,
                    "message": "Maximum OTP resend limit reached",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        resend_count = last_otp.resend_count if last_otp else 0

        otp = create_otp(user, "password_reset")
        otp.resend_count = resend_count + 1
        otp.save(update_fields=["resend_count"])

        PasswordReset.objects.create(
            user=user,
            otp=otp,
            expires_at=timezone.now() + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        )

        return Response(
            {
                "success": True,
                "message": "OTP resent successfully",
                "data": {
                    "email_address": user.email_address,
                    "purpose": "password_reset",
                },
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return build_response(
            request,
            success=True,
            message="Logout successful",
            data={},
            status_code=status.HTTP_200_OK,
        )
    

def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def parse_user_agent(request):
    user_agent = request.META.get("HTTP_USER_AGENT", "")

    browser = "Unknown"
    os_name = "Unknown"

    if "Edg" in user_agent:
        browser = "Microsoft Edge"
    elif "Chrome" in user_agent:
        browser = "Chrome"
    elif "Firefox" in user_agent:
        browser = "Firefox"
    elif "Safari" in user_agent:
        browser = "Safari"

    if "Windows" in user_agent:
        os_name = "Windows"
    elif "Mac OS X" in user_agent or "Macintosh" in user_agent:
        os_name = "macOS"
    elif "Android" in user_agent:
        os_name = "Android"
    elif "iPhone" in user_agent or "iPad" in user_agent:
        os_name = "iOS"
    elif "Linux" in user_agent:
        os_name = "Linux"

    return browser, os_name


def get_profile_image_data(request, user):
    if not user.profile_image:
        return {
            "profile_image": None,
            "profile_image_path": None,
            "profile_image_url": None,
        }

    try:
        image_path = user.profile_image.url
    except Exception:
        image_path = None

    image_url = request.build_absolute_uri(image_path) if image_path else None

    return {
        "profile_image": image_url,
        "profile_image_path": image_path,
        "profile_image_url": image_url,
    }


def get_user_initials(user):
    full_name = user.full_name or ""
    parts = full_name.strip().split()

    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()

    if len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()

    return "U"


def get_role_label(user):
    if user.is_superuser:
        return "Super Administrator"

    if user.is_staff or user.role == "admin":
        return "Administrator"

    return "Customer"


def format_datetime(value):
    if not value:
        return None
    return timezone.localtime(value).strftime("%b %d, %Y, %I:%M %p")


def build_me_response(request, user):
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    current_month_apps = LoanApplication.objects.filter(updated_at__gte=month_start)

    applications_reviewed = current_month_apps.exclude(
        status=LoanApplication.STATUS_DRAFT
    ).count()

    approved = current_month_apps.filter(
        status__in=[
            LoanApplication.STATUS_APPROVED,
            LoanApplication.STATUS_COMPLETED,
        ]
    ).count()

    rejected = current_month_apps.filter(
        status=LoanApplication.STATUS_REJECTED
    ).count()

    pending_review = current_month_apps.filter(
        status__in=[
            LoanApplication.STATUS_SUBMITTED,
            LoanApplication.STATUS_UNDER_REVIEW,
            LoanApplication.STATUS_PENDING_DOCUMENTS,
            LoanApplication.STATUS_KYC_REQUIRED,
        ]
    ).count()

    profile_image_data = get_profile_image_data(request, user)

    return {
        "id": user.id,
        "full_name": user.full_name,
        "email_address": user.email_address,
        "phone_number": user.phone_number,
        "profile_image": profile_image_data["profile_image"],
        "profile_image_path": profile_image_data["profile_image_path"],
        "profile_image_url": profile_image_data["profile_image_url"],
        "department": user.department,
        "location": user.location,
        "role": user.role,
        "role_label": get_role_label(user),
        "is_email_verified": user.is_email_verified,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,

        "header": {
            "initials": get_user_initials(user),
            "full_name": user.full_name,
            "email_address": user.email_address,
            "department": user.department,
            "location": user.location,
            "role_label": get_role_label(user),
            "status": "Active" if user.is_active else "Inactive",
            "profile_image": profile_image_data["profile_image"],
            "profile_image_path": profile_image_data["profile_image_path"],
        },

        "personal_information": {
            "full_name": user.full_name,
            "email_address": user.email_address,
            "phone_number": user.phone_number,
            "department": user.department,
            "location": user.location,
            "role": get_role_label(user),
        },

        "this_month": {
            "applications_reviewed": applications_reviewed,
            "approved": approved,
            "rejected": rejected,
            "pending_review": pending_review,
        },

        "last_login": {
            "time": format_datetime(user.last_login),
            "ip_address": user.last_login_ip,
            "browser": user.last_login_browser,
            "os": user.last_login_os,
            "location": user.location,
        },
    }



class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return build_response(
            request,
            success=True,
            message="User profile fetched successfully",
            data=build_me_response(request, request.user),
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request):
        user = request.user

        full_name = request.data.get("full_name")
        email_address = request.data.get("email_address")
        phone_number = request.data.get("phone_number")
        department = request.data.get("department")
        location = request.data.get("location")

        profile_image = (
            request.FILES.get("profile_image")
            or request.FILES.get("image")
            or request.FILES.get("avatar")
        )

        remove_profile_image = str(
            request.data.get("remove_profile_image", "")
        ).lower() in ["true", "1", "yes"]

        errors = {}

        if full_name is not None and not str(full_name).strip():
            errors["full_name"] = ["Full name cannot be empty."]

        if email_address is not None:
            email_address = str(email_address).strip().lower()

            if not email_address:
                errors["email_address"] = ["Email address cannot be empty."]
            elif User.objects.filter(email_address=email_address).exclude(id=user.id).exists():
                errors["email_address"] = ["This email address is already used."]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        update_fields = []

        if full_name is not None:
            user.full_name = str(full_name).strip()
            update_fields.append("full_name")

        if email_address is not None:
            user.email_address = email_address
            update_fields.append("email_address")

        if phone_number is not None:
            user.phone_number = str(phone_number).strip() or None
            update_fields.append("phone_number")

        if department is not None:
            user.department = str(department).strip() or None
            update_fields.append("department")

        if location is not None:
            user.location = str(location).strip() or None
            update_fields.append("location")

        if remove_profile_image:
            if user.profile_image:
                user.profile_image.delete(save=False)
            user.profile_image = None
            update_fields.append("profile_image")

        if profile_image:
            if user.profile_image:
                user.profile_image.delete(save=False)
            user.profile_image = profile_image
            update_fields.append("profile_image")

        if update_fields:
            update_fields.append("updated_at")
            user.save(update_fields=update_fields)

        return build_response(
            request,
            success=True,
            message="User profile updated successfully",
            data=build_me_response(request, user),
            status_code=status.HTTP_200_OK,
        )