import math
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from authentication.utils import build_response

from .models import LoanType, LoanTemplate, LoanTemplateSection
from .permissions import IsAdminUserRole
from .serializers import (
    CustomerLoanTypeSerializer,
    LoanTemplateCreateUpdateSerializer,
    LoanTemplateDetailSerializer,
    LoanTemplateDropdownSerializer,
    LoanTemplateListSerializer,
    LoanTemplateSectionSerializer,
    LoanTypeSerializer,
)


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


def normalize_section_orders(template):
    sections = list(template.sections.all().order_by("order", "created_at"))

    for index, section in enumerate(sections, start=1):
        if section.order != index:
            section.order = index
            section.save(update_fields=["order", "updated_at"])


class LoanManagementSummaryView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):
        total_loan_types = LoanType.objects.count()
        active_loan_types = LoanType.objects.filter(is_active=True).count()
        inactive_loan_types = LoanType.objects.filter(is_active=False).count()

        total_templates = LoanTemplate.objects.count()
        published_templates = LoanTemplate.objects.filter(status=LoanTemplate.STATUS_PUBLISHED).count()
        draft_templates = LoanTemplate.objects.filter(status=LoanTemplate.STATUS_DRAFT).count()

        total_sections = LoanTemplateSection.objects.count()

        avg_sections = Decimal("0.0")
        if total_templates:
            avg_sections = Decimal(total_sections) / Decimal(total_templates)

        return build_response(
            request,
            success=True,
            message="Loan management summary fetched successfully",
            data={
                "totalLoanTypes": total_loan_types,
                "activeLoanTypes": active_loan_types,
                "inactiveLoanTypes": inactive_loan_types,
                "totalTemplates": total_templates,
                "publishedTemplates": published_templates,
                "draftTemplates": draft_templates,
                "averageSectionsPerTemplate": float(round(avg_sections, 1)),
            },
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTypeListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        is_active = request.query_params.get("is_active", "").strip()
        template_id = request.query_params.get("template_id", "").strip()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 10)

        sort_by = request.query_params.get("sort_by", "name")
        order = request.query_params.get("order", "asc").lower()

        queryset = LoanType.objects.select_related("template").all()

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            )

        if is_active in ["true", "false"]:
            queryset = queryset.filter(is_active=(is_active == "true"))

        if template_id:
            queryset = queryset.filter(template_id=template_id)

        sort_map = {
            "name": "name",
            "date": "created_at",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "status": "is_active",
        }

        sort_field = sort_map.get(sort_by, "name")

        if order == "desc":
            sort_field = f"-{sort_field}"

        queryset = queryset.order_by(sort_field)

        total = queryset.count()
        items = paginate_queryset(queryset, page, limit)

        serializer = LoanTypeSerializer(items, many=True)

        meta = build_list_meta(
            page=page,
            limit=limit,
            total=total,
            filters={
                "search": search,
                "is_active": is_active,
                "template_id": template_id,
                "status": "",
                "date_from": "",
                "date_to": "",
            },
            sorting={
                "sort_by": sort_by,
                "order": order,
            },
            summary={
                "total_loan_types": LoanType.objects.count(),
                "active_loan_types": LoanType.objects.filter(is_active=True).count(),
                "inactive_loan_types": LoanType.objects.filter(is_active=False).count(),
            },
        )

        return build_response(
            request,
            success=True,
            message="Loan types fetched successfully",
            meta=meta,
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = LoanTypeSerializer(data=request.data)

        if not serializer.is_valid():
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        loan_type = serializer.save(created_by=request.user)

        return build_response(
            request,
            success=True,
            message="Loan type created successfully",
            data=LoanTypeSerializer(loan_type).data,
            status_code=status.HTTP_201_CREATED,
        )


class AdminLoanTypeDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self, pk):
        return LoanType.objects.select_related("template").filter(pk=pk).first()

    def get(self, request, pk):
        loan_type = self.get_object(pk)

        if not loan_type:
            return build_response(
                request,
                success=False,
                message="Loan type not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        return build_response(
            request,
            success=True,
            message="Loan type detail fetched successfully",
            data=LoanTypeSerializer(loan_type).data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        loan_type = self.get_object(pk)

        if not loan_type:
            return build_response(
                request,
                success=False,
                message="Loan type not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = LoanTypeSerializer(loan_type, data=request.data, partial=True)

        if not serializer.is_valid():
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        loan_type = serializer.save()

        return build_response(
            request,
            success=True,
            message="Loan type updated successfully",
            data=LoanTypeSerializer(loan_type).data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        loan_type = self.get_object(pk)

        if not loan_type:
            return build_response(
                request,
                success=False,
                message="Loan type not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        loan_type.delete()

        return build_response(
            request,
            success=True,
            message="Loan type deleted successfully",
            data={},
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTypeToggleStatusView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def patch(self, request, pk):
        loan_type = LoanType.objects.filter(pk=pk).first()

        if not loan_type:
            return build_response(
                request,
                success=False,
                message="Loan type not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if "isActive" not in request.data:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "isActive": ["This field is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        value = request.data.get("isActive")

        if isinstance(value, str):
            value = value.lower() == "true"

        loan_type.is_active = bool(value)
        loan_type.save(update_fields=["is_active", "updated_at"])

        return build_response(
            request,
            success=True,
            message="Loan type status updated successfully",
            data={
                "id": loan_type.id,
                "name": loan_type.name,
                "isActive": loan_type.is_active,
            },
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTemplateListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        status_filter = request.query_params.get("status", "").strip()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 10)

        sort_by = request.query_params.get("sort_by", "date")
        order = request.query_params.get("order", "desc").lower()

        queryset = LoanTemplate.objects.annotate(
            sections_count=Count("sections")
        )

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            )

        if status_filter in [
            LoanTemplate.STATUS_DRAFT,
            LoanTemplate.STATUS_PUBLISHED,
        ]:
            queryset = queryset.filter(status=status_filter)

        sort_map = {
            "name": "name",
            "date": "updated_at",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "status": "status",
            "sections": "sections_count",
        }

        sort_field = sort_map.get(sort_by, "updated_at")

        if order == "desc":
            sort_field = f"-{sort_field}"

        queryset = queryset.order_by(sort_field)

        total = queryset.count()
        items = paginate_queryset(queryset, page, limit)

        serializer = LoanTemplateListSerializer(items, many=True)

        meta = build_list_meta(
            page=page,
            limit=limit,
            total=total,
            filters={
                "search": search,
                "status": status_filter,
                "date_from": "",
                "date_to": "",
            },
            sorting={
                "sort_by": sort_by,
                "order": order,
            },
            summary={
                "total_templates": LoanTemplate.objects.count(),
                "published_templates": LoanTemplate.objects.filter(
                    status=LoanTemplate.STATUS_PUBLISHED
                ).count(),
                "draft_templates": LoanTemplate.objects.filter(
                    status=LoanTemplate.STATUS_DRAFT
                ).count(),
            },
        )

        return build_response(
            request,
            success=True,
            message="Loan templates fetched successfully",
            meta=meta,
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = LoanTemplateCreateUpdateSerializer(data=request.data)

        if not serializer.is_valid():
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        template = serializer.save(created_by=request.user)
        template.sections_count = template.sections.count()

        return build_response(
            request,
            success=True,
            message="Loan template created successfully",
            data=LoanTemplateListSerializer(template).data,
            status_code=status.HTTP_201_CREATED,
        )


class AdminLoanTemplateDropdownView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get(self, request):
        templates = LoanTemplate.objects.filter(
            status=LoanTemplate.STATUS_PUBLISHED
        ).order_by("name")

        return build_response(
            request,
            success=True,
            message="Published templates fetched successfully",
            data=LoanTemplateDropdownSerializer(templates, many=True).data,
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTemplateDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get_object(self, pk):
        return LoanTemplate.objects.prefetch_related("sections").filter(pk=pk).first()

    def get(self, request, pk):
        template = self.get_object(pk)

        if not template:
            return build_response(
                request,
                success=False,
                message="Loan template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        template.sections_count = template.sections.count()

        return build_response(
            request,
            success=True,
            message="Loan template detail fetched successfully",
            data=LoanTemplateDetailSerializer(template).data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        template = self.get_object(pk)

        if not template:
            return build_response(
                request,
                success=False,
                message="Loan template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = LoanTemplateCreateUpdateSerializer(
            template,
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

        template = serializer.save()
        template.sections_count = template.sections.count()

        return build_response(
            request,
            success=True,
            message="Loan template updated successfully",
            data=LoanTemplateDetailSerializer(template).data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        template = self.get_object(pk)

        if not template:
            return build_response(
                request,
                success=False,
                message="Loan template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if template.loan_types.exists():
            return build_response(
                request,
                success=False,
                message="This template is assigned to one or more loan types and cannot be deleted",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            template.delete()
        except ProtectedError:
            return build_response(
                request,
                success=False,
                message="This template is assigned to one or more loan types and cannot be deleted",
                data={},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        return build_response(
            request,
            success=True,
            message="Loan template deleted successfully",
            data={},
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTemplatePublishView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def post(self, request, pk):
        template = LoanTemplate.objects.prefetch_related("sections").filter(pk=pk).first()

        if not template:
            return build_response(
                request,
                success=False,
                message="Loan template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if not template.sections.exists():
            return build_response(
                request,
                success=False,
                message="Template must have at least one section before publishing",
                data={
                    "sections": ["At least one section is required"]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        template.status = LoanTemplate.STATUS_PUBLISHED
        template.save(update_fields=["status", "updated_at"])
        template.sections_count = template.sections.count()

        return build_response(
            request,
            success=True,
            message="Loan template published successfully",
            data=LoanTemplateListSerializer(template).data,
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTemplateMarkDraftView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def post(self, request, pk):
        template = LoanTemplate.objects.filter(pk=pk).first()

        if not template:
            return build_response(
                request,
                success=False,
                message="Loan template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        template.status = LoanTemplate.STATUS_DRAFT
        template.save(update_fields=["status", "updated_at"])
        template.sections_count = template.sections.count()

        return build_response(
            request,
            success=True,
            message="Loan template moved to draft successfully",
            data=LoanTemplateListSerializer(template).data,
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTemplateSectionCreateView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    @transaction.atomic
    def post(self, request, pk):
        template = LoanTemplate.objects.filter(pk=pk).first()

        if not template:
            return build_response(
                request,
                success=False,
                message="Loan template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = LoanTemplateSectionSerializer(data=request.data)

        if not serializer.is_valid():
            return build_response(
                request,
                success=False,
                message="Validation error",
                data=serializer.errors,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        next_order = template.sections.count() + 1

        section = serializer.save(
            template=template,
            order=next_order,
        )

        template.save(update_fields=["updated_at"])

        return build_response(
            request,
            success=True,
            message="Section added successfully",
            data=LoanTemplateSectionSerializer(section).data,
            status_code=status.HTTP_201_CREATED,
        )


class AdminLoanTemplateSectionDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    def get_object(self, pk):
        return LoanTemplateSection.objects.select_related("template").filter(pk=pk).first()

    def patch(self, request, pk):
        section = self.get_object(pk)

        if not section:
            return build_response(
                request,
                success=False,
                message="Section not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = LoanTemplateSectionSerializer(
            section,
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

        section = serializer.save()
        section.template.save(update_fields=["updated_at"])

        return build_response(
            request,
            success=True,
            message="Section updated successfully",
            data=LoanTemplateSectionSerializer(section).data,
            status_code=status.HTTP_200_OK,
        )

    @transaction.atomic
    def delete(self, request, pk):
        section = self.get_object(pk)

        if not section:
            return build_response(
                request,
                success=False,
                message="Section not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        template = section.template
        section.delete()
        normalize_section_orders(template)
        template.save(update_fields=["updated_at"])

        return build_response(
            request,
            success=True,
            message="Section deleted successfully",
            data={},
            status_code=status.HTTP_200_OK,
        )


class AdminLoanTemplateSectionReorderView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUserRole]

    @transaction.atomic
    def post(self, request, pk):
        template = LoanTemplate.objects.prefetch_related("sections").filter(pk=pk).first()

        if not template:
            return build_response(
                request,
                success=False,
                message="Loan template not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        sections_payload = request.data.get("sections")

        if not isinstance(sections_payload, list) or not sections_payload:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "sections": ["A non-empty list of sections is required."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        existing_ids = set(str(section.id) for section in template.sections.all())
        payload_ids = set(str(item.get("id")) for item in sections_payload if item.get("id"))

        if existing_ids != payload_ids:
            return build_response(
                request,
                success=False,
                message="Validation error",
                data={
                    "sections": ["All template section ids must be provided exactly once."]
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        sections_by_id = {
            str(section.id): section
            for section in template.sections.all()
        }

        sorted_payload = sorted(
            sections_payload,
            key=lambda item: int(item.get("order", 999999)),
        )

        updated_sections = []

        for index, item in enumerate(sorted_payload, start=1):
            section = sections_by_id[str(item.get("id"))]
            section.order = index
            section.save(update_fields=["order", "updated_at"])
            updated_sections.append(section)

        template.save(update_fields=["updated_at"])

        return build_response(
            request,
            success=True,
            message="Sections reordered successfully",
            data=LoanTemplateSectionSerializer(updated_sections, many=True).data,
            status_code=status.HTTP_200_OK,
        )


class CustomerActiveLoanTypeListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search", "").strip()

        page = _to_int(request.query_params.get("page"), 1)
        limit = _to_int(request.query_params.get("limit"), 20)

        sort_by = request.query_params.get("sort_by", "name")
        order = request.query_params.get("order", "asc").lower()

        queryset = LoanType.objects.filter(
            is_active=True,
            template__status=LoanTemplate.STATUS_PUBLISHED,
        )

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search)
            )

        sort_map = {
            "name": "name",
            "date": "created_at",
            "created_at": "created_at",
        }

        sort_field = sort_map.get(sort_by, "name")

        if order == "desc":
            sort_field = f"-{sort_field}"

        queryset = queryset.order_by(sort_field)

        total = queryset.count()
        items = paginate_queryset(queryset, page, limit)

        serializer = CustomerLoanTypeSerializer(items, many=True)

        meta = build_list_meta(
            page=page,
            limit=limit,
            total=total,
            filters={
                "search": search,
                "status": "active",
            },
            sorting={
                "sort_by": sort_by,
                "order": order,
            },
            summary={
                "active_loan_types": total,
            },
        )

        return build_response(
            request,
            success=True,
            message="Active loan types fetched successfully",
            meta=meta,
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )