from django.urls import path

from .views import ReferralDashboardView


urlpatterns = [
    path(
        "referrals/dashboard/",
        ReferralDashboardView.as_view(),
        name="referral_dashboard",
    ),
]