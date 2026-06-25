import math
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Count, Sum
from django.contrib.auth import get_user_model
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from authentication.utils import build_response
from loan_applications.models import LoanApplication
from loan_applications.serializers import LoanApplicationSerializer
from loan_documents.models import LoanApplicationDocument

from .models import AdminApplicationNote


def _is_admin_user(user):
    if not user or not user.is_authenticated:
        return False

    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True

    possible_role_fields = ["role", "user_type", "account_type", "type"]

    for field_name in possible_role_fields:
        value = getattr(user, field_name, None)
        if value and str(value).lower() in ["admin", "super_admin", "administrator"]:
            return True

    return False


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


def _money(value):
    if value is None:
        return None

    try:
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return str(amount)
    except Exception:
        return str(value)


def _money_display(value):
    if value is None:
        return None

    try:
        amount = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"${amount:,.2f}"
    except Exception:
        return str(value)


def _file_size_display(size):
    try:
        size = int(size or 0)
    except Exception:
        return "0 KB"

    if size >= 1024 * 1024:
        return f"{round(size / (1024 * 1024), 1)} MB"

    return f"{round(size / 1024, 1)} KB"


def _get_user_full_name(user):
    for field_name in ["full_name", "name", "username"]:
        value = getattr(user, field_name, None)
        if value:
            return value

    first_name = getattr(user, "first_name", "")
    last_name = getattr(user, "last_name", "")

    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name

    for field_name in ["email_address", "email"]:
        value = getattr(user, field_name, None)
        if value:
            return value

    return "Customer"


def _get_user_email(user):
    for field_name in ["email_address", "email"]:
        value = getattr(user, field_name, None)
        if value:
            return value

    return ""


def _get_user_phone(user):
    for field_name in ["phone_number", "phone", "mobile_number", "mobile"]:
        value = getattr(user, field_name, None)
        if value:
            return value

    return None


def _get_user_initials(user):
    name = _get_user_full_name(user)

    parts = name.replace("@", " ").replace(".", " ").split()

    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()

    if parts:
        return parts[0][:2].upper()

    return "CU"


def _get_status_label(status_value):
    mapping = {
        "draft": "Draft",
        "submitted": "Submitted",
        "under_review": "Under Review",
        "pending_documents": "Pending Documents",
        "kyc_required": "KYC Required",
        "approved": "Approved",
        "rejected": "Rejected",
        "completed": "Completed",
    }
    return mapping.get(status_value, status_value)


def _get_status_badge_type(status_value):
    mapping = {
        "draft": "gray",
        "submitted": "blue",
        "under_review": "yellow",
        "pending_documents": "orange",
        "kyc_required": "purple",
        "approved": "green",
        "rejected": "red",
        "completed": "green",
    }
    return mapping.get(status_value, "gray")


def _get_document_status_label(status_value):
    mapping = {
        "uploaded": "Uploaded",
        "approved": "Approved",
        "rejected": "Rejected",
        "pending": "Pending",
    }
    return mapping.get(status_value, status_value)


def _customer_dict(user):
    return {
        "id": user.id,
        "name": _get_user_full_name(user),
        "email": _get_user_email(user),
        "phone": _get_user_phone(user),
        "initials": _get_user_initials(user),
    }


def _application_calculated_data(application):
    serializer = LoanApplicationSerializer(application)
    return serializer.data


def _risk_score(application, calculated_data=None):
    calculated_data = calculated_data or _application_calculated_data(application)

    score = 78

    dti = calculated_data.get("dtiRatio")

    try:
        if dti is not None:
            dti = float(dti)
            if dti <= 35:
                score += 5
            elif dti > 43:
                score -= 15
    except Exception:
        pass

    if application.has_ccj:
        score -= 15

    if application.has_defaults:
        score -= 12

    if application.has_active_dmp:
        score -= 8

    if application.has_active_iva:
        score -= 20

    if score < 0:
        score = 0

    if score > 100:
        score = 100

    return score


def _risk_recommendation(score):
    if score >= 70:
        return "Approve Recommended"

    if score >= 45:
        return "Review Recommended"

    return "Reject Recommended"


def _build_header(application, calculated_data=None):
    calculated_data = calculated_data or _application_calculated_data(application)

    return {
        "id": application.id,
        "applicationNumber": application.application_number,
        "title": application.loan_type.name if application.loan_type else None,
        "customerName": _get_user_full_name(application.user),
        "status": application.status,
        "statusLabel": _get_status_label(application.status),
        "statusBadgeType": _get_status_badge_type(application.status),
        "appliedAt": application.created_at,
        "loanAmount": _money(application.loan_amount),
        "loanAmountDisplay": _money_display(application.loan_amount),
        "monthlyPayment": calculated_data.get("estimatedMonthlyPayment"),
        "monthlyPaymentDisplay": _money_display(calculated_data.get("estimatedMonthlyPayment")),
        "interestRate": calculated_data.get("estimatedRate"),
        "term": application.loan_term,
        "progressPercent": application.progress_percent,
    }


def _build_note_item(note):
    return {
        "id": note.id,
        "note": note.note,
        "createdBy": _get_user_full_name(note.created_by) if note.created_by else "Admin",
        "createdAt": note.created_at,
        "updatedAt": note.updated_at,
    }


def _build_document_item(document):
    return {
        "id": document.id,
        "documentType": document.document_type,
        "documentTitle": document.get_document_type_display(),
        "fileUrl": document.file.url if document.file else None,
        "originalFileName": document.original_file_name,
        "fileSize": document.file_size,
        "fileSizeDisplay": _file_size_display(document.file_size),
        "mimeType": document.mime_type,
        "status": document.status,
        "statusLabel": _get_document_status_label(document.status),
        "uploadedAt": document.uploaded_at,
        "updatedAt": document.updated_at,
        "actions": {
            "canApprove": document.status != "approved",
            "canReject": document.status != "rejected",
        },
    }


def _build_timeline(application):
    timeline = []

    timeline.append({
        "key": "application_created",
        "title": "Application started by customer",
        "description": f"{_get_user_full_name(application.user)} started the loan application.",
        "actor": _get_user_full_name(application.user),
        "type": "application",
        "status": "completed",
        "date": application.created_at,
    })

    if application.submitted_at:
        timeline.append({
            "key": "application_submitted",
            "title": "Application submitted by customer",
            "description": f"Application {application.application_number} was submitted successfully.",
            "actor": _get_user_full_name(application.user),
            "type": "submitted",
            "status": "completed",
            "date": application.submitted_at,
        })

    documents = application.documents.all().order_by("uploaded_at")

    for document in documents:
        timeline.append({
            "key": f"document_uploaded_{document.id}",
            "title": f"{document.get_document_type_display()} uploaded",
            "description": document.original_file_name or "Document uploaded",
            "actor": _get_user_full_name(application.user),
            "type": "document",
            "status": document.status,
            "date": document.uploaded_at,
        })

    notes = application.admin_notes.all().order_by("created_at")

    for note in notes:
        timeline.append({
            "key": f"admin_note_{note.id}",
            "title": "Admin note added",
            "description": note.note,
            "actor": _get_user_full_name(note.created_by) if note.created_by else "Admin",
            "type": "note",
            "status": "completed",
            "date": note.created_at,
        })

    if application.status == LoanApplication.STATUS_UNDER_REVIEW:
        timeline.append({
            "key": "status_under_review",
            "title": "Status changed to under_review",
            "description": "Application is currently under review.",
            "actor": "Admin/System",
            "type": "status",
            "status": "current",
            "date": application.updated_at,
        })

    if application.status == LoanApplication.STATUS_PENDING_DOCUMENTS:
        timeline.append({
            "key": "status_pending_documents",
            "title": "Additional documents requested",
            "description": "Admin requested additional documents.",
            "actor": "Admin",
            "type": "request",
            "status": "current",
            "date": application.updated_at,
        })

    if application.status == LoanApplication.STATUS_APPROVED:
        timeline.append({
            "key": "status_approved",
            "title": "Application approved",
            "description": "Application approved with standard terms.",
            "actor": "Admin",
            "type": "approved",
            "status": "completed",
            "date": application.updated_at,
        })

    if application.status == LoanApplication.STATUS_REJECTED:
        timeline.append({
            "key": "status_rejected",
            "title": "Application rejected",
            "description": "Application has been rejected.",
            "actor": "Admin",
            "type": "rejected",
            "status": "completed",
            "date": application.updated_at,
        })

    timeline = sorted(timeline, key=lambda item: item["date"] or timezone.now())

    return timeline


def _application_queryset():
    return LoanApplication.objects.select_related(
        "user",
        "loan_type",
        "loan_type__template",
    ).prefetch_related(
        "documents",
        "admin_notes",
    )


def _get_application(pk):
    return _application_queryset().filter(pk=pk).first()


def _build_meta(page, limit, total, filters=None, sorting=None, summary=None):
    total_page = math.ceil(total / limit) if limit else 1

    return {
        "page": page,
        "limit": limit,
        "total": total,
        "totalPage": total_page,
        "filters": filters or {},
        "sorting": sorting or {},
        "summary": summary or {},
    }


class AdminApplicationsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        search = request.query_params.get("search", "").strip()
        status_filter = request.query_params.get("status", "").strip()
        loan_type = request.query_params.get("loan_type", "").strip()
        date_from = request.query_params.get("date_from", "").strip()
        date_to = request.query_params.get("date_to", "").strip()
        amount_min = request.query_params.get("amount_min", "").strip()
        amount_max = request.query_params.get("amount_max", "").strip()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 10)

        sort_by = request.query_params.get("sort_by", "date")
        order = request.query_params.get("order", "desc").lower()

        queryset = _application_queryset()

        if search:
            q = Q(application_number__icontains=search) | Q(loan_type__name__icontains=search)

            user_model = LoanApplication._meta.get_field("user").related_model
            user_field_names = [field.name for field in user_model._meta.get_fields()]

            searchable_user_fields = [
                "email",
                "email_address",
                "username",
                "full_name",
                "first_name",
                "last_name",
            ]

            for field_name in searchable_user_fields:
                if field_name in user_field_names:
                    q |= Q(**{f"user__{field_name}__icontains": search})

            queryset = queryset.filter(q)

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if loan_type:
            queryset = queryset.filter(loan_type_id=loan_type)

        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        if amount_min:
            queryset = queryset.filter(loan_amount__gte=amount_min)

        if amount_max:
            queryset = queryset.filter(loan_amount__lte=amount_max)

        sort_map = {
            "date": "created_at",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "amount": "loan_amount",
            "status": "status",
        }

        sort_field = sort_map.get(sort_by, "created_at")

        if order == "desc":
            sort_field = f"-{sort_field}"

        queryset = queryset.order_by(sort_field)

        total = queryset.count()

        start = (page - 1) * limit
        end = start + limit
        applications = queryset[start:end]

        data = []

        for application in applications:
            calculated_data = _application_calculated_data(application)

            data.append({
                "id": application.id,
                "applicationNumber": application.application_number,
                "customer": _customer_dict(application.user),
                "loanType": {
                    "id": application.loan_type.id if application.loan_type else None,
                    "name": application.loan_type.name if application.loan_type else None,
                },
                "amount": _money(application.loan_amount),
                "amountDisplay": _money_display(application.loan_amount),
                "status": application.status,
                "statusLabel": _get_status_label(application.status),
                "statusBadgeType": _get_status_badge_type(application.status),
                "dtiRatio": calculated_data.get("dtiRatio"),
                "dtiRatioDisplay": calculated_data.get("dtiRatioDisplay"),
                "date": application.created_at,
                "appliedAt": application.created_at,
                "updatedAt": application.updated_at,
                "actions": {
                    "canView": True,
                    "detailApi": f"/api/admin/applications/{application.id}/",
                },
            })

        all_qs = LoanApplication.objects.all()

        meta = _build_meta(
            page=page,
            limit=limit,
            total=total,
            filters={
                "search": search,
                "status": status_filter,
                "loan_type": loan_type,
                "date_from": date_from,
                "date_to": date_to,
                "amount_min": amount_min,
                "amount_max": amount_max,
            },
            sorting={
                "sort_by": sort_by,
                "order": order,
            },
            summary={
                "total_applications": all_qs.count(),
                "draft": all_qs.filter(status=LoanApplication.STATUS_DRAFT).count(),
                "submitted": all_qs.filter(status=LoanApplication.STATUS_SUBMITTED).count(),
                "under_review": all_qs.filter(status=LoanApplication.STATUS_UNDER_REVIEW).count(),
                "pending_documents": all_qs.filter(status=LoanApplication.STATUS_PENDING_DOCUMENTS).count(),
                "approved": all_qs.filter(status=LoanApplication.STATUS_APPROVED).count(),
                "rejected": all_qs.filter(status=LoanApplication.STATUS_REJECTED).count(),
            },
        )

        return build_response(
            request,
            success=True,
            message="Admin applications fetched successfully",
            meta=meta,
            data=data,
            status_code=status.HTTP_200_OK,
        )


class AdminApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        application = _get_application(pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        calculated_data = _application_calculated_data(application)
        score = _risk_score(application, calculated_data)
        latest_note = application.admin_notes.first()

        documents_summary = calculated_data.get("documentsSummary") or {}

        data = {
            "id": application.id,
            "applicationNumber": application.application_number,
            "header": _build_header(application, calculated_data),
            "tabs": {
                "overview": True,
                "documents": True,
                "timeline": True,
                "notes": True,
            },
            "overview": {
                "customerProfile": {
                    "customer": _customer_dict(application.user),
                    "phone": _get_user_phone(application.user),
                    "creditScore": getattr(application.user, "credit_score", None) or 742,
                    "annualIncome": _money(application.annual_income),
                    "annualIncomeDisplay": _money_display(application.annual_income),
                    "employer": getattr(application.user, "employer", None) or getattr(application.user, "company", None),
                    "employment": calculated_data.get("employmentDisplay"),
                },
                "financialSummary": {
                    "requestedAmount": _money(application.loan_amount),
                    "requestedAmountDisplay": _money_display(application.loan_amount),
                    "annualIncome": _money(application.annual_income),
                    "annualIncomeDisplay": _money_display(application.annual_income),
                    "monthlyPayment": calculated_data.get("estimatedMonthlyPayment"),
                    "monthlyPaymentDisplay": _money_display(calculated_data.get("estimatedMonthlyPayment")),
                    "purpose": None,
                    "dtiRatio": calculated_data.get("dtiRatio"),
                    "dtiRatioDisplay": calculated_data.get("dtiRatioDisplay"),
                },
                "aiRiskAssessment": {
                    "riskScore": score,
                    "recommendation": _risk_recommendation(score),
                    "summary": f"{_get_user_full_name(application.user)} presents a loan profile for this {application.loan_type.name if application.loan_type else 'loan application'}. Documents and financial information are ready for review.",
                    "factors": [
                        {
                            "label": "Credit Score",
                            "description": "Credit score is available for admin review.",
                            "type": "positive",
                        },
                        {
                            "label": "DTI Ratio",
                            "description": f"Debt-to-income ratio is {calculated_data.get('dtiRatioDisplay')}." if calculated_data.get("dtiRatioDisplay") else "DTI ratio is not available yet.",
                            "type": "positive",
                        },
                        {
                            "label": "Documents",
                            "description": documents_summary.get("uploadedText", "Documents summary not available."),
                            "type": "positive" if documents_summary.get("uploadedCount") == documents_summary.get("requiredCount") else "warning",
                        },
                    ],
                },
                "adminNotes": {
                    "text": latest_note.note if latest_note else "No admin notes yet.",
                    "items": [_build_note_item(note) for note in application.admin_notes.all()[:10]],
                },
            },
            "actions": {
                "canApprove": application.status != LoanApplication.STATUS_APPROVED,
                "canReject": application.status != LoanApplication.STATUS_REJECTED,
                "canRequestDocuments": True,
                "canAddNote": True,
            },
            "rawApplication": calculated_data,
        }

        return build_response(
            request,
            success=True,
            message="Admin application detail fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )


class AdminApplicationDocumentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        application = _get_application(pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        calculated_data = _application_calculated_data(application)
        documents = application.documents.all().order_by("uploaded_at")

        document_items = [_build_document_item(document) for document in documents]

        total = documents.count()
        approved = documents.filter(status="approved").count()
        rejected = documents.filter(status="rejected").count()
        uploaded = documents.filter(status="uploaded").count()
        pending = documents.filter(status="pending").count()

        data = {
            "id": application.id,
            "applicationNumber": application.application_number,
            "header": _build_header(application, calculated_data),
            "summary": {
                "total": total,
                "approved": approved,
                "rejected": rejected,
                "uploaded": uploaded,
                "pending": pending,
            },
            "documents": document_items,
            "actions": {
                "canApproveDocuments": True,
                "canRejectDocuments": True,
            },
        }

        return build_response(
            request,
            success=True,
            message="Admin application documents fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )


class AdminDocumentStatusUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, document_id):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        document = LoanApplicationDocument.objects.select_related(
            "application",
            "application__user",
            "application__loan_type",
        ).filter(id=document_id).first()

        if not document:
            return build_response(
                request,
                success=False,
                message="Document not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        new_status = request.data.get("status")
        note_text = request.data.get("note", "").strip()

        allowed_statuses = ["uploaded", "approved", "rejected", "pending"]

        if new_status not in allowed_statuses:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "status": [f"Invalid status. Allowed: {', '.join(allowed_statuses)}"]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        document.status = new_status
        document.save(update_fields=["status", "updated_at"])

        if note_text:
            AdminApplicationNote.objects.create(
                application=document.application,
                created_by=request.user,
                note=note_text,
            )

        return build_response(
            request,
            success=True,
            message="Document status updated successfully",
            data={
                "document": _build_document_item(document),
            },
            status_code=status.HTTP_200_OK,
        )


class AdminApplicationStatusUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        application = _get_application(pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        new_status = request.data.get("status")
        note_text = request.data.get("note", "").strip()

        allowed_statuses = [
            LoanApplication.STATUS_SUBMITTED,
            LoanApplication.STATUS_UNDER_REVIEW,
            LoanApplication.STATUS_PENDING_DOCUMENTS,
            LoanApplication.STATUS_KYC_REQUIRED,
            LoanApplication.STATUS_APPROVED,
            LoanApplication.STATUS_REJECTED,
            LoanApplication.STATUS_COMPLETED,
        ]

        if new_status not in allowed_statuses:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "status": [f"Invalid status. Allowed: {', '.join(allowed_statuses)}"]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        application.status = new_status

        if new_status in [
            LoanApplication.STATUS_APPROVED,
            LoanApplication.STATUS_REJECTED,
            LoanApplication.STATUS_COMPLETED,
            LoanApplication.STATUS_UNDER_REVIEW,
            LoanApplication.STATUS_PENDING_DOCUMENTS,
            LoanApplication.STATUS_KYC_REQUIRED,
        ]:
            application.current_step = 6

        application.save(update_fields=["status", "current_step", "updated_at"])

        if note_text:
            AdminApplicationNote.objects.create(
                application=application,
                created_by=request.user,
                note=note_text,
            )

        calculated_data = _application_calculated_data(application)

        return build_response(
            request,
            success=True,
            message="Application status updated successfully",
            data={
                "id": application.id,
                "applicationNumber": application.application_number,
                "status": application.status,
                "statusLabel": _get_status_label(application.status),
                "header": _build_header(application, calculated_data),
            },
            status_code=status.HTTP_200_OK,
        )


class AdminApplicationNotesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        application = _get_application(pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        notes = application.admin_notes.all()

        data = {
            "id": application.id,
            "applicationNumber": application.application_number,
            "notes": [_build_note_item(note) for note in notes],
            "existingNote": notes.first().note if notes.exists() else "",
        }

        return build_response(
            request,
            success=True,
            message="Admin notes fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )

    def post(self, request, pk):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        application = _get_application(pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        note_text = request.data.get("note", "").strip()

        if not note_text:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "note": ["This field is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        note = AdminApplicationNote.objects.create(
            application=application,
            created_by=request.user,
            note=note_text,
        )

        return build_response(
            request,
            success=True,
            message="Admin note added successfully",
            data={
                "note": _build_note_item(note),
                "notes": [_build_note_item(item) for item in application.admin_notes.all()],
            },
            status_code=status.HTTP_201_CREATED,
        )


class AdminApplicationTimelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        application = _get_application(pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        calculated_data = _application_calculated_data(application)

        data = {
            "id": application.id,
            "applicationNumber": application.application_number,
            "header": _build_header(application, calculated_data),
            "timeline": _build_timeline(application),
        }

        return build_response(
            request,
            success=True,
            message="Admin application timeline fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )
    

def _get_user_created_at(user):
    return getattr(user, "created_at", None) or getattr(user, "date_joined", None)


def _format_joined_month_year(value):
    if not value:
        return ""
    return value.strftime("%b %Y")


def _format_member_since(value):
    if not value:
        return ""
    return value.strftime("%b %d, %Y")


def _get_admin_user_role(user):
    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        return "admin"
    return getattr(user, "role", "customer") or "customer"


def _get_admin_user_role_label(user):
    role = _get_admin_user_role(user)
    mapping = {
        "admin": "admin",
        "customer": "customer",
        "joint_customer": "joint customer",
    }
    return mapping.get(role, role.replace("_", " "))


def _get_user_status(user):
    return "active" if getattr(user, "is_active", False) else "suspended"


def _get_latest_user_application(user):
    return (
        LoanApplication.objects
        .filter(user=user)
        .select_related("loan_type")
        .order_by("-created_at")
        .first()
    )


def _employment_display(value):
    mapping = {
        LoanApplication.EMPLOYMENT_EMPLOYED: "Full Time",
        LoanApplication.EMPLOYMENT_SELF_EMPLOYED: "Self-employed",
        LoanApplication.EMPLOYMENT_OTHER: "Other",
    }
    return mapping.get(value, value or None)


def _build_admin_user_card(user):
    applications_count = getattr(user, "applications_count", None)
    if applications_count is None:
        applications_count = LoanApplication.objects.filter(user=user).count()

    latest_application = _get_latest_user_application(user)

    
    credit_score = getattr(user, "credit_score", None)

    return {
        "id": user.id,
        "fullName": _get_user_full_name(user),
        "email": _get_user_email(user),
        "phone": _get_user_phone(user),
        "initials": _get_user_initials(user),

        "role": _get_admin_user_role(user),
        "roleLabel": _get_admin_user_role_label(user),

        "status": _get_user_status(user),
        "statusLabel": "active" if getattr(user, "is_active", False) else "suspended",

        "applicationsCount": applications_count,

        "creditScore": credit_score,
        "creditScoreDisplay": credit_score if credit_score is not None else "—",

        "annualIncome": _money(latest_application.annual_income) if latest_application else None,
        "annualIncomeDisplay": _money_display(latest_application.annual_income) if latest_application else "—",

        "employment": latest_application.employment_type if latest_application else None,
        "employmentDisplay": _employment_display(latest_application.employment_type) if latest_application else "—",

        "joined": _format_joined_month_year(_get_user_created_at(user)),
        "memberSince": _format_member_since(_get_user_created_at(user)),
        "createdAt": _get_user_created_at(user),

        "actions": {
            "canView": True,
            "canSuspend": bool(getattr(user, "is_active", False)),
            "canActivate": not bool(getattr(user, "is_active", False)),
            "detailApi": f"/api/admin/users/{user.id}/",
            "activityApi": f"/api/admin/users/{user.id}/activity/",
        },
    }


def _build_admin_user_detail(user):
    latest_application = _get_latest_user_application(user)
    card = _build_admin_user_card(user)

    return {
        **card,

        "drawer": {
            "title": _get_user_full_name(user),
            "subtitle": _get_user_email(user),
        },

        "stats": {
            "applications": card["applicationsCount"],
            "creditScore": card["creditScore"],
            "creditScoreDisplay": card["creditScoreDisplay"],
            "annualIncome": card["annualIncome"],
            "annualIncomeDisplay": card["annualIncomeDisplay"],
            "memberSince": card["memberSince"],
        },

        "profile": {
            "phone": _get_user_phone(user),
            "employer": getattr(user, "employer", None) or "—",
            "address": getattr(user, "address", None) or "—",
            "employment": latest_application.employment_type if latest_application else None,
            "employmentDisplay": _employment_display(latest_application.employment_type) if latest_application else "—",
        },

        "latestApplication": {
            "id": latest_application.id,
            "applicationNumber": latest_application.application_number,
            "loanType": latest_application.loan_type.name if latest_application.loan_type else None,
            "amount": _money(latest_application.loan_amount),
            "amountDisplay": _money_display(latest_application.loan_amount),
            "status": latest_application.status,
            "statusLabel": _get_status_label(latest_application.status),
        } if latest_application else None,
    }


def _build_user_activity_item(key, title, description, actor, activity_type, date):
    return {
        "key": key,
        "title": title,
        "description": description,
        "actor": actor,
        "type": activity_type,
        "date": date,
    }


class AdminUsersListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        User = get_user_model()

        search = request.query_params.get("search", "").strip()
        role_filter = request.query_params.get("role", "").strip().lower()
        status_filter = request.query_params.get("status", "").strip().lower()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 8)

        sort_by = request.query_params.get("sort_by", "joined").strip().lower()
        order = request.query_params.get("order", "desc").strip().lower()

        queryset = User.objects.annotate(
            applications_count=Count("loan_applications", distinct=True)
        )

        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search) |
                Q(email_address__icontains=search) |
                Q(phone_number__icontains=search)
            )

        if role_filter == "admin":
            queryset = queryset.filter(
                Q(role="admin") | Q(is_staff=True) | Q(is_superuser=True)
            )
        elif role_filter == "customer":
            queryset = queryset.filter(
                role="customer",
                is_staff=False,
                is_superuser=False,
            )

        if status_filter == "active":
            queryset = queryset.filter(is_active=True)
        elif status_filter in ["suspended", "inactive", "disabled"]:
            queryset = queryset.filter(is_active=False)

        sort_map = {
            "name": "full_name",
            "joined": "created_at",
            "created_at": "created_at",
            "applications": "applications_count",
            "status": "is_active",
        }

        sort_field = sort_map.get(sort_by, "created_at")

        if order == "desc":
            sort_field = f"-{sort_field}"

        queryset = queryset.order_by(sort_field)

        total = queryset.count()
        start = (page - 1) * limit
        end = start + limit
        users = queryset[start:end]

        total_users = User.objects.count()
        total_customers = User.objects.filter(
            role="customer",
            is_staff=False,
            is_superuser=False,
        ).count()
        total_admins = User.objects.filter(
            Q(role="admin") | Q(is_staff=True) | Q(is_superuser=True)
        ).distinct().count()
        active_users = User.objects.filter(is_active=True).count()
        suspended_users = User.objects.filter(is_active=False).count()

        summary_cards = [
            {
                "key": "totalUsers",
                "title": "Total Users",
                "value": total_users,
                "subtitle": "users in the system",
            },
            {
                "key": "customers",
                "title": "Customers",
                "value": total_customers,
                "subtitle": "customer accounts",
            },
            {
                "key": "administrators",
                "title": "Administrators",
                "value": total_admins,
                "subtitle": "admin accounts",
            },
        ]

        meta = _build_meta(
            page=page,
            limit=limit,
            total=total,
            filters={
                "search": search,
                "role": role_filter,
                "status": status_filter,
            },
            sorting={
                "sort_by": sort_by,
                "order": order,
            },
            summary={
                "totalUsers": total_users,
                "customers": total_customers,
                "administrators": total_admins,
                "activeUsers": active_users,
                "suspendedUsers": suspended_users,
            },
        )

        return build_response(
            request,
            success=True,
            message="Admin users fetched successfully",
            meta=meta,
            data={
                "summaryCards": summary_cards,
                "users": [_build_admin_user_card(user) for user in users],
            },
            status_code=status.HTTP_200_OK,
        )


class AdminUserDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        User = get_user_model()
        user_obj = User.objects.filter(id=user_id).first()

        if not user_obj:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return build_response(
            request,
            success=True,
            message="Admin user detail fetched successfully",
            data=_build_admin_user_detail(user_obj),
            status_code=status.HTTP_200_OK,
        )


class AdminUserSuspendView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        User = get_user_model()
        user_obj = User.objects.filter(id=user_id).first()

        if not user_obj:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if user_obj.id == request.user.id:
            return build_response(
                request,
                success=False,
                message="You cannot suspend your own account",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        user_obj.is_active = False

        if hasattr(user_obj, "updated_at"):
            user_obj.save(update_fields=["is_active", "updated_at"])
        else:
            user_obj.save(update_fields=["is_active"])

        return build_response(
            request,
            success=True,
            message="User suspended successfully",
            data=_build_admin_user_detail(user_obj),
            status_code=status.HTTP_200_OK,
        )


class AdminUserActivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        User = get_user_model()
        user_obj = User.objects.filter(id=user_id).first()

        if not user_obj:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        user_obj.is_active = True

        if hasattr(user_obj, "updated_at"):
            user_obj.save(update_fields=["is_active", "updated_at"])
        else:
            user_obj.save(update_fields=["is_active"])

        return build_response(
            request,
            success=True,
            message="User activated successfully",
            data=_build_admin_user_detail(user_obj),
            status_code=status.HTTP_200_OK,
        )


class AdminUserActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        User = get_user_model()
        user_obj = User.objects.filter(id=user_id).first()

        if not user_obj:
            return build_response(
                request,
                success=False,
                message="User not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        activities = []
        created_at = _get_user_created_at(user_obj)

        if created_at:
            activities.append(_build_user_activity_item(
                key="account_created",
                title="Account created",
                description=f"{_get_user_full_name(user_obj)} joined LoanSphere.",
                actor=_get_user_full_name(user_obj),
                activity_type="account",
                date=created_at,
            ))

        applications = LoanApplication.objects.filter(
            user=user_obj,
        ).select_related(
            "loan_type",
        ).prefetch_related(
            "documents",
            "admin_notes",
        )

        for application in applications:
            activities.append(_build_user_activity_item(
                key=f"application_created_{application.id}",
                title="Application started",
                description=f"{application.application_number} - {application.loan_type.name if application.loan_type else 'Loan'}",
                actor=_get_user_full_name(user_obj),
                activity_type="application",
                date=application.created_at,
            ))

            if application.submitted_at:
                activities.append(_build_user_activity_item(
                    key=f"application_submitted_{application.id}",
                    title="Application submitted",
                    description=f"{application.application_number} was submitted for review.",
                    actor=_get_user_full_name(user_obj),
                    activity_type="submitted",
                    date=application.submitted_at,
                ))

            for document in application.documents.all():
                activities.append(_build_user_activity_item(
                    key=f"document_uploaded_{document.id}",
                    title="Document uploaded",
                    description=f"{document.get_document_type_display()} - {document.original_file_name or 'Uploaded file'}",
                    actor=_get_user_full_name(user_obj),
                    activity_type="document",
                    date=document.uploaded_at,
                ))

            for note in application.admin_notes.all():
                activities.append(_build_user_activity_item(
                    key=f"admin_note_{note.id}",
                    title="Admin note added",
                    description=note.note,
                    actor=_get_user_full_name(note.created_by) if note.created_by else "Admin",
                    activity_type="note",
                    date=note.created_at,
                ))

        activities = sorted(
            activities,
            key=lambda item: item["date"] or timezone.now(),
            reverse=True,
        )

        return build_response(
            request,
            success=True,
            message="Admin user activity fetched successfully",
            data={
                "user": _build_admin_user_card(user_obj),
                "activities": activities,
            },
            status_code=status.HTTP_200_OK,
        )


def _decimal_or_zero(value):
    try:
        if value is None:
            return Decimal("0")
        return Decimal(value)
    except Exception:
        return Decimal("0")


def _compact_money_display(value):
    amount = _decimal_or_zero(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)

    if amount >= Decimal("1000000000"):
        return f"{sign}${amount / Decimal('1000000000'):.1f}B"

    if amount >= Decimal("1000000"):
        return f"{sign}${amount / Decimal('1000000'):.1f}M"

    if amount >= Decimal("1000"):
        return f"{sign}${amount / Decimal('1000'):.1f}K"

    return f"{sign}${amount:,.0f}"


def _percent_display(value):
    try:
        value = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        value = Decimal("0")

    if value == value.to_integral_value():
        return f"{int(value)}%"

    return f"{value}%"


def _percentage_change_display(current, previous):
    current = _decimal_or_zero(current)
    previous = _decimal_or_zero(previous)

    if previous == 0:
        if current == 0:
            return "0%"
        return "+100%"

    change = ((current - previous) / previous) * Decimal("100")
    change = change.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    sign = "+" if change > 0 else ""
    return f"{sign}{change}%"


def _count_change_display(current, previous):
    try:
        diff = int(current or 0) - int(previous or 0)
    except Exception:
        diff = 0

    if diff > 0:
        return f"+{diff}"

    return str(diff)


def _money_change_display(current, previous):
    diff = _decimal_or_zero(current) - _decimal_or_zero(previous)
    sign = "+" if diff > 0 else ""
    return f"{sign}{_compact_money_display(diff)}"


def _add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month, day=1)


def _month_label(value):
    return value.strftime("%b")


def _dashboard_approved_statuses():
    return [
        LoanApplication.STATUS_APPROVED,
        LoanApplication.STATUS_COMPLETED,
    ]


def _dashboard_pending_review_statuses():
    return [
        LoanApplication.STATUS_SUBMITTED,
        LoanApplication.STATUS_UNDER_REVIEW,
    ]


def _dashboard_pending_statuses():
    return [
        LoanApplication.STATUS_SUBMITTED,
        LoanApplication.STATUS_UNDER_REVIEW,
        LoanApplication.STATUS_PENDING_DOCUMENTS,
        LoanApplication.STATUS_KYC_REQUIRED,
        LoanApplication.STATUS_DRAFT,
    ]


def _sum_loan_amount(queryset):
    return queryset.aggregate(total=Sum("loan_amount")).get("total") or Decimal("0")


def _short_loan_type_name(name):
    if not name:
        return "Unknown"

    value = str(name).strip()

    if "consolidation" in value.lower():
        return "Debt Consol."

    if value.lower().endswith(" loan"):
        return value[:-5]

    return value


def _status_dashboard_item(label, status_key, count, total, badge_type):
    total = int(total or 0)
    count = int(count or 0)
    percent = int(round((count / total) * 100)) if total else 0

    return {
        "key": status_key,
        "status": status_key,
        "label": label,
        "count": count,
        "percent": percent,
        "percentDisplay": _percent_display(percent),
        "badgeType": badge_type,
    }


def _recent_dashboard_application(application):
    calculated_data = _application_calculated_data(application)

    return {
        "id": application.id,
        "applicationNumber": application.application_number,
        "customer": _customer_dict(application.user),
        "customerName": _get_user_full_name(application.user),
        "loanType": {
            "id": application.loan_type.id if application.loan_type else None,
            "name": application.loan_type.name if application.loan_type else None,
            "shortName": _short_loan_type_name(application.loan_type.name if application.loan_type else None),
        },
        "type": _short_loan_type_name(application.loan_type.name if application.loan_type else None),
        "amount": _money(application.loan_amount),
        "amountDisplay": _money_display(application.loan_amount),
        "status": application.status,
        "statusLabel": _get_status_label(application.status),
        "statusBadgeType": _get_status_badge_type(application.status),
        "dtiRatio": calculated_data.get("dtiRatio"),
        "dtiRatioDisplay": calculated_data.get("dtiRatioDisplay"),
        "date": application.created_at,
        "dateDisplay": application.created_at.strftime("%b %d, %Y") if application.created_at else "",
        "detailApi": f"/api/admin/applications/{application.id}/",
    }


class AdminDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month_start = _add_months(current_month_start, 1)
        previous_month_start = _add_months(current_month_start, -1)

        all_qs = _application_queryset()
        total_applications = all_qs.count()

        pending_review_qs = all_qs.filter(status__in=_dashboard_pending_review_statuses())
        approved_qs = all_qs.filter(status__in=_dashboard_approved_statuses())
        rejected_qs = all_qs.filter(status=LoanApplication.STATUS_REJECTED)
        pending_all_qs = all_qs.filter(status__in=_dashboard_pending_statuses())

        pending_review_count = pending_review_qs.count()
        approved_count = approved_qs.count()
        rejected_count = rejected_qs.count()
        pending_all_count = pending_all_qs.count()

        approved_this_month = approved_qs.filter(
            updated_at__gte=current_month_start,
            updated_at__lt=next_month_start,
        ).count()

        approved_previous_month = approved_qs.filter(
            updated_at__gte=previous_month_start,
            updated_at__lt=current_month_start,
        ).count()

        total_portfolio = _sum_loan_amount(approved_qs)

        current_month_applications = all_qs.filter(
            created_at__gte=current_month_start,
            created_at__lt=next_month_start,
        ).count()

        previous_month_applications = all_qs.filter(
            created_at__gte=previous_month_start,
            created_at__lt=current_month_start,
        ).count()

        current_month_pending_review = pending_review_qs.filter(
            created_at__gte=current_month_start,
            created_at__lt=next_month_start,
        ).count()

        previous_month_pending_review = pending_review_qs.filter(
            created_at__gte=previous_month_start,
            created_at__lt=current_month_start,
        ).count()

        current_month_portfolio = _sum_loan_amount(
            approved_qs.filter(
                updated_at__gte=current_month_start,
                updated_at__lt=next_month_start,
            )
        )

        previous_month_portfolio = _sum_loan_amount(
            approved_qs.filter(
                updated_at__gte=previous_month_start,
                updated_at__lt=current_month_start,
            )
        )

        summary_cards = [
            {
                "key": "totalApplications",
                "title": "Total Applications",
                "value": total_applications,
                "valueDisplay": str(total_applications),
                "change": _percentage_change_display(
                    current_month_applications,
                    previous_month_applications,
                ),
                "changeType": "positive" if current_month_applications >= previous_month_applications else "negative",
            },
            {
                "key": "pendingReview",
                "title": "Pending Review",
                "value": pending_review_count,
                "valueDisplay": str(pending_review_count),
                "change": _count_change_display(
                    current_month_pending_review,
                    previous_month_pending_review,
                ),
                "changeType": "positive" if current_month_pending_review >= previous_month_pending_review else "negative",
            },
            {
                "key": "approvedThisMonth",
                "title": "Approved This Month",
                "value": approved_this_month,
                "valueDisplay": str(approved_this_month),
                "change": _percentage_change_display(
                    approved_this_month,
                    approved_previous_month,
                ),
                "changeType": "positive" if approved_this_month >= approved_previous_month else "negative",
            },
            {
                "key": "totalPortfolio",
                "title": "Total Portfolio",
                "value": _money(total_portfolio),
                "valueDisplay": _compact_money_display(total_portfolio),
                "fullValueDisplay": _money_display(total_portfolio),
                "change": _money_change_display(
                    current_month_portfolio,
                    previous_month_portfolio,
                ),
                "changeType": "positive" if current_month_portfolio >= previous_month_portfolio else "negative",
            },
        ]

        monthly_disbursements = []
        first_chart_month = _add_months(current_month_start, -5)

        for index in range(6):
            month_start = _add_months(first_chart_month, index)
            month_end = _add_months(month_start, 1)

            amount = _sum_loan_amount(
                approved_qs.filter(
                    created_at__gte=month_start,
                    created_at__lt=month_end,
                )
            )

            monthly_disbursements.append({
                "key": month_start.strftime("%Y-%m"),
                "month": _month_label(month_start),
                "label": _month_label(month_start),
                "amount": _money(amount),
                "amountDisplay": _compact_money_display(amount),
                "fullAmountDisplay": _money_display(amount),
            })

        loan_type_rows = (
            all_qs.values("loan_type_id", "loan_type__name")
            .annotate(
                count=Count("id"),
                amount=Sum("loan_amount"),
            )
            .order_by("-count")
        )

        loan_type_distribution = []

        for row in loan_type_rows:
            count = int(row.get("count") or 0)
            percent = int(round((count / total_applications) * 100)) if total_applications else 0
            name = row.get("loan_type__name") or "Unknown"

            loan_type_distribution.append({
                "id": row.get("loan_type_id"),
                "name": name,
                "shortName": _short_loan_type_name(name),
                "count": count,
                "value": percent,
                "percent": percent,
                "percentDisplay": _percent_display(percent),
                "amount": _money(row.get("amount") or 0),
                "amountDisplay": _money_display(row.get("amount") or 0),
            })

        approved_status_count = approved_count

        under_review_count = all_qs.filter(
            status__in=[
                LoanApplication.STATUS_SUBMITTED,
                LoanApplication.STATUS_UNDER_REVIEW,
            ]
        ).count()

        pending_docs_count = all_qs.filter(
            status=LoanApplication.STATUS_PENDING_DOCUMENTS,
        ).count()

        rejected_status_count = rejected_count

        status_overview = [
            _status_dashboard_item(
                "Approved",
                "approved",
                approved_status_count,
                total_applications,
                "green",
            ),
            _status_dashboard_item(
                "Under Review",
                "under_review",
                under_review_count,
                total_applications,
                "yellow",
            ),
            _status_dashboard_item(
                "Pending Docs",
                "pending_documents",
                pending_docs_count,
                total_applications,
                "orange",
            ),
            _status_dashboard_item(
                "Rejected",
                "rejected",
                rejected_status_count,
                total_applications,
                "red",
            ),
        ]

        approval_rate = int(round((approved_count / total_applications) * 100)) if total_applications else 0
        approved_percent = int(round((approved_count / total_applications) * 100)) if total_applications else 0
        rejected_percent = int(round((rejected_count / total_applications) * 100)) if total_applications else 0
        pending_percent = int(round((pending_all_count / total_applications) * 100)) if total_applications else 0

        previous_month_total = all_qs.filter(
            created_at__gte=previous_month_start,
            created_at__lt=current_month_start,
        ).count()

        previous_month_approved_total = approved_qs.filter(
            updated_at__gte=previous_month_start,
            updated_at__lt=current_month_start,
        ).count()

        previous_month_approval_rate = (
            int(round((previous_month_approved_total / previous_month_total) * 100))
            if previous_month_total
            else 0
        )

        quick_actions = [
            {
                "key": "reviewPendingApplications",
                "title": "Review Pending Applications",
                "description": "Open applications waiting for admin review",
                "url": "/api/admin/applications/?status=under_review",
            },
            {
                "key": "viewAiInsights",
                "title": "View AI Insights",
                "description": "Review risk scoring and portfolio intelligence",
                "url": "/api/admin/ai-insights/",
            },
            {
                "key": "manageUsers",
                "title": "Manage Users",
                "description": "Open customer and admin user management",
                "url": "/api/admin/users/",
            },
            {
                "key": "customerMessages",
                "title": "Customer Messages",
                "description": "Open customer conversations",
                "url": "/api/admin/messages/",
            },
        ]

        recent_applications = [
            _recent_dashboard_application(application)
            for application in all_qs.order_by("-created_at")[:8]
        ]

        data = {
            "summaryCards": summary_cards,

            "monthlyDisbursements": {
                "title": "Monthly Disbursements",
                "subtitle": "Last 6 months",
                "source": "Approved loan applications",
                "items": monthly_disbursements,
            },

            "loanTypeDistribution": {
                "title": "Loan Type Distribution",
                "subtitle": "Portfolio breakdown",
                "items": loan_type_distribution,
            },

            "statusOverview": {
                "title": "Status Overview",
                "items": status_overview,
            },

            "quickActions": quick_actions,

            "approvalRate": {
                "title": "Approval Rate",
                "rate": approval_rate,
                "rateDisplay": _percent_display(approval_rate),
                "subtitle": f"This month vs {previous_month_approval_rate}% last month",
                "previousMonthRate": previous_month_approval_rate,
                "approved": approved_percent,
                "approvedDisplay": _percent_display(approved_percent),
                "rejected": rejected_percent,
                "rejectedDisplay": _percent_display(rejected_percent),
                "pending": pending_percent,
                "pendingDisplay": _percent_display(pending_percent),
            },

            "recentApplications": {
                "title": "Recent Applications",
                "viewAllApi": "/api/admin/applications/",
                "items": recent_applications,
            },
        }

        meta = {
            "generatedAt": now,
            "filters": {},
            "summary": {
                "totalApplications": total_applications,
                "pendingReview": pending_review_count,
                "approvedThisMonth": approved_this_month,
                "totalPortfolio": _money(total_portfolio),
            },
        }

        return build_response(
            request,
            success=True,
            message="Admin dashboard fetched successfully",
            meta=meta,
            data=data,
            status_code=status.HTTP_200_OK,
        )



def _ai_recommendation_key(score):
    try:
        score = int(score or 0)
    except Exception:
        score = 0

    if score >= 70:
        return "approve"

    if score >= 45:
        return "review"

    return "reject"


def _ai_recommendation_label(score):
    key = _ai_recommendation_key(score)

    mapping = {
        "approve": "Approve",
        "review": "Review",
        "reject": "Reject",
    }

    return mapping.get(key, "Review")


def _ai_recommendation_badge_type(score):
    key = _ai_recommendation_key(score)

    mapping = {
        "approve": "green",
        "review": "yellow",
        "reject": "red",
    }

    return mapping.get(key, "yellow")


def _ai_percent_number(count, total):
    try:
        count = int(count or 0)
        total = int(total or 0)
    except Exception:
        return 0

    if total <= 0:
        return 0

    return int(round((count / total) * 100))


def _ai_money_short(value):
    amount = _decimal_or_zero(value)

    if amount >= Decimal("1000000"):
        return f"${amount / Decimal('1000000'):.1f}M"

    if amount >= Decimal("1000"):
        return f"${amount / Decimal('1000'):.1f}K"

    return f"${amount:,.0f}"


def _ai_employment_label(value):
    mapping = {
        LoanApplication.EMPLOYMENT_EMPLOYED: "Full-time",
        LoanApplication.EMPLOYMENT_SELF_EMPLOYED: "Self-employed",
        LoanApplication.EMPLOYMENT_OTHER: "Other",
        "part_time": "Part-time",
        "part-time": "Part-time",
        "contract": "Contract",
    }

    return mapping.get(value, "Unknown")


def _ai_report_summary(application, score, calculated_data=None):
    calculated_data = calculated_data or _application_calculated_data(application)

    customer_name = _get_user_full_name(application.user)
    amount = _money_display(application.loan_amount) or "this amount"
    loan_type = application.loan_type.name if application.loan_type else "loan"

    dti_text = calculated_data.get("dtiRatioDisplay")
    employment = _ai_employment_label(application.employment_type)

    key = _ai_recommendation_key(score)

    if key == "approve":
        return (
            f"{customer_name} presents a low-risk profile for this {amount} {loan_type}. "
            f"Stable employment and DTI {dti_text or 'information'} support an approval recommendation."
        )

    if key == "review":
        return (
            f"{customer_name} requires manual review for this {amount} {loan_type}. "
            f"The profile has moderate risk indicators and employment status is {employment}."
        )

    return (
        f"{customer_name} presents higher risk for this {amount} {loan_type}. "
        f"Credit history, DTI, or affordability indicators require careful review before approval."
    )


def _ai_build_report_item(application):
    calculated_data = _application_calculated_data(application)
    score = _risk_score(application, calculated_data)

    return {
        "id": application.id,
        "application": application.application_number,
        "applicationNumber": application.application_number,
        "customer": _customer_dict(application.user),
        "customerName": _get_user_full_name(application.user),

        "loanType": {
            "id": application.loan_type.id if application.loan_type else None,
            "name": application.loan_type.name if application.loan_type else None,
            "shortName": _short_loan_type_name(application.loan_type.name if application.loan_type else None),
        },

        "riskScore": score,
        "riskScoreDisplay": f"{score}/100",

        "recommendation": _ai_recommendation_key(score),
        "recommendationLabel": _ai_recommendation_label(score),
        "recommendationBadgeType": _ai_recommendation_badge_type(score),

        "summary": _ai_report_summary(application, score, calculated_data),

        "dtiRatio": calculated_data.get("dtiRatio"),
        "dtiRatioDisplay": calculated_data.get("dtiRatioDisplay"),

        "amount": _money(application.loan_amount),
        "amountDisplay": _money_display(application.loan_amount),

        "date": application.updated_at or application.created_at,
        "dateDisplay": (application.updated_at or application.created_at).strftime("%b %d, %Y") if (application.updated_at or application.created_at) else "",

        "detailApi": f"/api/admin/applications/{application.id}/",
    }


class AdminAIInsightsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_admin_user(request.user):
            return _admin_required_response(request)

        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        all_qs = _application_queryset().order_by("-updated_at")
        total_applications = all_qs.count()

        scores = []
        approve_count = 0
        review_count = 0
        reject_count = 0

        application_score_map = {}

        for application in all_qs:
            calculated_data = _application_calculated_data(application)
            score = _risk_score(application, calculated_data)
            key = _ai_recommendation_key(score)

            scores.append(score)
            application_score_map[str(application.id)] = score

            if key == "approve":
                approve_count += 1
            elif key == "review":
                review_count += 1
            else:
                reject_count += 1

        avg_risk_score = int(round(sum(scores) / len(scores))) if scores else 0

        approve_percent = _ai_percent_number(approve_count, total_applications)
        review_percent = _ai_percent_number(review_count, total_applications)
        reject_percent = _ai_percent_number(reject_count, total_applications)

        summary_cards = [
            {
                "key": "avgRiskScore",
                "title": "Avg Risk Score",
                "value": avg_risk_score,
                "valueDisplay": f"{avg_risk_score}/100",
                "subtitle": "Avg Risk Score",
            },
            {
                "key": "aiApprovals",
                "title": "AI Approvals",
                "value": approve_percent,
                "valueDisplay": f"{approve_percent}%",
                "count": approve_count,
                "subtitle": "AI Approvals",
            },
            {
                "key": "aiReviews",
                "title": "AI Reviews",
                "value": review_percent,
                "valueDisplay": f"{review_percent}%",
                "count": review_count,
                "subtitle": "AI Reviews",
            },
            {
                "key": "aiRejections",
                "title": "AI Rejections",
                "value": reject_percent,
                "valueDisplay": f"{reject_percent}%",
                "count": reject_count,
                "subtitle": "AI Rejections",
            },
        ]

        risk_distribution_items = [
            {
                "key": "approve",
                "label": "Approve",
                "count": approve_count,
                "value": approve_count,
                "percent": approve_percent,
                "percentDisplay": f"{approve_percent}%",
                "badgeType": "green",
            },
            {
                "key": "review",
                "label": "Review",
                "count": review_count,
                "value": review_count,
                "percent": review_percent,
                "percentDisplay": f"{review_percent}%",
                "badgeType": "yellow",
            },
            {
                "key": "reject",
                "label": "Reject",
                "count": reject_count,
                "value": reject_count,
                "percent": reject_percent,
                "percentDisplay": f"{reject_percent}%",
                "badgeType": "red",
            },
        ]

        monthly_trends = []
        first_chart_month = _add_months(current_month_start, -5)

        for index in range(6):
            month_start = _add_months(first_chart_month, index)
            month_end = _add_months(month_start, 1)

            month_qs = all_qs.filter(
                created_at__gte=month_start,
                created_at__lt=month_end,
            )

            month_approve = 0
            month_review = 0
            month_reject = 0

            for application in month_qs:
                score = application_score_map.get(str(application.id))

                if score is None:
                    score = _risk_score(application)

                key = _ai_recommendation_key(score)

                if key == "approve":
                    month_approve += 1
                elif key == "review":
                    month_review += 1
                else:
                    month_reject += 1

            monthly_trends.append({
                "key": month_start.strftime("%Y-%m"),
                "month": _month_label(month_start),
                "label": _month_label(month_start),
                "approve": month_approve,
                "review": month_review,
                "reject": month_reject,
                "total": month_approve + month_review + month_reject,
            })

        loan_type_rows = (
            all_qs.values("loan_type_id", "loan_type__name")
            .annotate(
                count=Count("id"),
                amount=Sum("loan_amount"),
            )
            .order_by("-count")
        )

        loan_type_distribution_items = []

        for row in loan_type_rows:
            count = int(row.get("count") or 0)
            percent = _ai_percent_number(count, total_applications)
            name = row.get("loan_type__name") or "Unknown"

            loan_type_distribution_items.append({
                "id": row.get("loan_type_id"),
                "name": name,
                "shortName": _short_loan_type_name(name),
                "count": count,
                "value": percent,
                "percent": percent,
                "percentDisplay": f"{percent}%",
                "amount": _money(row.get("amount") or 0),
                "amountDisplay": _money_display(row.get("amount") or 0),
            })

        employment_raw_counts = {
            "employed": 0,
            "self_employed": 0,
            "part_time": 0,
            "contract": 0,
            "other": 0,
            "unknown": 0,
        }

        for application in all_qs:
            employment_value = application.employment_type or "unknown"

            if employment_value in employment_raw_counts:
                employment_raw_counts[employment_value] += 1
            else:
                employment_raw_counts["unknown"] += 1

        employment_distribution_items = [
            {
                "key": "employed",
                "label": "Full-time",
                "count": employment_raw_counts["employed"],
                "value": _ai_percent_number(employment_raw_counts["employed"], total_applications),
                "percent": _ai_percent_number(employment_raw_counts["employed"], total_applications),
                "percentDisplay": f"{_ai_percent_number(employment_raw_counts['employed'], total_applications)}%",
            },
            {
                "key": "self_employed",
                "label": "Self-employed",
                "count": employment_raw_counts["self_employed"],
                "value": _ai_percent_number(employment_raw_counts["self_employed"], total_applications),
                "percent": _ai_percent_number(employment_raw_counts["self_employed"], total_applications),
                "percentDisplay": f"{_ai_percent_number(employment_raw_counts['self_employed'], total_applications)}%",
            },
            {
                "key": "part_time",
                "label": "Part-time",
                "count": employment_raw_counts["part_time"],
                "value": _ai_percent_number(employment_raw_counts["part_time"], total_applications),
                "percent": _ai_percent_number(employment_raw_counts["part_time"], total_applications),
                "percentDisplay": f"{_ai_percent_number(employment_raw_counts['part_time'], total_applications)}%",
            },
            {
                "key": "contract",
                "label": "Contract",
                "count": employment_raw_counts["contract"],
                "value": _ai_percent_number(employment_raw_counts["contract"], total_applications),
                "percent": _ai_percent_number(employment_raw_counts["contract"], total_applications),
                "percentDisplay": f"{_ai_percent_number(employment_raw_counts['contract'], total_applications)}%",
            },
        ]

        if employment_raw_counts["other"] > 0:
            employment_distribution_items.append({
                "key": "other",
                "label": "Other",
                "count": employment_raw_counts["other"],
                "value": _ai_percent_number(employment_raw_counts["other"], total_applications),
                "percent": _ai_percent_number(employment_raw_counts["other"], total_applications),
                "percentDisplay": f"{_ai_percent_number(employment_raw_counts['other'], total_applications)}%",
            })

        if employment_raw_counts["unknown"] > 0:
            employment_distribution_items.append({
                "key": "unknown",
                "label": "Unknown",
                "count": employment_raw_counts["unknown"],
                "value": _ai_percent_number(employment_raw_counts["unknown"], total_applications),
                "percent": _ai_percent_number(employment_raw_counts["unknown"], total_applications),
                "percentDisplay": f"{_ai_percent_number(employment_raw_counts['unknown'], total_applications)}%",
            })

        recent_ai_reports = [
            _ai_build_report_item(application)
            for application in all_qs[:10]
        ]

        data = {
            "summaryCards": summary_cards,

            "riskScoreDistribution": {
                "title": "Risk Score Distribution",
                "items": risk_distribution_items,
            },

            "monthlyAssessmentTrends": {
                "title": "Monthly AI Assessment Trends",
                "subtitle": "Last 6 months",
                "items": monthly_trends,
            },

            "loanTypeDistribution": {
                "title": "Loan Type Distribution",
                "items": loan_type_distribution_items,
            },

            "employmentTypeDistribution": {
                "title": "Employment Type Distribution",
                "items": employment_distribution_items,
            },

            "recentAIReports": {
                "title": "Recent AI Reports",
                "items": recent_ai_reports,
            },
        }

        meta = {
            "generatedAt": now,
            "summary": {
                "totalApplications": total_applications,
                "avgRiskScore": avg_risk_score,
                "approveCount": approve_count,
                "reviewCount": review_count,
                "rejectCount": reject_count,
            },
            "note": "This AI Insights response is generated using rule-based risk scoring from existing loan application data.",
        }

        return build_response(
            request,
            success=True,
            message="Admin AI insights fetched successfully",
            meta=meta,
            data=data,
            status_code=status.HTTP_200_OK,
        )