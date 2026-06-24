import math

from django.db.models import Q
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from authentication.utils import build_response

from .models import LoanApplication
from .serializers import LoanApplicationSerializer, MyLoanListSerializer


def _to_int(value, default):
    try:
        value = int(value)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def build_list_meta(page, limit, total, filters=None, sorting=None, summary=None):
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


def paginate_queryset(queryset, page, limit):
    start = (page - 1) * limit
    end = start + limit
    return queryset[start:end]


class CustomerLoanApplicationListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        status_filter = request.query_params.get("status", "").strip()
        loan_type = request.query_params.get("loan_type", "").strip()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 10)

        sort_by = request.query_params.get("sort_by", "date")
        order = request.query_params.get("order", "desc").lower()

        queryset = LoanApplication.objects.select_related(
            "loan_type",
            "loan_type__template",
        ).filter(user=request.user)

        if search:
            queryset = queryset.filter(
                Q(application_number__icontains=search) |
                Q(loan_type__name__icontains=search)
            )

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if loan_type:
            queryset = queryset.filter(loan_type_id=loan_type)

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
        items = paginate_queryset(queryset, page, limit)

        serializer = MyLoanListSerializer(items, many=True)

        meta = build_list_meta(
            page=page,
            limit=limit,
            total=total,
            filters={
                "search": search,
                "status": status_filter,
                "loan_type": loan_type,
                "date_from": "",
                "date_to": "",
                "amount_min": "",
                "amount_max": "",
            },
            sorting={
                "sort_by": sort_by,
                "order": order,
            },
            summary={
                "total_applications": LoanApplication.objects.filter(user=request.user).count(),
                "draft_applications": LoanApplication.objects.filter(
                    user=request.user,
                    status=LoanApplication.STATUS_DRAFT,
                ).count(),
                "submitted_applications": LoanApplication.objects.filter(
                    user=request.user,
                    status=LoanApplication.STATUS_SUBMITTED,
                ).count(),
                "active_loans": LoanApplication.objects.filter(
                    user=request.user,
                ).exclude(status=LoanApplication.STATUS_DRAFT).count(),
                "in_review": LoanApplication.objects.filter(
                    user=request.user,
                    status__in=[
                        LoanApplication.STATUS_SUBMITTED,
                        LoanApplication.STATUS_UNDER_REVIEW,
                        LoanApplication.STATUS_PENDING_DOCUMENTS,
                        LoanApplication.STATUS_KYC_REQUIRED,
                    ],
                ).count(),
            },
        )

        return build_response(
            request,
            success=True,
            message="Loan applications fetched successfully",
            meta=meta,
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = LoanApplicationSerializer(data=request.data)

        if not serializer.is_valid():
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        application = serializer.save(
            user=request.user,
            status=LoanApplication.STATUS_DRAFT,
            current_step=1,
        )

        return build_response(
            request,
            success=True,
            message="Loan application draft created successfully",
            data=LoanApplicationSerializer(application).data,
            status_code=status.HTTP_201_CREATED,
        )


class CustomerLoanApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, pk):
        return LoanApplication.objects.select_related(
            "loan_type",
            "loan_type__template",
        ).filter(
            pk=pk,
            user=request.user,
        ).first()

    def get(self, request, pk):
        application = self.get_object(request, pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return build_response(
            request,
            success=True,
            message="Loan application detail fetched successfully",
            data=LoanApplicationSerializer(application).data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        application = self.get_object(request, pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if application.status != LoanApplication.STATUS_DRAFT:
            return build_response(
                request,
                success=False,
                message="Only draft applications can be edited",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        serializer = LoanApplicationSerializer(
            application,
            data=request.data,
            partial=True,
        )

        if not serializer.is_valid():
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        application = serializer.save()

        return build_response(
            request,
            success=True,
            message="Loan application updated successfully",
            data=LoanApplicationSerializer(application).data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        application = self.get_object(request, pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if application.status != LoanApplication.STATUS_DRAFT:
            return build_response(
                request,
                success=False,
                message="Only draft applications can be deleted",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        application.delete()

        return build_response(
            request,
            success=True,
            message="Loan application deleted successfully",
            data={},
            status_code=status.HTTP_200_OK,
        )


class CustomerLoanApplicationSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        application = LoanApplication.objects.select_related(
            "loan_type",
            "loan_type__template",
        ).filter(
            pk=pk,
            user=request.user,
        ).first()

        if not application:
            return build_response(
                request,
                success=False,
                message="Loan application not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if application.status != LoanApplication.STATUS_DRAFT:
            return build_response(
                request,
                success=False,
                message="Application already submitted",
                data=LoanApplicationSerializer(application).data,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        errors = {}

        if not application.loan_amount:
            errors["loanAmount"] = ["Loan amount is required before submit."]

        if not application.loan_term:
            errors["loanTerm"] = ["Loan term is required before submit."]

        if not application.employment_type:
            errors["employmentType"] = ["Employment type is required before submit."]

        if not application.annual_income:
            errors["annualIncome"] = ["Annual income is required before submit."]

        if errors:
            return build_response(
                request,
                success=False,
                message="Please complete required fields before submit",
                data=errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        application.status = LoanApplication.STATUS_SUBMITTED
        application.current_step = 6
        application.submitted_at = timezone.now()
        application.save(update_fields=["status", "current_step", "submitted_at", "updated_at"])

        data = LoanApplicationSerializer(application).data

        data["nextStep"] = "documents"
        data["successScreen"] = {
            "title": "Application Submitted!",
            "applicationNumber": application.application_number,
            "message": "We'll review your application and contact you shortly. You can track the status in My Loan.",
            "buttons": {
                "viewMyLoan": True,
                "callUsNow": True,
                "uploadDocuments": True,
                "inviteCoApplicant": True,
            },
        }

        return build_response(
            request,
            success=True,
            message="Loan application submitted successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )


class CustomerMyLoansView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        status_filter = request.query_params.get("status", "").strip()
        loan_type = request.query_params.get("loan_type", "").strip()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 10)

        sort_by = request.query_params.get("sort_by", "date")
        order = request.query_params.get("order", "desc").lower()

        queryset = LoanApplication.objects.select_related(
            "loan_type",
            "loan_type__template",
        ).filter(
            user=request.user,
        )

        if search:
            queryset = queryset.filter(
                Q(application_number__icontains=search) |
                Q(loan_type__name__icontains=search)
            )

        if status_filter:
            queryset = queryset.filter(status=status_filter)

        if loan_type:
            queryset = queryset.filter(loan_type_id=loan_type)

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
        items = paginate_queryset(queryset, page, limit)

        serializer = MyLoanListSerializer(items, many=True)

        meta = build_list_meta(
            page=page,
            limit=limit,
            total=total,
            filters={
                "search": search,
                "status": status_filter,
                "loan_type": loan_type,
                "date_from": "",
                "date_to": "",
                "amount_min": "",
                "amount_max": "",
            },
            sorting={
                "sort_by": sort_by,
                "order": order,
            },
            summary={
                "total_applications": LoanApplication.objects.filter(user=request.user).count(),
                "active_loans": LoanApplication.objects.filter(
                    user=request.user,
                ).exclude(status=LoanApplication.STATUS_DRAFT).count(),
                "in_review": LoanApplication.objects.filter(
                    user=request.user,
                    status__in=[
                        LoanApplication.STATUS_SUBMITTED,
                        LoanApplication.STATUS_UNDER_REVIEW,
                        LoanApplication.STATUS_PENDING_DOCUMENTS,
                        LoanApplication.STATUS_KYC_REQUIRED,
                    ],
                ).count(),
                "approved": LoanApplication.objects.filter(
                    user=request.user,
                    status=LoanApplication.STATUS_APPROVED,
                ).count(),
            },
        )

        return build_response(
            request,
            success=True,
            message="My loans fetched successfully",
            meta=meta,
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )
    

from decimal import Decimal, ROUND_HALF_UP


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


def _get_user_full_name(user):
    for field_name in ["full_name", "name", "username", "email", "email_address"]:
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


def _get_customer_my_loan_application(request, pk):
    return LoanApplication.objects.select_related(
        "loan_type",
        "loan_type__template",
        "user",
    ).filter(
        pk=pk,
        user=request.user,
    ).first()


class CustomerMyLoanDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        application = _get_customer_my_loan_application(request, pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="My loan not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = LoanApplicationSerializer(application)
        serialized_data = serializer.data

        loan_type_name = application.loan_type.name if application.loan_type else None
        template_name = None

        if application.loan_type and application.loan_type.template:
            template_name = application.loan_type.template.name

        estimated_rate = serialized_data.get("estimatedRate")
        estimated_monthly_payment = serialized_data.get("estimatedMonthlyPayment")
        dti_ratio = serialized_data.get("dtiRatio")
        dti_ratio_display = serialized_data.get("dtiRatioDisplay")
        documents_summary = serialized_data.get("documentsSummary")

        data = {
            "id": application.id,
            "applicationNumber": application.application_number,
            "status": application.status,
            "statusLabel": _get_status_label(application.status),
            "statusBadgeType": _get_status_badge_type(application.status),

            "header": {
                "title": loan_type_name,
                "applicationNumber": application.application_number,
                "status": application.status,
                "statusLabel": _get_status_label(application.status),
                "loanAmount": _money(application.loan_amount),
                "loanAmountDisplay": _money_display(application.loan_amount),
                "lender": template_name,
                "term": application.loan_term,
                "interestRate": estimated_rate,
                "monthlyPayment": estimated_monthly_payment,
                "monthlyPaymentDisplay": _money_display(estimated_monthly_payment),
                "progressPercent": application.progress_percent,
            },

            "tabs": {
                "overview": True,
                "documents": True,
                "timeline": True,
            },

            "overview": {
                "loanDetails": {
                    "loanType": loan_type_name,
                    "amount": _money(application.loan_amount),
                    "amountDisplay": _money_display(application.loan_amount),
                    "term": application.loan_term,
                    "interestRate": estimated_rate,
                    "monthlyPayment": estimated_monthly_payment,
                    "monthlyPaymentDisplay": _money_display(estimated_monthly_payment),
                    "propertyValue": _money(application.property_value),
                    "propertyValueDisplay": _money_display(application.property_value),
                    "mortgageBalance": _money(application.mortgage_balance),
                    "mortgageBalanceDisplay": _money_display(application.mortgage_balance),
                    "mortgagePayment": _money(application.mortgage_payment),
                    "mortgagePaymentDisplay": _money_display(application.mortgage_payment),
                    "mortgageLender": application.mortgage_lender,
                    "termRemaining": application.term_remaining,
                    "applied": application.created_at,
                    "lastUpdated": application.updated_at,
                },
                "financialSummary": {
                    "annualIncome": _money(application.annual_income),
                    "annualIncomeDisplay": _money_display(application.annual_income),
                    "employment": serialized_data.get("employmentDisplay"),
                    "dtiRatio": dti_ratio,
                    "dtiRatioDisplay": dti_ratio_display,
                },
                "aiRiskAssessment": {
                    "riskScore": 78 if application.status in ["approved", "under_review", "submitted"] else 0,
                    "recommendation": "Approve Recommended" if application.status != "rejected" else "Review Required",
                    "summary": f"{_get_user_full_name(application.user)} presents a loan profile for this {loan_type_name}. Uploaded documents and financial information are available for review.",
                    "factors": [
                        {
                            "label": "Credit Profile",
                            "description": "Credit and affordability information will be reviewed by the admin team.",
                            "type": "positive",
                        },
                        {
                            "label": "DTI Ratio",
                            "description": f"Debt-to-income ratio is {dti_ratio_display}." if dti_ratio_display else "DTI ratio will be calculated when enough financial data is available.",
                            "type": "positive" if dti_ratio and float(dti_ratio) <= 43 else "warning",
                        },
                        {
                            "label": "Documents",
                            "description": documents_summary.get("uploadedText") if documents_summary else "Documents not uploaded yet.",
                            "type": "positive" if documents_summary and documents_summary.get("isCompleted") else "warning",
                        },
                    ],
                },
                "adminNotes": {
                    "text": "No admin notes yet.",
                    "items": [],
                },
            },

            "documentsSummary": documents_summary,

            "actions": {
                "canUploadNewDocument": application.status in [
                    LoanApplication.STATUS_SUBMITTED,
                    LoanApplication.STATUS_UNDER_REVIEW,
                    LoanApplication.STATUS_PENDING_DOCUMENTS,
                    LoanApplication.STATUS_KYC_REQUIRED,
                    LoanApplication.STATUS_APPROVED,
                ],
                "canViewDocuments": True,
                "canViewTimeline": True,
            },

            "rawApplication": serialized_data,
        }

        return build_response(
            request,
            success=True,
            message="My loan detail fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )


class CustomerMyLoanDocumentsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        application = _get_customer_my_loan_application(request, pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="My loan not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        try:
            from loan_documents.views import build_documents_response
            documents_data = build_documents_response(application)
        except Exception:
            documents_data = {
                "application": {
                    "id": application.id,
                    "applicationNumber": application.application_number,
                    "loanType": {
                        "id": application.loan_type.id if application.loan_type else None,
                        "name": application.loan_type.name if application.loan_type else None,
                    },
                    "status": application.status,
                },
                "summary": {
                    "requiredCount": 5,
                    "uploadedCount": 0,
                    "remainingCount": 5,
                    "progressPercent": 0,
                    "uploadedText": "0/5 uploaded",
                    "statusText": "5 required remaining",
                    "isCompleted": False,
                },
                "categories": [],
            }

        data = {
            "id": application.id,
            "applicationNumber": application.application_number,
            "status": application.status,
            "statusLabel": _get_status_label(application.status),

            "header": {
                "title": application.loan_type.name if application.loan_type else None,
                "applicationNumber": application.application_number,
                "loanAmount": _money(application.loan_amount),
                "loanAmountDisplay": _money_display(application.loan_amount),
                "term": application.loan_term,
                "progressPercent": application.progress_percent,
            },

            "documents": documents_data,

            "actions": {
                "canUploadNewDocument": True,
                "uploadApi": f"/api/customer/loan-applications/{application.id}/documents/upload/",
            },
        }

        return build_response(
            request,
            success=True,
            message="My loan documents fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )


class CustomerMyLoanTimelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        application = _get_customer_my_loan_application(request, pk)

        if not application:
            return build_response(
                request,
                success=False,
                message="My loan not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

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

        try:
            documents = application.documents.all().order_by("uploaded_at")

            for document in documents:
                timeline.append({
                    "key": f"document_uploaded_{document.id}",
                    "title": f"{document.get_document_type_display()} uploaded",
                    "description": document.original_file_name or "Document uploaded",
                    "actor": _get_user_full_name(application.user),
                    "type": "document",
                    "status": "completed",
                    "date": document.uploaded_at,
                })

        except Exception:
            pass

        if application.status == LoanApplication.STATUS_UNDER_REVIEW:
            timeline.append({
                "key": "status_under_review",
                "title": "Status changed to under_review",
                "description": "Your application is now under review.",
                "actor": "System",
                "type": "status",
                "status": "current",
                "date": application.updated_at,
            })

        if application.status == LoanApplication.STATUS_PENDING_DOCUMENTS:
            timeline.append({
                "key": "additional_documents_requested",
                "title": "Additional documents requested",
                "description": "The admin team requested additional documents for your application.",
                "actor": "Admin",
                "type": "request",
                "status": "current",
                "date": application.updated_at,
            })

        if application.status == LoanApplication.STATUS_APPROVED:
            timeline.append({
                "key": "application_approved",
                "title": "Application approved",
                "description": "Your loan application has been approved.",
                "actor": "Admin",
                "type": "approved",
                "status": "completed",
                "date": application.updated_at,
            })

        if application.status == LoanApplication.STATUS_REJECTED:
            timeline.append({
                "key": "application_rejected",
                "title": "Application rejected",
                "description": "Your loan application has been rejected.",
                "actor": "Admin",
                "type": "rejected",
                "status": "completed",
                "date": application.updated_at,
            })

        timeline = sorted(timeline, key=lambda item: item["date"] or application.created_at)

        data = {
            "id": application.id,
            "applicationNumber": application.application_number,
            "status": application.status,
            "statusLabel": _get_status_label(application.status),

            "header": {
                "title": application.loan_type.name if application.loan_type else None,
                "applicationNumber": application.application_number,
                "loanAmount": _money(application.loan_amount),
                "loanAmountDisplay": _money_display(application.loan_amount),
                "term": application.loan_term,
                "progressPercent": application.progress_percent,
            },

            "timeline": timeline,
        }

        return build_response(
            request,
            success=True,
            message="My loan timeline fetched successfully",
            data=data,
            status_code=status.HTTP_200_OK,
        )


