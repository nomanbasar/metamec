import base64
import os
import textwrap
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.http import FileResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from authentication.utils import build_response
from loan_applications.models import LoanApplication
from loan_applications.serializers import LoanApplicationSerializer

from .models import CoApplicantInvitation, LoanAgreement


def _get_user_full_name(user):
    return getattr(user, "full_name", None) or getattr(user, "email_address", None) or "Customer"


def _get_user_email(user):
    return getattr(user, "email_address", None) or getattr(user, "email", None) or ""


def _money_display(value):
    if value is None:
        return None

    try:
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"${amount:,.2f}"
    except Exception:
        return str(value)


def _truthy(value):
    return str(value).lower() in ["true", "1", "yes", "on"]


def _get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _file_url(request, file_field):
    if not file_field:
        return None

    try:
        return request.build_absolute_uri(file_field.url)
    except Exception:
        return None


def _file_path(file_field):
    if not file_field:
        return None

    try:
        return file_field.url
    except Exception:
        return None


def _status_label(status_value):
    mapping = {
        LoanAgreement.STATUS_AWAITING_SIGNATURE: "Awaiting Signature",
        LoanAgreement.STATUS_SIGNED: "Signed",
    }
    return mapping.get(status_value, status_value)


def _co_applicant_status_label(status_value):
    mapping = {
        LoanAgreement.CO_APPLICANT_NONE: "Not Required",
        LoanAgreement.CO_APPLICANT_INVITED: "Invited",
        LoanAgreement.CO_APPLICANT_SKIPPED: "Skipped",
        LoanAgreement.CO_APPLICANT_ACCEPTED: "Accepted",
    }
    return mapping.get(status_value, status_value)


def _get_application_for_customer(user, application_id):
    return (
        LoanApplication.objects
        .select_related("user", "loan_type", "loan_type__template")
        .filter(id=application_id, user=user)
        .first()
    )


def _get_or_create_agreement(application):
    agreement, _ = LoanAgreement.objects.get_or_create(
        application=application,
        defaults={
            "borrower": application.user,
            "lender_name": "LoanSphere Financial Ltd.",
        },
    )
    return agreement


def _loan_summary(application):
    serializer = LoanApplicationSerializer(application)
    data = serializer.data

    return {
        "loanAmount": str(application.loan_amount) if application.loan_amount is not None else None,
        "loanAmountDisplay": _money_display(application.loan_amount),
        "loanTerm": application.loan_term,
        "interestRate": data.get("estimatedRate"),
        "monthlyPayment": data.get("estimatedMonthlyPayment"),
        "monthlyPaymentDisplay": _money_display(data.get("estimatedMonthlyPayment")),
        "applicationNumber": application.application_number,
        "loanType": application.loan_type.name if application.loan_type else None,
        "status": application.status,
    }


def _agreement_sections(application):
    sections = []
    template = application.loan_type.template if application.loan_type else None

    if template:
        for section in template.sections.all().order_by("order", "created_at"):
            sections.append({
                "id": section.id,
                "order": section.order,
                "title": section.title,
                "description": section.description,
                "isOpen": section.order == 1,
            })

    if sections:
        return sections

    return [
        {
            "id": "default_loan_amount",
            "order": 1,
            "title": "Loan Amount",
            "description": "This is the loan amount being borrowed from the lender, subject to approval and verification.",
            "isOpen": True,
        },
        {
            "id": "default_interest_repayments",
            "order": 2,
            "title": "Interest Rate & Repayments",
            "description": "The interest rate, repayment schedule, monthly instalment and total cost are based on the approved loan terms.",
            "isOpen": False,
        },
        {
            "id": "default_security_address",
            "order": 3,
            "title": "Security Address",
            "description": "The security address is the property connected to this loan agreement where applicable.",
            "isOpen": False,
        },
    ]


def _invitation_response(request, invite):
    if not invite:
        return None

    return {
        "id": invite.id,
        "token": invite.token,
        "name": invite.name,
        "email": invite.email,
        "status": invite.status,
        "statusLabel": invite.get_status_display(),
        "inviteLink": invite.invite_link,
        "message": invite.message,
        "agreementId": invite.agreement_id,
        "applicationId": invite.agreement.application_id,
        "createdAt": invite.created_at,
        "acceptedAt": invite.accepted_at,
        "declinedAt": invite.declined_at,
    }


def _agreement_response(request, agreement):
    application = agreement.application
    latest_invite = agreement.co_applicant_invitations.order_by("-created_at").first()

    return {
        "id": agreement.id,
        "status": agreement.status,
        "statusLabel": _status_label(agreement.status),
        "borrower": {
            "id": agreement.borrower.id,
            "name": _get_user_full_name(agreement.borrower),
            "email": _get_user_email(agreement.borrower),
        },
        "lender": {
            "name": agreement.lender_name,
        },
        "application": {
            "id": application.id,
            "applicationNumber": application.application_number,
            "loanType": application.loan_type.name if application.loan_type else None,
            "status": application.status,
        },
        "loanSummary": _loan_summary(application),
        "sections": _agreement_sections(application),
        "signature": {
            "signatureText": agreement.signature_text,
            "signatureImageUrl": _file_url(request, agreement.signature_image),
            "signatureImagePath": _file_path(agreement.signature_image),
            "acceptedTerms": agreement.accepted_terms,
            "signedAt": agreement.signed_at,
            "signedIp": agreement.signed_ip,
        },
        "signedDocument": {
            "url": _file_url(request, agreement.signed_pdf),
            "path": _file_path(agreement.signed_pdf),
            "downloadApi": f"/api/agreements/{application.id}/download/",
            "isGenerated": bool(agreement.signed_pdf),
        },
        "coApplicant": {
            "status": agreement.co_applicant_status,
            "statusLabel": _co_applicant_status_label(agreement.co_applicant_status),
            "latestInvitation": _invitation_response(request, latest_invite) if latest_invite else None,
        },
        "screen": {
            "title": "Sign Agreement",
            "subtitle": "Review and e-sign your loan document",
            "successTitle": "Document Signed!",
            "successMessage": "Your loan agreement has been signed and saved securely.",
        },
        "actions": {
            "canSign": agreement.status != LoanAgreement.STATUS_SIGNED and application.status in [
                LoanApplication.STATUS_APPROVED,
                LoanApplication.STATUS_COMPLETED,
            ],
            "canDownload": bool(agreement.signed_pdf),
            "canInviteCoApplicant": agreement.status == LoanAgreement.STATUS_SIGNED,
            "previewApi": f"/api/agreements/{application.id}/",
            "signApi": f"/api/agreements/{application.id}/sign/",
            "inviteCoApplicantApi": f"/api/agreements/{application.id}/co-applicant/invite/",
            "skipCoApplicantApi": f"/api/agreements/{application.id}/co-applicant/skip/",
        },
        "createdAt": agreement.created_at,
        "updatedAt": agreement.updated_at,
    }


def _escape_pdf_text(text):
    text = str(text or "")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _make_basic_pdf(title, lines):
    wrapped_lines = []

    for line in lines:
        if line is None:
            continue

        text = str(line)

        if not text.strip():
            wrapped_lines.append("")
            continue

        wrapped_lines.extend(textwrap.wrap(text, width=88) or [""])

    commands = ["BT", "/F1 16 Tf", "72 780 Td", f"({_escape_pdf_text(title)}) Tj"]
    commands.extend(["/F1 10 Tf", "0 -24 Td"])

    for line in wrapped_lines[:60]:
        commands.append(f"({_escape_pdf_text(line)}) Tj")
        commands.append("0 -15 Td")

    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", errors="replace")

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode())
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_start = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")

    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())

    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode()
    )
    return bytes(pdf)


def _generate_signed_pdf(agreement):
    application = agreement.application
    summary = _loan_summary(application)
    sections = _agreement_sections(application)

    lines = [
        f"Reference: {application.application_number}",
        f"Borrower: {_get_user_full_name(agreement.borrower)}",
        f"Borrower Email: {_get_user_email(agreement.borrower)}",
        f"Lender: {agreement.lender_name}",
        f"Loan Type: {summary.get('loanType')}",
        f"Loan Amount: {summary.get('loanAmountDisplay')}",
        f"Loan Term: {summary.get('loanTerm')}",
        f"Interest Rate: {summary.get('interestRate')}",
        f"Monthly Payment: {summary.get('monthlyPaymentDisplay')}",
        "",
        "Agreement Sections:",
    ]

    for section in sections:
        lines.append(f"{section.get('order')}. {section.get('title')}")
        lines.append(section.get("description"))
        lines.append("")

    lines.extend([
        "Signature:",
        agreement.signature_text or "Signature image attached by customer.",
        f"Accepted Terms: {'Yes' if agreement.accepted_terms else 'No'}",
        f"Signed At: {timezone.localtime(agreement.signed_at).strftime('%b %d, %Y, %I:%M %p') if agreement.signed_at else ''}",
        f"Signed IP: {agreement.signed_ip or ''}",
    ])

    return _make_basic_pdf("Loan Agreement", lines)


def _save_base64_signature(agreement, base64_data):
    if not base64_data:
        return False

    raw = str(base64_data)

    if ";base64," in raw:
        raw = raw.split(";base64,", 1)[1]
    elif "," in raw:
        raw = raw.split(",", 1)[1]

    try:
        decoded = base64.b64decode(raw)
    except Exception:
        return False

    agreement.signature_image.save(
        f"{agreement.application.application_number}_signature.png",
        ContentFile(decoded),
        save=False,
    )
    return True


class CustomerAgreementDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        application = _get_application_for_customer(request.user, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        agreement = _get_or_create_agreement(application)

        return build_response(
            request,
            success=True,
            message="Loan agreement fetched successfully",
            data=_agreement_response(request, agreement),
            status_code=status.HTTP_200_OK,
        )


class CustomerAgreementSignView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, application_id):
        application = _get_application_for_customer(request.user, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        agreement = _get_or_create_agreement(application)

        if application.status not in [LoanApplication.STATUS_APPROVED, LoanApplication.STATUS_COMPLETED]:
            return build_response(
                request,
                success=False,
                message="Only approved applications can be signed",
                data={
                    "currentStatus": application.status,
                    "hint": "Approve the application from admin panel first, then try signing agreement.",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if agreement.status == LoanAgreement.STATUS_SIGNED:
            return build_response(
                request,
                success=False,
                message="Agreement is already signed",
                data=_agreement_response(request, agreement),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        accepted_terms = _truthy(
            request.data.get("accepted_terms")
            or request.data.get("acceptedTerms")
        )

        signature_text = request.data.get("signature_text") or request.data.get("signatureText")
        signature_base64 = request.data.get("signature_base64") or request.data.get("signatureBase64")
        signature_file = (
            request.FILES.get("signature_image")
            or request.FILES.get("signature")
            or request.FILES.get("file")
        )

        errors = {}

        if not accepted_terms:
            errors["accepted_terms"] = ["You must accept the agreement terms before signing."]

        if not signature_text and not signature_base64 and not signature_file:
            errors["signature"] = ["Signature text, base64 signature, or signature image is required."]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if signature_file:
            if agreement.signature_image:
                agreement.signature_image.delete(save=False)
            agreement.signature_image = signature_file

        if signature_base64:
            if agreement.signature_image:
                agreement.signature_image.delete(save=False)
            saved = _save_base64_signature(agreement, signature_base64)
            if not saved:
                return build_response(
                    request,
                    success=False,
                    message="Invalid base64 signature data",
                    data={},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        agreement.signature_text = str(signature_text).strip() if signature_text else agreement.signature_text
        agreement.accepted_terms = True
        agreement.status = LoanAgreement.STATUS_SIGNED
        agreement.signed_at = timezone.now()
        agreement.signed_ip = _get_client_ip(request)
        agreement.signed_user_agent = request.META.get("HTTP_USER_AGENT", "")

        pdf_bytes = _generate_signed_pdf(agreement)

        if agreement.signed_pdf:
            agreement.signed_pdf.delete(save=False)

        agreement.signed_pdf.save(
            f"{application.application_number}_signed_agreement.pdf",
            ContentFile(pdf_bytes),
            save=False,
        )
        agreement.save()

        if application.status == LoanApplication.STATUS_APPROVED:
            application.status = LoanApplication.STATUS_COMPLETED
            application.save(update_fields=["status", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Loan agreement signed successfully",
            data=_agreement_response(request, agreement),
            status_code=status.HTTP_200_OK,
        )


class CustomerAgreementDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        application = _get_application_for_customer(request.user, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        agreement = _get_or_create_agreement(application)

        if not agreement.signed_pdf:
            return build_response(
                request,
                success=False,
                message="Signed PDF is not available yet",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        filename = os.path.basename(agreement.signed_pdf.name)
        return FileResponse(
            agreement.signed_pdf.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type="application/pdf",
        )


class CoApplicantInviteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        application = _get_application_for_customer(request.user, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        agreement = _get_or_create_agreement(application)

        if agreement.status != LoanAgreement.STATUS_SIGNED:
            return build_response(
                request,
                success=False,
                message="Please sign the agreement before inviting a co-applicant",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        name = (
            request.data.get("name")
            or request.data.get("co_applicant_name")
            or request.data.get("coApplicantName")
            or ""
        ).strip()

        email = (
            request.data.get("email")
            or request.data.get("co_applicant_email")
            or request.data.get("coApplicantEmail")
            or ""
        ).strip().lower()

        message = (request.data.get("message") or "").strip()

        errors = {}

        if not name:
            errors["name"] = ["Co-applicant name is required."]

        if not email or "@" not in email:
            errors["email"] = ["Valid co-applicant email is required."]

        if errors:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        invite = CoApplicantInvitation.objects.create(
            agreement=agreement,
            name=name,
            email=email,
            message=message,
        )

        site_base_url = str(getattr(settings, "SITE_BASE_URL", "") or "").rstrip("/")
        if not site_base_url:
            site_base_url = request.build_absolute_uri("/").rstrip("/")

        invite.invite_link = f"{site_base_url}/co-applicant/invite/{invite.token}"
        invite.save(update_fields=["invite_link", "updated_at"])

        agreement.co_applicant_status = LoanAgreement.CO_APPLICANT_INVITED
        agreement.save(update_fields=["co_applicant_status", "updated_at"])

        try:
            send_mail(
                subject="You have been invited as a co-applicant",
                message=(
                    f"Hello {name},\n\n"
                    f"You have been invited to join loan application {application.application_number}.\n"
                    f"Open this link: {invite.invite_link}\n\n"
                    "If the property is jointly owned, the loan application must be in both names."
                ),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[email],
                fail_silently=True,
            )
        except Exception:
            pass

        return build_response(
            request,
            success=True,
            message="Co-applicant invitation sent successfully",
            data={
                "agreement": _agreement_response(request, agreement),
                "invitation": _invitation_response(request, invite),
            },
            status_code=status.HTTP_201_CREATED,
        )


class CoApplicantSkipView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        application = _get_application_for_customer(request.user, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        agreement = _get_or_create_agreement(application)
        agreement.co_applicant_status = LoanAgreement.CO_APPLICANT_SKIPPED
        agreement.save(update_fields=["co_applicant_status", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Co-applicant invitation skipped successfully",
            data=_agreement_response(request, agreement),
            status_code=status.HTTP_200_OK,
        )


class CoApplicantInvitationDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        invite = (
            CoApplicantInvitation.objects
            .select_related("agreement", "agreement__application", "agreement__application__loan_type")
            .filter(token=token)
            .first()
        )

        if not invite:
            return build_response(
                request,
                success=False,
                message="Invitation not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return build_response(
            request,
            success=True,
            message="Co-applicant invitation fetched successfully",
            data={
                "invitation": _invitation_response(request, invite),
                "agreement": _agreement_response(request, invite.agreement),
            },
            status_code=status.HTTP_200_OK,
        )


class CoApplicantInvitationRespondView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, token):
        invite = CoApplicantInvitation.objects.select_related("agreement").filter(token=token).first()

        if not invite:
            return build_response(
                request,
                success=False,
                message="Invitation not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        action = str(request.data.get("action") or "accept").lower()

        if action not in ["accept", "decline"]:
            return build_response(
                request,
                success=False,
                message="Invalid action. Use accept or decline.",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if action == "accept":
            invite.status = CoApplicantInvitation.STATUS_ACCEPTED
            invite.accepted_at = timezone.now()
            invite.agreement.co_applicant_status = LoanAgreement.CO_APPLICANT_ACCEPTED
            invite.agreement.save(update_fields=["co_applicant_status", "updated_at"])
            message = "Co-applicant invitation accepted successfully"
        else:
            invite.status = CoApplicantInvitation.STATUS_DECLINED
            invite.declined_at = timezone.now()
            message = "Co-applicant invitation declined successfully"

        invite.save()

        return build_response(
            request,
            success=True,
            message=message,
            data=_invitation_response(request, invite),
            status_code=status.HTTP_200_OK,
        )