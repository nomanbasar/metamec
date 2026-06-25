import uuid

from django.conf import settings


class MockKYCProvider:
    name = "mock"

    def create_or_update_applicant(self, kyc):
        return {
            "provider": self.name,
            "applicant_id": kyc.provider_applicant_id or f"mock_applicant_{uuid.uuid4().hex[:16]}",
            "mode": "mock",
        }

    def upload_document(self, kyc):
        return {
            "provider": self.name,
            "document_id": f"mock_document_{uuid.uuid4().hex[:16]}",
            "mode": "mock",
        }

    def upload_selfie(self, kyc):
        return {
            "provider": self.name,
            "selfie_id": f"mock_selfie_{uuid.uuid4().hex[:16]}",
            "mode": "mock",
        }

    def submit_check(self, kyc):
        return {
            "provider": self.name,
            "check_id": f"mock_check_{uuid.uuid4().hex[:16]}",
            "status": "in_progress",
            "result": None,
            "mode": "mock",
            "note": "Mock KYC check created. Real Onfido integration can be added without changing frontend API.",
        }


class OnfidoKYCProvider(MockKYCProvider):
    name = "onfido"

    def _credentials_ready(self):
        return bool(getattr(settings, "ONFIDO_API_TOKEN", ""))

    def create_or_update_applicant(self, kyc):
        if not self._credentials_ready():
            return {
                "provider": self.name,
                "applicant_id": kyc.provider_applicant_id or f"onfido_pending_applicant_{uuid.uuid4().hex[:16]}",
                "warning": "ONFIDO_API_TOKEN missing. Real Onfido applicant request was not sent.",
            }

        return {
            "provider": self.name,
            "applicant_id": kyc.provider_applicant_id or f"onfido_ready_applicant_{uuid.uuid4().hex[:16]}",
            "note": "Replace this method with real Onfido applicant API call when credentials are available.",
        }

    def upload_document(self, kyc):
        if not self._credentials_ready():
            return {
                "provider": self.name,
                "document_id": f"onfido_pending_document_{uuid.uuid4().hex[:16]}",
                "warning": "ONFIDO_API_TOKEN missing. Real Onfido document request was not sent.",
            }

        return {
            "provider": self.name,
            "document_id": f"onfido_ready_document_{uuid.uuid4().hex[:16]}",
            "note": "Replace this method with real Onfido document upload API call.",
        }

    def upload_selfie(self, kyc):
        if not self._credentials_ready():
            return {
                "provider": self.name,
                "selfie_id": f"onfido_pending_selfie_{uuid.uuid4().hex[:16]}",
                "warning": "ONFIDO_API_TOKEN missing. Real Onfido selfie request was not sent.",
            }

        return {
            "provider": self.name,
            "selfie_id": f"onfido_ready_selfie_{uuid.uuid4().hex[:16]}",
            "note": "Replace this method with real Onfido selfie upload API call.",
        }

    def submit_check(self, kyc):
        if not self._credentials_ready():
            return {
                "provider": self.name,
                "check_id": f"onfido_pending_check_{uuid.uuid4().hex[:16]}",
                "status": "in_progress",
                "result": None,
                "warning": "ONFIDO_API_TOKEN missing. Real Onfido check request was not sent.",
            }

        return {
            "provider": self.name,
            "check_id": f"onfido_ready_check_{uuid.uuid4().hex[:16]}",
            "status": "in_progress",
            "result": None,
            "note": "Replace this method with real Onfido check API call.",
        }


def get_kyc_provider():
    provider = str(getattr(settings, "KYC_PROVIDER", "mock") or "mock").lower()

    if provider == "onfido":
        return OnfidoKYCProvider()

    return MockKYCProvider()