from django.urls import path

from .views import (
    CustomerLoanApplicationDetailView,
    CustomerLoanApplicationListCreateView,
    CustomerLoanApplicationSubmitView,
    CustomerMyLoansView,
)


urlpatterns = [
    path(
        "customer/loan-applications/",
        CustomerLoanApplicationListCreateView.as_view(),
        name="customer_loan_application_list_create",
    ),
    path(
        "customer/loan-applications/<uuid:pk>/",
        CustomerLoanApplicationDetailView.as_view(),
        name="customer_loan_application_detail",
    ),
    path(
        "customer/loan-applications/<uuid:pk>/submit/",
        CustomerLoanApplicationSubmitView.as_view(),
        name="customer_loan_application_submit",
    ),
    path(
        "customer/my-loans/",
        CustomerMyLoansView.as_view(),
        name="customer_my_loans",
    ),
]