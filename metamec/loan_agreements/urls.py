from django.urls import path

from .views import (
    CoApplicantInvitationDetailView,
    CoApplicantInvitationRespondView,
    CoApplicantInviteView,
    CoApplicantSkipView,
    CustomerAgreementDetailView,
    CustomerAgreementDownloadView,
    CustomerAgreementSignView,
)


urlpatterns = [
    path(
        "agreements/<uuid:application_id>/",
        CustomerAgreementDetailView.as_view(),
        name="customer_agreement_detail",
    ),
    path(
        "agreements/<uuid:application_id>/sign/",
        CustomerAgreementSignView.as_view(),
        name="customer_agreement_sign",
    ),
    path(
        "agreements/<uuid:application_id>/download/",
        CustomerAgreementDownloadView.as_view(),
        name="customer_agreement_download",
    ),

    path(
        "agreements/<uuid:application_id>/co-applicant/invite/",
        CoApplicantInviteView.as_view(),
        name="co_applicant_invite",
    ),
    path(
        "agreements/<uuid:application_id>/co-applicant/skip/",
        CoApplicantSkipView.as_view(),
        name="co_applicant_skip",
    ),

    path(
        "agreements/co-applicant/invitations/<uuid:token>/",
        CoApplicantInvitationDetailView.as_view(),
        name="co_applicant_invitation_detail",
    ),
    path(
        "agreements/co-applicant/invitations/<uuid:token>/respond/",
        CoApplicantInvitationRespondView.as_view(),
        name="co_applicant_invitation_respond",
    ),
]