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