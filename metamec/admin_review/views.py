import math
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Count
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




