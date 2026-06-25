from django.urls import path

from .views import (
    AdminKYCDetailView,
    AdminKYCListView,
    AdminKYCStatusUpdateView,
    CustomerKYCStatusView,
    CustomerKYCSubmitView,
    CustomerKYCUploadIDView,
    CustomerKYCUploadSelfieView,
    OnfidoWebhookView,
)


urlpatterns = [
    path("kyc/me/", CustomerKYCStatusView.as_view(), name="customer_kyc_status"),
    path("kyc/upload-id/", CustomerKYCUploadIDView.as_view(), name="customer_kyc_upload_id"),
    path("kyc/upload-selfie/", CustomerKYCUploadSelfieView.as_view(), name="customer_kyc_upload_selfie"),
    path("kyc/submit/", CustomerKYCSubmitView.as_view(), name="customer_kyc_submit"),
    path("kyc/onfido/webhook/", OnfidoWebhookView.as_view(), name="onfido_kyc_webhook"),

    path("admin/kyc/", AdminKYCListView.as_view(), name="admin_kyc_list"),
    path("admin/kyc/<uuid:kyc_id>/", AdminKYCDetailView.as_view(), name="admin_kyc_detail"),
    path("admin/kyc/<uuid:kyc_id>/status/", AdminKYCStatusUpdateView.as_view(), name="admin_kyc_status_update"),
]