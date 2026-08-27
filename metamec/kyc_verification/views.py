import math
import os

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from django.db import transaction
from authentication.utils import build_response
from loan_applications.models import LoanApplication
from user_notifications.events import (
    notify_kyc_submitted,
    notify_kyc_status_changed,
)
from .models import CustomerKYC
# from .providers import get_kyc_provider
from .providers import (
    ComplianceAssistKYCProvider,
    KYCProviderError,
    get_kyc_provider,
)


ALLOWED_ID_EXTENSIONS = [".jpg", ".jpeg", ".png", ".pdf"]
ALLOWED_SELFIE_EXTENSIONS = [".jpg", ".jpeg", ".png"]
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def _is_admin_user(user):
    if not user or not user.is_authenticated:
        return False

    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True

    return str(getattr(user, "role", "")).lower() in [
        "admin",
        "super_admin",
        "administrator",
    ]


def _admin_required_response(request):
    return build_response(
        request,
        success=False,
        message="Admin permission required",
        data={},
        status_code=status.HTTP_403_FORBIDDEN,
    )


def _to_int(value, default):
    try:
        value = int(value)
        return value if value > 0 else default
    except Exception:
        return default


def _build_meta(page, limit, total, filters=None):
    total_page = math.ceil(total / limit) if limit else 1

    return {
        "page": page,
        "limit": limit,
        "total": total,
        "totalPage": total_page,
        "filters": filters or {},
    }


def _get_user_full_name(user):
    return getattr(user, "full_name", None) or getattr(user, "email_address", None) or "Customer"


def _get_user_email(user):
    return getattr(user, "email_address", None) or getattr(user, "email", None) or ""


def _get_user_initials(user):
    name = _get_user_full_name(user)
    parts = name.replace("@", " ").replace(".", " ").split()

    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()

    if parts:
        return parts[0][:2].upper()

    return "CU"


def _file_url(request, file_field):
    if not file_field:
        return None

    try:
        return file_field.url
    except Exception:
        return None


def _file_path(file_field):
    if not file_field:
        return None

    try:
        return file_field.url
    except Exception:
        return None


def _validate_file(uploaded_file, allowed_extensions):
    if not uploaded_file:
        return "File is required."

    extension = os.path.splitext(uploaded_file.name)[1].lower()

    if extension not in allowed_extensions:
        return f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"

    if uploaded_file.size > MAX_FILE_SIZE_BYTES:
        return f"File size must be less than or equal to {MAX_FILE_SIZE_MB}MB."

    return None


def _get_application_for_user(user, application_id=None):
    queryset = LoanApplication.objects.select_related("loan_type", "user").filter(user=user)

    if application_id:
        return queryset.filter(id=application_id).first()

    return queryset.order_by("-created_at").first()


def _get_or_create_customer_kyc(user, application=None):
    queryset = CustomerKYC.objects.select_related(
        "user",
        "application",
        "application__loan_type",
    ).filter(user=user)

    if application:
        kyc = queryset.filter(application=application).order_by("-created_at").first()
    else:
        kyc = queryset.order_by("-created_at").first()

    if not kyc:
        kyc = CustomerKYC.objects.create(
            user=user,
            application=application,
            provider=get_kyc_provider().name,
        )

    elif application and not kyc.application:
        kyc.application = application
        kyc.save(update_fields=["application", "updated_at"])

    return kyc


def _kyc_status_label(status_value):
    mapping = {
        CustomerKYC.STATUS_NOT_STARTED: "Not Started",
        CustomerKYC.STATUS_ID_UPLOADED: "ID Uploaded",
        CustomerKYC.STATUS_SELFIE_UPLOADED: "Selfie Uploaded",
        CustomerKYC.STATUS_UNDER_REVIEW: "Pending Verification",
        CustomerKYC.STATUS_APPROVED: "Approved",
        CustomerKYC.STATUS_REJECTED: "Rejected",
    }

    return mapping.get(status_value, status_value)


def _kyc_badge_type(status_value):
    mapping = {
        CustomerKYC.STATUS_NOT_STARTED: "gray",
        CustomerKYC.STATUS_ID_UPLOADED: "blue",
        CustomerKYC.STATUS_SELFIE_UPLOADED: "blue",
        CustomerKYC.STATUS_UNDER_REVIEW: "yellow",
        CustomerKYC.STATUS_APPROVED: "green",
        CustomerKYC.STATUS_REJECTED: "red",
    }

    return mapping.get(status_value, "gray")


def _step_status(kyc, step):
    if step == 1:
        if kyc.has_id_documents:
            return "completed"
        return "current"

    if step == 2:
        if kyc.has_selfie:
            return "completed"
        if kyc.has_id_documents:
            return "current"
        return "pending"

    if step == 3:
        if kyc.status in [
            CustomerKYC.STATUS_UNDER_REVIEW,
            CustomerKYC.STATUS_APPROVED,
            CustomerKYC.STATUS_REJECTED,
        ]:
            return "completed"

        if kyc.has_id_documents and kyc.has_selfie:
            return "current"

        return "pending"

    return "pending"

def _get_provider_check_data(kyc):
    provider_response = kyc.provider_response or {}
    check_data = provider_response.get("check") or {}

    if not isinstance(check_data, dict):
        return {}

    return check_data


def _get_provider_raw_response(kyc):
    check_data = _get_provider_check_data(kyc)

    raw_response = (
        check_data.get("raw_response")
        or {}
    )

    if not isinstance(raw_response, dict):
        return {}

    return raw_response


def _get_provider_verification_url(kyc):
    check_data = _get_provider_check_data(kyc)

    verification_url = check_data.get(
        "verification_url"
    )

    if verification_url:
        return verification_url

    raw_response = _get_provider_raw_response(kyc)
    results = raw_response.get("results") or {}

    physical_results = (
        results.get(
            "physicalIdVerificationResults"
        )
        or {}
    )

    if not isinstance(physical_results, dict):
        return None

    return physical_results.get("url")


def _get_provider_request_status(kyc):
    check_data = _get_provider_check_data(kyc)

    return (
        check_data.get("status")
        or _get_provider_raw_response(kyc).get(
            "requestStatus"
        )
    )


def _get_physical_id_status_from_data(
    provider_data,
):
    raw_response = (
        provider_data.get("raw_response")
        or {}
    )

    results = raw_response.get("results") or {}

    physical_results = (
        results.get(
            "physicalIdVerificationResults"
        )
        or {}
    )

    if not isinstance(physical_results, dict):
        return ""

    return str(
        physical_results.get("status") or ""
    ).strip().upper()


def _get_physical_id_status(kyc):
    check_data = _get_provider_check_data(kyc)

    return _get_physical_id_status_from_data(
        check_data
    )


def _get_watchlist_summary_from_data(
    provider_data,
):
    raw_response = (
        provider_data.get("raw_response")
        or {}
    )

    results = raw_response.get("results") or {}

    watchlist_results = (
        results.get("watchlistsResults")
        or {}
    )

    if not isinstance(watchlist_results, dict):
        watchlist_results = {}

    total_matches = int(
        watchlist_results.get(
            "totalNumberOfMatches"
        )
        or 0
    )

    open_matches = 0
    false_positive_matches = 0

    match_statuses = (
        watchlist_results.get("matchStatuses")
        or []
    )

    for item in match_statuses:
        if not isinstance(item, dict):
            continue

        match_status = str(
            item.get("matchStatus") or ""
        ).strip().lower()

        number_of_matches = int(
            item.get("numberOfMatches")
            or 0
        )

        if match_status == "open":
            open_matches += number_of_matches

        elif match_status in [
            "false positive",
            "false_positive",
        ]:
            false_positive_matches += (
                number_of_matches
            )

    return {
        "totalMatches": total_matches,
        "openMatches": open_matches,
        "falsePositiveMatches": (
            false_positive_matches
        ),
    }


def _get_watchlist_summary(kyc):
    return _get_watchlist_summary_from_data(
        _get_provider_check_data(kyc)
    )


def _map_complianceassist_status(
    provider_data,
):
    physical_status = (
        _get_physical_id_status_from_data(
            provider_data
        )
    )

    request_status = str(
        provider_data.get("status") or ""
    ).strip().upper()

    watchlist = (
        _get_watchlist_summary_from_data(
            provider_data
        )
    )

    rejected_statuses = {
        "FAILED",
        "FAIL",
        "REJECTED",
        "DECLINED",
        "UNVERIFIED",
        "CANCELLED",
    }

    approved_statuses = {
        "PASSED",
        "PASS",
        "APPROVED",
        "VERIFIED",
        "SUCCESS",
        "COMPLETE",
        "COMPLETED",
        "CLEAR",
    }

    if (
        physical_status in rejected_statuses
        or request_status in rejected_statuses
    ):
        return CustomerKYC.STATUS_REJECTED

    if watchlist["openMatches"] > 0:
        return CustomerKYC.STATUS_UNDER_REVIEW

    if (
        physical_status in approved_statuses
        or request_status in approved_statuses
    ):
        return CustomerKYC.STATUS_APPROVED

    return CustomerKYC.STATUS_UNDER_REVIEW


def _update_application_after_kyc(kyc):
    application = kyc.application

    if not application:
        return

    if kyc.status == CustomerKYC.STATUS_APPROVED:
        if application.status in [
            LoanApplication.STATUS_DRAFT,
            LoanApplication.STATUS_SUBMITTED,
            LoanApplication.STATUS_KYC_REQUIRED,
        ]:
            application.status = (
                LoanApplication.STATUS_UNDER_REVIEW
            )
            application.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

    elif kyc.status == CustomerKYC.STATUS_REJECTED:
        application.status = (
            LoanApplication.STATUS_KYC_REQUIRED
        )
        application.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )


def _save_complianceassist_result(
    kyc,
    provider_data,
):
    previous_status = kyc.status

    new_status = _map_complianceassist_status(
        provider_data
    )

    kyc.status = new_status

    kyc.provider_response = {
        **(kyc.provider_response or {}),
        "check": provider_data,
        "lastSync": provider_data,
    }

    if new_status in [
        CustomerKYC.STATUS_APPROVED,
        CustomerKYC.STATUS_REJECTED,
    ]:
        kyc.reviewed_at = timezone.now()

    if new_status == CustomerKYC.STATUS_REJECTED:
        raw_response = (
            provider_data.get("raw_response")
            or {}
        )

        kyc.rejection_reason = (
            raw_response.get("message")
            or "ComplianceAssist verification failed."
        )

    kyc.save()

    _update_application_after_kyc(kyc)

    if previous_status != new_status:
        notify_kyc_status_changed(
            kyc,
            new_status,
        )

    return kyc


# def _build_kyc_response(request, kyc):
#     application = kyc.application

#     return {
#         "id": kyc.id,
#         "status": kyc.status,
#         "statusLabel": _kyc_status_label(kyc.status),
#         "statusBadgeType": _kyc_badge_type(kyc.status),
#         "provider": kyc.provider,

#         "documentType": kyc.document_type,
#         "documentTypeLabel": kyc.get_document_type_display() if kyc.document_type else None,

#         "application": {
#             "id": application.id,
#             "applicationNumber": application.application_number,
#             "loanType": application.loan_type.name if application.loan_type else None,
#             "status": application.status,
#         } if application else None,

#         "customer": {
#             "id": kyc.user.id,
#             "name": _get_user_full_name(kyc.user),
#             "email": _get_user_email(kyc.user),
#             "initials": _get_user_initials(kyc.user),
#         },

#         "files": {
#             "idFront": {
#                 "url": _file_url(request, kyc.id_front_image),
#                 "path": _file_path(kyc.id_front_image),
#                 "isUploaded": bool(kyc.id_front_image),
#             },
#             "idBack": {
#                 "url": _file_url(request, kyc.id_back_image),
#                 "path": _file_path(kyc.id_back_image),
#                 "isUploaded": bool(kyc.id_back_image),
#             },
#             "selfie": {
#                 "url": _file_url(request, kyc.selfie_image),
#                 "path": _file_path(kyc.selfie_image),
#                 "isUploaded": bool(kyc.selfie_image),
#             },
#         },

#         "providerData": {
#             "applicantId": kyc.provider_applicant_id,
#             "documentId": kyc.provider_document_id,
#             "selfieId": kyc.provider_selfie_id,
#             "checkId": kyc.provider_check_id,
#             "response": kyc.provider_response,
#         },

#         "steps": [
#             {
#                 "step": 1,
#                 "key": "id_scan",
#                 "title": "ID Scan",
#                 "status": _step_status(kyc, 1),
#             },
#             {
#                 "step": 2,
#                 "key": "selfie_check",
#                 "title": "Selfie Check",
#                 "status": _step_status(kyc, 2),
#             },
#             {
#                 "step": 3,
#                 "key": "review_submit",
#                 "title": "Review & Submit",
#                 "status": _step_status(kyc, 3),
#             },
#         ],

#         "documentTypes": [
#             {
#                 "key": CustomerKYC.DOC_DRIVING_LICENSE,
#                 "label": "Driving License",
#             },
#             {
#                 "key": CustomerKYC.DOC_PASSPORT,
#                 "label": "Passport",
#             },
#         ],

#         "guidelines": [
#             {
#                 "key": "clear_photo",
#                 "label": "Make sure your document is clear and readable.",
#             },
#             {
#                 "key": "good_light",
#                 "label": "Use good lighting and avoid shadows or glare.",
#             },
#             {
#                 "key": "face_visible",
#                 "label": "For selfie, keep your face fully visible.",
#             },
#             {
#                 "key": "no_sunglasses",
#                 "label": "Do not wear sunglasses or a hat.",
#             },
#         ],

#         "screen": {
#             "title": "KYC Verification",
#             "subtitle": "KYC — Know Your Customer",
#             "underReviewTitle": "Under Review",
#             "underReviewMessage": "Your documents have been submitted and are being reviewed by Dragon Finance.",
#         },

#         "actions": {
#             "canUploadId": kyc.status not in [
#                 CustomerKYC.STATUS_UNDER_REVIEW,
#                 CustomerKYC.STATUS_APPROVED,
#             ],
#             "canUploadSelfie": kyc.has_id_documents and kyc.status not in [
#                 CustomerKYC.STATUS_UNDER_REVIEW,
#                 CustomerKYC.STATUS_APPROVED,
#             ],
#             "canSubmit": kyc.can_submit,
#             "statusApi": "/api/kyc/me/",
#             "uploadIdApi": "/api/kyc/upload-id/",
#             "uploadSelfieApi": "/api/kyc/upload-selfie/",
#             "submitApi": "/api/kyc/submit/",
#         },

#         "submittedAt": kyc.submitted_at,
#         "reviewedAt": kyc.reviewed_at,
#         "adminNote": kyc.admin_note,
#         "rejectionReason": kyc.rejection_reason,
#     }

def _build_kyc_response(request, kyc):
    application = kyc.application

    is_complianceassist = (
        kyc.provider
        == CustomerKYC.PROVIDER_COMPLIANCE_ASSIST
    )

    verification_url = (
        _get_provider_verification_url(kyc)
    )

    return {
        "id": kyc.id,
        "status": kyc.status,
        "statusLabel": _kyc_status_label(
            kyc.status
        ),
        "statusBadgeType": _kyc_badge_type(
            kyc.status
        ),
        "provider": kyc.provider,

        "documentType": kyc.document_type,
        "documentTypeLabel": (
            kyc.get_document_type_display()
            if kyc.document_type
            else None
        ),

        "application": {
            "id": application.id,
            "applicationNumber": (
                application.application_number
            ),
            "loanType": (
                application.loan_type.name
                if application.loan_type
                else None
            ),
            "status": application.status,
        } if application else None,

        "customer": {
            "id": kyc.user.id,
            "name": _get_user_full_name(
                kyc.user
            ),
            "email": _get_user_email(
                kyc.user
            ),
            "initials": _get_user_initials(
                kyc.user
            ),
        },

       
        "files": {
            "idFront": {
                "url": _file_url(
                    request,
                    kyc.id_front_image,
                ),
                "path": _file_path(
                    kyc.id_front_image
                ),
                "isUploaded": bool(
                    kyc.id_front_image
                ),
            },
            "idBack": {
                "url": _file_url(
                    request,
                    kyc.id_back_image,
                ),
                "path": _file_path(
                    kyc.id_back_image
                ),
                "isUploaded": bool(
                    kyc.id_back_image
                ),
            },
            "selfie": {
                "url": _file_url(
                    request,
                    kyc.selfie_image,
                ),
                "path": _file_path(
                    kyc.selfie_image
                ),
                "isUploaded": bool(
                    kyc.selfie_image
                ),
            },
        },

        "providerData": {
            "applicantId": (
                kyc.provider_applicant_id
            ),
            "documentId": (
                kyc.provider_document_id
            ),
            "selfieId": (
                kyc.provider_selfie_id
            ),
            "checkId": (
                kyc.provider_check_id
            ),
            "requestStatus": (
                _get_provider_request_status(
                    kyc
                )
            ),
            "physicalIdStatus": (
                _get_physical_id_status(kyc)
            ),
            "verificationUrl": (
                verification_url
            ),
            "watchlist": (
                _get_watchlist_summary(kyc)
            ),
            "response": kyc.provider_response,
        },

        "steps": [
            {
                "step": 1,
                "key": (
                    "start_verification"
                    if is_complianceassist
                    else "id_scan"
                ),
                "title": (
                    "Start Verification"
                    if is_complianceassist
                    else "ID Scan"
                ),
                "status": (
                    "completed"
                    if kyc.provider_check_id
                    else "current"
                ),
            },
            {
                "step": 2,
                "key": (
                    "hosted_id_selfie"
                    if is_complianceassist
                    else "selfie_check"
                ),
                "title": (
                    "ID & Selfie Verification"
                    if is_complianceassist
                    else "Selfie Check"
                ),
                "status": (
                    "completed"
                    if kyc.status in [
                        CustomerKYC.STATUS_APPROVED,
                        CustomerKYC.STATUS_REJECTED,
                    ]
                    else (
                        "current"
                        if kyc.provider_check_id
                        else "pending"
                    )
                ),
            },
            {
                "step": 3,
                "key": "verification_result",
                "title": "Verification Result",
                "status": (
                    "completed"
                    if kyc.status in [
                        CustomerKYC.STATUS_APPROVED,
                        CustomerKYC.STATUS_REJECTED,
                    ]
                    else "pending"
                ),
            },
        ],

        "documentTypes": [
            {
                "key": (
                    CustomerKYC
                    .DOC_DRIVING_LICENSE
                ),
                "label": "Driving License",
            },
            {
                "key": (
                    CustomerKYC.DOC_PASSPORT
                ),
                "label": "Passport",
            },
        ],

        "guidelines": [
            {
                "key": "valid_document",
                "label": (
                    "Use a valid government-issued "
                    "identity document."
                ),
            },
            {
                "key": "good_light",
                "label": (
                    "Use good lighting and avoid "
                    "shadows or glare."
                ),
            },
            {
                "key": "face_visible",
                "label": (
                    "Keep your face fully visible "
                    "during verification."
                ),
            },
        ],

        "screen": {
            "title": "KYC Verification",
            "subtitle": "KYC — Know Your Customer",
            "underReviewTitle": (
                "Verification in Progress"
            ),
            "underReviewMessage": (
                "Your verification is being "
                "processed by ComplianceAssist."
                if is_complianceassist
                else (
                    "Your documents have been "
                    "submitted for verification."
                )
            ),
        },

        "actions": {
            "canUploadId": bool(
                not is_complianceassist
                and kyc.status not in [
                    CustomerKYC
                    .STATUS_UNDER_REVIEW,
                    CustomerKYC
                    .STATUS_APPROVED,
                ]
            ),
            "canUploadSelfie": bool(
                not is_complianceassist
                and kyc.has_id_documents
                and kyc.status not in [
                    CustomerKYC
                    .STATUS_UNDER_REVIEW,
                    CustomerKYC
                    .STATUS_APPROVED,
                ]
            ),
            # "canSubmit": bool(
            #     not kyc.provider_check_id
            #     and kyc.status
            #     != CustomerKYC.STATUS_APPROVED
            # ),
            "canSubmit": bool(
                (
                    not kyc.provider_check_id
                    or kyc.status
                    == CustomerKYC.STATUS_REJECTED
                )
                and kyc.status
                != CustomerKYC.STATUS_APPROVED
            ),

            "canRetry": bool(
                is_complianceassist
                and kyc.status
                == CustomerKYC.STATUS_REJECTED
            ),


            "canOpenVerification": bool(
                is_complianceassist
                and verification_url
                and kyc.status
                == CustomerKYC
                .STATUS_UNDER_REVIEW
            ),
            "canSyncProvider": bool(
                is_complianceassist
                and kyc.provider_check_id
                and kyc.status
                == CustomerKYC
                .STATUS_UNDER_REVIEW
            ),
            "statusApi": "/api/kyc/me/",
            "uploadIdApi": (
                "/api/kyc/upload-id/"
            ),
            "uploadSelfieApi": (
                "/api/kyc/upload-selfie/"
            ),
            "submitApi": "/api/kyc/submit/",
            "providerSyncApi": (
                "/api/kyc/provider-sync/"
            ),
        },

        "submittedAt": kyc.submitted_at,
        "reviewedAt": kyc.reviewed_at,
        "adminNote": kyc.admin_note,
        "rejectionReason": (
            kyc.rejection_reason
        ),
    }


class CustomerKYCStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        application_id = request.query_params.get("application_id")
        application = _get_application_for_user(request.user, application_id)

        if application_id and not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        kyc = _get_or_create_customer_kyc(request.user, application)

        return build_response(
            request,
            success=True,
            message="KYC status fetched successfully",
            data=_build_kyc_response(request, kyc),
            status_code=status.HTTP_200_OK,
        )


class CustomerKYCUploadIDView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        application_id = request.data.get("application_id")
        document_type = request.data.get("document_type") or request.data.get("documentType")

        front_file = (
            request.FILES.get("front_file")
            or request.FILES.get("id_front")
            or request.FILES.get("front")
        )

        back_file = (
            request.FILES.get("back_file")
            or request.FILES.get("id_back")
            or request.FILES.get("back")
        )

        application = _get_application_for_user(request.user, application_id)

        if application_id and not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if document_type not in [
            CustomerKYC.DOC_DRIVING_LICENSE,
            CustomerKYC.DOC_PASSPORT,
        ]:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "document_type": [
                        "Invalid document type. Allowed: driving_license, passport"
                    ]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        front_error = _validate_file(front_file, ALLOWED_ID_EXTENSIONS)
        back_error = _validate_file(back_file, ALLOWED_ID_EXTENSIONS)

        errors = {}

        if front_error:
            errors["front_file"] = [front_error]

        if back_error:
            errors["back_file"] = [back_error]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        kyc = _get_or_create_customer_kyc(request.user, application)

        if kyc.status == CustomerKYC.STATUS_APPROVED:
            return build_response(
                request,
                success=False,
                message="KYC is already approved",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if kyc.status == CustomerKYC.STATUS_UNDER_REVIEW:
            return build_response(
                request,
                success=False,
                message="KYC is already under review",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if kyc.id_front_image:
            kyc.id_front_image.delete(save=False)

        if kyc.id_back_image:
            kyc.id_back_image.delete(save=False)

        provider = get_kyc_provider()
        applicant_response = provider.create_or_update_applicant(kyc)

        kyc.provider = provider.name
        kyc.provider_applicant_id = applicant_response.get("applicant_id")
        kyc.document_type = document_type
        kyc.id_front_image = front_file
        kyc.id_back_image = back_file
        kyc.status = CustomerKYC.STATUS_ID_UPLOADED
        kyc.provider_response = {
            "applicant": applicant_response,
        }
        kyc.save()

        document_response = provider.upload_document(kyc)

        kyc.provider_document_id = document_response.get("document_id")
        kyc.provider_response = {
            **(kyc.provider_response or {}),
            "document": document_response,
        }
        kyc.save(update_fields=["provider_document_id", "provider_response", "updated_at"])

        return build_response(
            request,
            success=True,
            message="KYC ID documents uploaded successfully",
            data=_build_kyc_response(request, kyc),
            status_code=status.HTTP_201_CREATED,
        )


class CustomerKYCUploadSelfieView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        application_id = request.data.get("application_id")

        selfie_file = (
            request.FILES.get("selfie_file")
            or request.FILES.get("selfie")
            or request.FILES.get("file")
        )

        application = _get_application_for_user(request.user, application_id)

        if application_id and not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        kyc = _get_or_create_customer_kyc(request.user, application)

        if not kyc.has_id_documents:
            return build_response(
                request,
                success=False,
                message="Please upload ID front and back first",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if kyc.status == CustomerKYC.STATUS_APPROVED:
            return build_response(
                request,
                success=False,
                message="KYC is already approved",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if kyc.status == CustomerKYC.STATUS_UNDER_REVIEW:
            return build_response(
                request,
                success=False,
                message="KYC is already under review",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        file_error = _validate_file(selfie_file, ALLOWED_SELFIE_EXTENSIONS)

        if file_error:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={"selfie_file": [file_error]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if kyc.selfie_image:
            kyc.selfie_image.delete(save=False)

        provider = get_kyc_provider()

        kyc.selfie_image = selfie_file
        kyc.status = CustomerKYC.STATUS_SELFIE_UPLOADED
        kyc.provider = provider.name
        kyc.save()

        selfie_response = provider.upload_selfie(kyc)

        kyc.provider_selfie_id = selfie_response.get("selfie_id")
        kyc.provider_response = {
            **(kyc.provider_response or {}),
            "selfie": selfie_response,
        }
        kyc.save(update_fields=["provider_selfie_id", "provider_response", "updated_at"])

        return build_response(
            request,
            success=True,
            message="KYC selfie uploaded successfully",
            data=_build_kyc_response(request, kyc),
            status_code=status.HTTP_201_CREATED,
        )


# class CustomerKYCSubmitView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request):
#         application_id = request.data.get("application_id")
#         application = _get_application_for_user(request.user, application_id)

#         if application_id and not application:
#             return build_response(
#                 request,
#                 success=False,
#                 message="Loan application not found",
#                 data={},
#                 status_code=status.HTTP_404_NOT_FOUND,
#             )

#         kyc = _get_or_create_customer_kyc(request.user, application)

#         if not kyc.has_id_documents:
#             return build_response(
#                 request,
#                 success=False,
#                 message="Please upload ID front and back before submit",
#                 data={},
#                 status_code=status.HTTP_400_BAD_REQUEST,
#             )

#         if not kyc.has_selfie:
#             return build_response(
#                 request,
#                 success=False,
#                 message="Please upload selfie before submit",
#                 data={},
#                 status_code=status.HTTP_400_BAD_REQUEST,
#             )

#         if kyc.status == CustomerKYC.STATUS_APPROVED:
#             return build_response(
#                 request,
#                 success=False,
#                 message="KYC is already approved",
#                 data={},
#                 status_code=status.HTTP_400_BAD_REQUEST,
#             )

#         provider = get_kyc_provider()
#         try:
#             check_response = provider.submit_check(kyc, request.data)
#         except Exception as exc:
#             return build_response(
#                 request,
#                 success=False,
#                 message="KYC provider error",
#                 data={
#                     "provider": provider.name,
#                     "error": str(exc),
#                 },
#                 status_code=status.HTTP_502_BAD_GATEWAY,
#             )

#         kyc.provider = provider.name
#         kyc.provider_check_id = check_response.get("check_id")
#         kyc.status = CustomerKYC.STATUS_UNDER_REVIEW
#         kyc.submitted_at = timezone.now()
#         kyc.provider_response = {
#             **(kyc.provider_response or {}),
#             "check": check_response,
#         }
#         kyc.save()

#         notify_kyc_submitted(kyc)

#         if kyc.application and kyc.application.status == LoanApplication.STATUS_DRAFT:
#             kyc.application.status = LoanApplication.STATUS_KYC_REQUIRED
#             kyc.application.save(update_fields=["status", "updated_at"])

#         return build_response(
#             request,
#             success=True,
#             message="KYC submitted successfully. Verification is under review.",
#             data=_build_kyc_response(request, kyc),
#             status_code=status.HTTP_200_OK,
#         )

class CustomerKYCSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        application_id = request.data.get(
            "application_id"
        )

        application = _get_application_for_user(
            request.user,
            application_id,
        )

        if application_id and not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
            )

        kyc = _get_or_create_customer_kyc(
            request.user,
            application,
        )

        
        kyc = (
            CustomerKYC.objects
            .select_for_update()
            .select_related(
                "user",
                "application",
                "application__loan_type",
            )
            .get(id=kyc.id)
        )

        provider = get_kyc_provider()

        is_complianceassist = (
            provider.name
            == CustomerKYC
            .PROVIDER_COMPLIANCE_ASSIST
        )

       
        if not is_complianceassist:
            if not kyc.has_id_documents:
                return build_response(
                    request,
                    success=False,
                    message=(
                        "Please upload ID front "
                        "and back before submit"
                    ),
                    data={},
                    status_code=(
                        status
                        .HTTP_400_BAD_REQUEST
                    ),
                )

            if not kyc.has_selfie:
                return build_response(
                    request,
                    success=False,
                    message=(
                        "Please upload selfie "
                        "before submit"
                    ),
                    data={},
                    status_code=(
                        status
                        .HTTP_400_BAD_REQUEST
                    ),
                )

        if (
            kyc.status
            == CustomerKYC.STATUS_APPROVED
        ):
            return build_response(
                request,
                success=True,
                message="KYC is already approved",
                data=_build_kyc_response(
                    request,
                    kyc,
                ),
                status_code=status.HTTP_200_OK,
            )

    
        # if kyc.provider_check_id:
        #     return build_response(
        #         request,
        #         success=True,
        #         message=(
        #             "KYC request already exists. "
        #             "Continue using the existing "
        #             "verification URL."
        #         ),
        #         data=_build_kyc_response(
        #             request,
        #             kyc,
        #         ),
        #         status_code=status.HTTP_200_OK,
        #     )

        if kyc.provider_check_id:
            verification_url = (
                _get_provider_verification_url(kyc)
            )

            # ComplianceAssist KYC failed/rejected:
            # keep the old attempt for history and
            # create a fresh KYC record for retry.
            if (
                is_complianceassist
                and kyc.status
                == CustomerKYC.STATUS_REJECTED
            ):
                kyc = CustomerKYC.objects.create(
                    user=request.user,
                    application=application,
                    provider=provider.name,
                )

            else:
                if verification_url:
                    existing_message = (
                        "KYC request already exists. "
                        "Continue using the existing "
                        "verification URL."
                    )
                else:
                    existing_message = (
                        "KYC request already exists. "
                        "Verification is being processed. "
                        "Please synchronize the provider "
                        "status."
                    )

                return build_response(
                    request,
                    success=True,
                    message=existing_message,
                    data=_build_kyc_response(
                        request,
                        kyc,
                    ),
                    status_code=status.HTTP_200_OK,
                )

        kyc.provider = provider.name
        kyc.save(
            update_fields=[
                "provider",
                "updated_at",
            ]
        )

        try:
            check_response = (
                provider.submit_check(
                    kyc,
                    request.data,
                )
            )

        except KYCProviderError as exc:
            error_status = (
                status.HTTP_400_BAD_REQUEST
                if exc.status_code in [
                    400,
                    404,
                    415,
                ]
                else status
                .HTTP_502_BAD_GATEWAY
            )

            return build_response(
                request,
                success=False,
                message=(
                    "KYC provider request failed"
                ),
                data={
                    "provider": provider.name,
                    "error": exc.as_dict(),
                },
                status_code=error_status,
            )

        except Exception:
            return build_response(
                request,
                success=False,
                message=(
                    "KYC provider is temporarily "
                    "unavailable"
                ),
                data={
                    "provider": provider.name,
                },
                status_code=(
                    status.HTTP_502_BAD_GATEWAY
                ),
            )

        kyc.provider = provider.name
        kyc.provider_check_id = str(
            check_response.get("check_id")
        )
        kyc.status = (
            CustomerKYC.STATUS_UNDER_REVIEW
        )
        kyc.submitted_at = timezone.now()

        kyc.provider_response = {
            **(kyc.provider_response or {}),
            "check": check_response,
        }

        kyc.save()

        notify_kyc_submitted(kyc)

        if kyc.application:
            if kyc.application.status in [
                LoanApplication.STATUS_DRAFT,
                LoanApplication.STATUS_SUBMITTED,
            ]:
                kyc.application.status = (
                    LoanApplication
                    .STATUS_KYC_REQUIRED
                )
                kyc.application.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

        return build_response(
            request,
            success=True,
            message=(
                "KYC request created successfully. "
                "Open verificationUrl to complete "
                "ID and selfie verification."
            ),
            data=_build_kyc_response(
                request,
                kyc,
            ),
            status_code=status.HTTP_200_OK,
        )

class CustomerKYCProviderSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        application_id = request.data.get(
            "application_id"
        )

        application = _get_application_for_user(
            request.user,
            application_id,
        )

        if application_id and not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
            )

        kyc = _get_or_create_customer_kyc(
            request.user,
            application,
        )

        if not kyc.provider_check_id:
            return build_response(
                request,
                success=False,
                message=(
                    "KYC request has not been "
                    "created yet"
                ),
                data=_build_kyc_response(
                    request,
                    kyc,
                ),
                status_code=(
                    status.HTTP_400_BAD_REQUEST
                ),
            )

        if (
            kyc.provider
            != CustomerKYC
            .PROVIDER_COMPLIANCE_ASSIST
        ):
            return build_response(
                request,
                success=False,
                message=(
                    "This KYC does not use "
                    "ComplianceAssist"
                ),
                data={},
                status_code=(
                    status.HTTP_400_BAD_REQUEST
                ),
            )

        provider = (
            ComplianceAssistKYCProvider()
        )

        try:
            provider_data = (
                provider.get_check_result(kyc)
            )

        except KYCProviderError as exc:
            return build_response(
                request,
                success=False,
                message=(
                    "Could not synchronize "
                    "ComplianceAssist result"
                ),
                data={
                    "error": exc.as_dict(),
                },
                status_code=(
                    status.HTTP_502_BAD_GATEWAY
                ),
            )

        _save_complianceassist_result(
            kyc,
            provider_data,
        )

        return build_response(
            request,
            success=True,
            message=(
                "ComplianceAssist result "
                "synchronized successfully"
            ),
            data=_build_kyc_response(
                request,
                kyc,
            ),
            status_code=status.HTTP_200_OK,
        )

class AdminKYCListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        search = request.query_params.get("search", "").strip()
        status_filter = request.query_params.get("status", "").strip()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 10)

        queryset = CustomerKYC.objects.select_related(
            "user",
            "application",
            "application__loan_type",
        ).all()

        if search:
            queryset = queryset.filter(
                Q(user__full_name__icontains=search)
                | Q(user__email_address__icontains=search)
                | Q(application__application_number__icontains=search)
            )

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        total = queryset.count()
        start = (page - 1) * limit
        end = start + limit

        items = [
            _build_kyc_response(request, item)
            for item in queryset.order_by("-created_at")[start:end]
        ]

        summary = {
            "total": CustomerKYC.objects.count(),
            "underReview": CustomerKYC.objects.filter(status=CustomerKYC.STATUS_UNDER_REVIEW).count(),
            "approved": CustomerKYC.objects.filter(status=CustomerKYC.STATUS_APPROVED).count(),
            "rejected": CustomerKYC.objects.filter(status=CustomerKYC.STATUS_REJECTED).count(),
        }

        return build_response(
            request,
            success=True,
            message="Admin KYC list fetched successfully",
            meta=_build_meta(
                page,
                limit,
                total,
                {
                    "search": search,
                    "status": status_filter,
                },
            ),
            data={
                "summary": summary,
                "kycVerifications": items,
            },
            status_code=status.HTTP_200_OK,
        )


class AdminKYCDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, kyc_id):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        kyc = CustomerKYC.objects.select_related(
            "user",
            "application",
            "application__loan_type",
            "reviewed_by",
        ).filter(id=kyc_id).first()

        if not kyc:
            return build_response(
                request,
                success=False,
                message="KYC verification not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        data = _build_kyc_response(request, kyc)

        data["reviewedBy"] = _get_user_full_name(kyc.reviewed_by) if kyc.reviewed_by else None
        # data["adminActions"] = {
        #     "canApprove": kyc.status != CustomerKYC.STATUS_APPROVED,
        #     "canReject": kyc.status != CustomerKYC.STATUS_REJECTED,
        #     "statusApi": f"/api/admin/kyc/{kyc.id}/status/",
        # }
        is_complianceassist = (
            kyc.provider
            == CustomerKYC.PROVIDER_COMPLIANCE_ASSIST
        )

        data["adminActions"] = {
            "canApprove": bool(
                not is_complianceassist
                and kyc.status
                != CustomerKYC.STATUS_APPROVED
            ),
            "canReject": bool(
                not is_complianceassist
                and kyc.status
                != CustomerKYC.STATUS_REJECTED
            ),
            "canSyncProvider": bool(
                is_complianceassist
                and kyc.provider_check_id
                and kyc.status
                == CustomerKYC.STATUS_UNDER_REVIEW
            ),
            "statusApi": (
                f"/api/admin/kyc/{kyc.id}/status/"
            ),
        }

        return build_response(
            request,
            success=True,
            message="Admin KYC detail fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )


class AdminKYCStatusUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, kyc_id):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        kyc = CustomerKYC.objects.select_related(
            "user",
            "application",
        ).filter(id=kyc_id).first()

        if not kyc:
            return build_response(
                request,
                success=False,
                message="KYC verification not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if (
            kyc.provider
            == CustomerKYC.PROVIDER_COMPLIANCE_ASSIST
        ):
            return build_response(
                request,
                success=False,
                message=(
                    "ComplianceAssist controls KYC "
                    "approval and rejection. Admin cannot "
                    "manually change this KYC status."
                ),
                data=_build_kyc_response(
                    request,
                    kyc,
                ),
                status_code=(
                    status.HTTP_400_BAD_REQUEST
                ),
            )




        new_status = request.data.get("status")
        note = str(request.data.get("note", "") or "").strip()
        rejection_reason = (
            str(request.data.get("rejection_reason", "") or "").strip()
            or str(request.data.get("rejectionReason", "") or "").strip()
        )

        allowed_statuses = [
            CustomerKYC.STATUS_APPROVED,
            CustomerKYC.STATUS_REJECTED,
            CustomerKYC.STATUS_UNDER_REVIEW,
        ]

        if new_status not in allowed_statuses:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "status": [
                        f"Invalid status. Allowed: {', '.join(allowed_statuses)}"
                    ]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        kyc.status = new_status
        kyc.reviewed_by = request.user
        kyc.reviewed_at = timezone.now()

        if note:
            kyc.admin_note = note

        if new_status == CustomerKYC.STATUS_REJECTED:
            kyc.rejection_reason = rejection_reason or note or "KYC verification rejected."

        kyc.save()

        if kyc.application:
            if (
                new_status == CustomerKYC.STATUS_APPROVED
                and kyc.application.status == LoanApplication.STATUS_KYC_REQUIRED
            ):
                kyc.application.status = LoanApplication.STATUS_UNDER_REVIEW
                kyc.application.save(update_fields=["status", "updated_at"])

            elif new_status == CustomerKYC.STATUS_REJECTED:
                kyc.application.status = LoanApplication.STATUS_KYC_REQUIRED
                kyc.application.save(update_fields=["status", "updated_at"])

        notify_kyc_status_changed(kyc, new_status, note)
        return build_response(
            request,
            success=True,
            message="KYC status updated successfully",
            data=_build_kyc_response(request, kyc),
            status_code=status.HTTP_200_OK,
        )


class OnfidoWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.data or {}

        if not isinstance(payload, dict):
            return build_response(
                request,
                success=False,
                message="Invalid webhook payload",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        resource = payload.get("resource", {})
        obj = payload.get("object", {})

        if not isinstance(resource, dict):
            resource = {}

        if not isinstance(obj, dict):
            obj = {}

        check_id = (
            payload.get("check_id")
            or payload.get("checkId")
            or resource.get("id")
            or obj.get("id")
        )

        result = (
            payload.get("result")
            or resource.get("result")
            or payload.get("status")
            or resource.get("status")
        )

        if not check_id:
            return build_response(
                request,
                success=False,
                message="Webhook received but check id was not found",
                data={"payload": payload},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        kyc = CustomerKYC.objects.filter(provider_check_id=check_id).first()

        if not kyc:
            return build_response(
                request,
                success=True,
                message="Webhook received. Matching KYC not found.",
                data={"checkId": check_id},
                status_code=status.HTTP_200_OK,
            )

        normalized = str(result or "").lower()

        if normalized in ["clear", "approved", "complete", "completed"]:
            kyc.status = CustomerKYC.STATUS_APPROVED
            kyc.reviewed_at = timezone.now()

        elif normalized in ["consider", "rejected", "failed", "declined"]:
            kyc.status = CustomerKYC.STATUS_REJECTED
            kyc.reviewed_at = timezone.now()
            kyc.rejection_reason = "Rejected by Onfido result."

        else:
            kyc.status = CustomerKYC.STATUS_UNDER_REVIEW

        kyc.provider_response = {
            **(kyc.provider_response or {}),
            "webhook": payload,
        }
        kyc.save()
        notify_kyc_status_changed(kyc, kyc.status)

        return build_response(
            request,
            success=True,
            message="Onfido webhook processed successfully",
            data=_build_kyc_response(request, kyc),
            status_code=status.HTTP_200_OK,
        )