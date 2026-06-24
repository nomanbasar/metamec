from django.urls import path

from .views import (
    CustomerApplicationDocumentsCompleteView,
    CustomerApplicationDocumentsView,
    CustomerApplicationDocumentUploadView,
    CustomerDocumentDeleteView,
)


urlpatterns = [
    path(
        "customer/loan-applications/<uuid:application_id>/documents/",
        CustomerApplicationDocumentsView.as_view(),
        name="customer_application_documents",
    ),
    path(
        "customer/loan-applications/<uuid:application_id>/documents/upload/",
        CustomerApplicationDocumentUploadView.as_view(),
        name="customer_application_document_upload",
    ),
    path(
        "customer/loan-applications/<uuid:application_id>/documents/complete/",
        CustomerApplicationDocumentsCompleteView.as_view(),
        name="customer_application_documents_complete",
    ),
    path(
        "customer/documents/<uuid:document_id>/",
        CustomerDocumentDeleteView.as_view(),
        name="customer_document_delete",
    ),
]