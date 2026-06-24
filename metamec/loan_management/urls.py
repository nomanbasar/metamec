from django.urls import path

from .views import (
    AdminLoanTemplateDetailView,
    AdminLoanTemplateDropdownView,
    AdminLoanTemplateListCreateView,
    AdminLoanTemplateMarkDraftView,
    AdminLoanTemplatePublishView,
    AdminLoanTemplateSectionCreateView,
    AdminLoanTemplateSectionDetailView,
    AdminLoanTemplateSectionReorderView,
    AdminLoanTypeDetailView,
    AdminLoanTypeListCreateView,
    AdminLoanTypeToggleStatusView,
    CustomerActiveLoanTypeListView,
    LoanManagementSummaryView,
)


urlpatterns = [
    path(
        "admin/loan-management/summary/",
        LoanManagementSummaryView.as_view(),
        name="admin_loan_management_summary",
    ),

    path(
        "admin/loan-types/",
        AdminLoanTypeListCreateView.as_view(),
        name="admin_loan_type_list_create",
    ),
    path(
        "admin/loan-types/<uuid:pk>/",
        AdminLoanTypeDetailView.as_view(),
        name="admin_loan_type_detail",
    ),
    path(
        "admin/loan-types/<uuid:pk>/toggle-status/",
        AdminLoanTypeToggleStatusView.as_view(),
        name="admin_loan_type_toggle_status",
    ),

    path(
        "admin/loan-templates/",
        AdminLoanTemplateListCreateView.as_view(),
        name="admin_loan_template_list_create",
    ),
    path(
        "admin/loan-templates/dropdown/",
        AdminLoanTemplateDropdownView.as_view(),
        name="admin_loan_template_dropdown",
    ),
    path(
        "admin/loan-templates/<uuid:pk>/",
        AdminLoanTemplateDetailView.as_view(),
        name="admin_loan_template_detail",
    ),
    path(
        "admin/loan-templates/<uuid:pk>/publish/",
        AdminLoanTemplatePublishView.as_view(),
        name="admin_loan_template_publish",
    ),
    path(
        "admin/loan-templates/<uuid:pk>/mark-draft/",
        AdminLoanTemplateMarkDraftView.as_view(),
        name="admin_loan_template_mark_draft",
    ),
    path(
        "admin/loan-templates/<uuid:pk>/sections/",
        AdminLoanTemplateSectionCreateView.as_view(),
        name="admin_loan_template_section_create",
    ),
    path(
        "admin/loan-templates/<uuid:pk>/sections/reorder/",
        AdminLoanTemplateSectionReorderView.as_view(),
        name="admin_loan_template_section_reorder",
    ),
    path(
        "admin/template-sections/<uuid:pk>/",
        AdminLoanTemplateSectionDetailView.as_view(),
        name="admin_loan_template_section_detail",
    ),

    path(
        "customer/loan-types/",
        CustomerActiveLoanTypeListView.as_view(),
        name="customer_active_loan_type_list",
    ),
]