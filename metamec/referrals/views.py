from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from authentication.utils import build_response

from .utils import dashboard_payload


class ReferralDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return build_response(
            request,
            success=True,
            message="Referral dashboard fetched successfully",
            data=dashboard_payload(request.user),
            status_code=status.HTTP_200_OK,
        )