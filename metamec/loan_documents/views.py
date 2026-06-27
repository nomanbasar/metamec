import os

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from authentication.utils import build_response
from user_notifications.events import (
    notify_document_uploaded,
    notify_documents_completed,
)

from loan_applications.models import LoanApplication

from .models import LoanApplicationDocument
from .serializers import LoanApplicationDocumentSerializer


REQUIRED_DOCUMENTS = [
    {
        "categoryKey": "identity_documents",
        "categoryTitle": "Identity Documents",
        "documentType": "passport_driving_license",
        "title": "Passport / Driving License",
        "description": "Valid photo ID",
        "isRequired": True,
    },
    {
        "categoryKey": "identity_documents",
        "categoryTitle": "Identity Documents",
        "documentType": "recent_photograph",
        "title": "Recent Photograph",
        "description": "Clear selfie or passport-style photograph",
        "isRequired": True,
    },
    {
        "categoryKey": "financial_documents",
        "categoryTitle": "Financial Documents",
        "documentType": "payslips_3_months",
        "title": "Last 3 Months Payslips",
        "description": "Signed payslips from your employer",
        "isRequired": True,
    },
    {
        "categoryKey": "financial_documents",
        "categoryTitle": "Financial Documents",
        "documentType": "latest_tax_return",
        "title": "Latest Tax Return",
        "description": "Most recent annual tax assessment",
        "isRequired": True,
    },
    {
        "categoryKey": "financial_documents",
        "categoryTitle": "Financial Documents",
        "documentType": "bank_statement",
        "title": "Bank Statement",
        "description": "Recent bank statement",
        "isRequired": True,
    },
]

ALLOWED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".mp4", ".pdf", ".psd", ".ai", ".doc", ".docx", ".ppt", ".pptx"]
MAX_FILE_SIZE_MB = 20
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def get_customer_application(request, application_id):
    return LoanApplication.objects.select_related(
        "loan_type",
        "loan_type__template",
    ).filter(
        id=application_id,
        user=request.user,
    ).first()


def get_uploaded_map(application):
    documents = application.documents.all()
    return {
        document.document_type: document
        for document in documents
    }


def build_documents_response(application):
    uploaded_map = get_uploaded_map(application)

    required_count = len(REQUIRED_DOCUMENTS)
    uploaded_count = len(uploaded_map)
    remaining_count = max(required_count - uploaded_count, 0)
    progress_percent = int(round((uploaded_count / required_count) * 100)) if required_count else 0
    is_completed = remaining_count == 0

    categories_map = {}

    for item in REQUIRED_DOCUMENTS:
        category_key = item["categoryKey"]

        if category_key not in categories_map:
            categories_map[category_key] = {
                "categoryKey": category_key,
                "categoryTitle": item["categoryTitle"],
                "uploadedCount": 0,
                "requiredCount": 0,
                "uploadedText": "0/0 uploaded",
                "documents": [],
            }

        uploaded_document = uploaded_map.get(item["documentType"])
        is_uploaded = uploaded_document is not None

        categories_map[category_key]["requiredCount"] += 1

        if is_uploaded:
            categories_map[category_key]["uploadedCount"] += 1

        categories_map[category_key]["documents"].append({
            "documentType": item["documentType"],
            "title": item["title"],
            "description": item["description"],
            "isRequired": item["isRequired"],
            "isUploaded": is_uploaded,
            "status": "uploaded" if is_uploaded else "missing",
            "uploadedDocument": LoanApplicationDocumentSerializer(uploaded_document).data if uploaded_document else None,
        })

    categories = []

    for category in categories_map.values():
        category["uploadedText"] = f'{category["uploadedCount"]}/{category["requiredCount"]} uploaded'
        categories.append(category)

    success_screen = None

    if is_completed:
        success_screen = {
            "title": "Upload successfully",
            "applicationNumber": application.application_number,
            "message": "We'll review your application and contact you shortly. You can track the status in My Loan.",
            "buttons": {
                "viewMyLoan": True,
                "callUsNow": True,
                "inviteCoApplicant": True,
            },
            "note": "Please upload your documents to progress your application and receive your funds. If the property is jointly owned, please invite your co-applicant.",
        }

    return {
        "application": {
            "id": application.id,
            "applicationNumber": application.application_number,
            "loanType": {
                "id": application.loan_type.id,
                "name": application.loan_type.name,
            },
            "status": application.status,
        },
        "summary": {
            "requiredCount": required_count,
            "uploadedCount": uploaded_count,
            "remainingCount": remaining_count,
            "progressPercent": progress_percent,
            "uploadedText": f"{uploaded_count}/{required_count} uploaded",
            "statusText": f"{remaining_count} required remaining",
            "isCompleted": is_completed,
        },
        "notice": {
            "text": "Documents marked * are mandatory. Optional documents may speed up your application review. All files are encrypted and stored securely.",
            "mandatorySymbol": "*",
        },
        "supportedFormats": {
            "text": "JPEG, PNG, GIF, MP4, PDF, PSD, AI, Word, PPT",
            "extensions": ALLOWED_EXTENSIONS,
            "maxFileSizeMb": MAX_FILE_SIZE_MB,
        },
        "categories": categories,
        "successScreen": success_screen,
    }


class CustomerApplicationDocumentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, application_id):
        application = get_customer_application(request, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if application.status == LoanApplication.STATUS_DRAFT:
            return build_response(
                request,
                success=False,
                message="Please submit application before uploading documents",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return build_response(
            request,
            success=True,
            message="Required documents fetched successfully",
            data=build_documents_response(application),
            status_code=status.HTTP_200_OK,
        )


class CustomerApplicationDocumentUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, application_id):
        application = get_customer_application(request, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if application.status == LoanApplication.STATUS_DRAFT:
            return build_response(
                request,
                success=False,
                message="Please submit application before uploading documents",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        document_type = request.data.get("documentType")
        uploaded_file = request.FILES.get("file")

        valid_document_types = [item["documentType"] for item in REQUIRED_DOCUMENTS]

        if not document_type:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={"documentType": ["This field is required."]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if document_type not in valid_document_types:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={"documentType": ["Invalid document type."]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if not uploaded_file:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={"file": ["This field is required."]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        extension = os.path.splitext(uploaded_file.name)[1].lower()

        if extension not in ALLOWED_EXTENSIONS:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={"file": [f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if uploaded_file.size > MAX_FILE_SIZE_BYTES:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={"file": [f"File size must be less than or equal to {MAX_FILE_SIZE_MB}MB."]},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        existing_document = LoanApplicationDocument.objects.filter(
            application=application,
            document_type=document_type,
        ).first()

        if existing_document:
            if existing_document.file:
                existing_document.file.delete(save=False)

            existing_document.file = uploaded_file
            existing_document.original_file_name = uploaded_file.name
            existing_document.file_size = uploaded_file.size
            existing_document.mime_type = getattr(uploaded_file, "content_type", "")
            existing_document.status = LoanApplicationDocument.STATUS_UPLOADED
            existing_document.save()

            document = existing_document
            message = "Document replaced successfully"
        else:
            document = LoanApplicationDocument.objects.create(
                application=application,
                document_type=document_type,
                file=uploaded_file,
                original_file_name=uploaded_file.name,
                file_size=uploaded_file.size,
                mime_type=getattr(uploaded_file, "content_type", ""),
                status=LoanApplicationDocument.STATUS_UPLOADED,
            )
            message = "Document uploaded successfully"
        notify_document_uploaded(document, replaced=bool(existing_document))
        return build_response(
            request,
            success=True,
            message=message,
            data={
                "document": LoanApplicationDocumentSerializer(document).data,
                "documents": build_documents_response(application),
            },
            status_code=status.HTTP_201_CREATED,
        )


class CustomerDocumentDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, document_id):
        document = LoanApplicationDocument.objects.select_related(
            "application",
            "application__user",
        ).filter(
            id=document_id,
            application__user=request.user,
        ).first()

        if not document:
            return build_response(
                request,
                success=False,
                message="Document not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        application = document.application

        if application.status == LoanApplication.STATUS_DRAFT:
            return build_response(
                request,
                success=False,
                message="Draft application document cannot be deleted here",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if document.file:
            document.file.delete(save=False)

        document.delete()

        return build_response(
            request,
            success=True,
            message="Document removed successfully",
            data=build_documents_response(application),
            status_code=status.HTTP_200_OK,
        )


class CustomerApplicationDocumentsCompleteView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, application_id):
        application = get_customer_application(request, application_id)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if application.status == LoanApplication.STATUS_DRAFT:
            return build_response(
                request,
                success=False,
                message="Please submit application before completing documents",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_types = set(application.documents.values_list("document_type", flat=True))
        required_types = set(item["documentType"] for item in REQUIRED_DOCUMENTS)

        missing_types = list(required_types - uploaded_types)

        if missing_types:
            missing_documents = [
                item
                for item in REQUIRED_DOCUMENTS
                if item["documentType"] in missing_types
            ]

            return build_response(
                request,
                success=False,
                message="Please upload all required documents before continue",
                data={
                    "missingDocuments": missing_documents,
                    "documents": build_documents_response(application),
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if application.status in [
            LoanApplication.STATUS_SUBMITTED,
            LoanApplication.STATUS_PENDING_DOCUMENTS,
            LoanApplication.STATUS_KYC_REQUIRED,
        ]:
            application.status = LoanApplication.STATUS_UNDER_REVIEW
            application.save(update_fields=["status", "updated_at"])

        notify_documents_completed(application)
        response_data = build_documents_response(application)

        response_data["successScreen"] = {
            "title": "Upload successfully",
            "applicationNumber": application.application_number,
            "message": "We'll review your application and contact you shortly. You can track the status in My Loan.",
            "buttons": {
                "viewMyLoan": True,
                "callUsNow": True,
                "inviteCoApplicant": True,
            },
            "note": "Please upload your documents to progress your application and receive your funds. If the property is jointly owned, please invite your co-applicant.",
        }

        return build_response(
            request,
            success=True,
            message="Documents completed successfully",
            data=response_data,
            status_code=status.HTTP_200_OK,
        )