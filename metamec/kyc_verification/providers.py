import base64
import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


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

    def submit_check(self, kyc, extra_data=None):
        return {
            "provider": self.name,
            "check_id": f"mock_check_{uuid.uuid4().hex[:16]}",
            "status": "in_progress",
            "result": None,
            "mode": "mock",
            "note": "Mock KYC check created.",
        }

    def get_check_result(self, kyc):
        return {
            "provider": self.name,
            "check_id": kyc.provider_check_id,
            "status": "in_progress",
            "result": None,
            "mode": "mock",
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
                "warning": "ONFIDO_API_TOKEN missing.",
            }

        return {
            "provider": self.name,
            "applicant_id": kyc.provider_applicant_id or f"onfido_ready_applicant_{uuid.uuid4().hex[:16]}",
        }

    def upload_document(self, kyc):
        return {
            "provider": self.name,
            "document_id": f"onfido_document_{uuid.uuid4().hex[:16]}",
        }

    def upload_selfie(self, kyc):
        return {
            "provider": self.name,
            "selfie_id": f"onfido_selfie_{uuid.uuid4().hex[:16]}",
        }

    def submit_check(self, kyc, extra_data=None):
        return {
            "provider": self.name,
            "check_id": f"onfido_check_{uuid.uuid4().hex[:16]}",
            "status": "in_progress",
            "result": None,
        }


class ComplianceAssistKYCProvider(MockKYCProvider):
    name = "complianceassist"

    TOKEN_CACHE_KEY = "complianceassist_access_token"

    def _credentials_ready(self):
        return bool(
            getattr(settings, "COMPLIANCE_ASSIST_CLIENT_ID", "")
            and getattr(settings, "COMPLIANCE_ASSIST_CLIENT_SECRET", "")
        )

    def _request_json(self, method, url, headers=None, body=None):
        headers = headers or {}

        data = None
        if body is not None:
            if headers.get("Content-Type") == "application/x-www-form-urlencoded":
                data = urlencode(body).encode("utf-8")
            else:
                data = json.dumps(body).encode("utf-8")

        req = Request(url=url, data=data, headers=headers, method=method)

        try:
            with urlopen(req, timeout=getattr(settings, "COMPLIANCE_ASSIST_TIMEOUT", 30)) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            raise Exception(f"ComplianceAssist HTTP {exc.code}: {error_body}")
        except URLError as exc:
            raise Exception(f"ComplianceAssist connection error: {exc}")
        except Exception as exc:
            raise Exception(f"ComplianceAssist error: {exc}")

    def get_access_token(self):
        cached_token = cache.get(self.TOKEN_CACHE_KEY)
        if cached_token:
            return cached_token

        if not self._credentials_ready():
            raise Exception("ComplianceAssist credentials missing in .env")

        raw_basic = (
            f"{settings.COMPLIANCE_ASSIST_CLIENT_ID}:"
            f"{settings.COMPLIANCE_ASSIST_CLIENT_SECRET}"
        )
        basic_token = base64.b64encode(raw_basic.encode("utf-8")).decode("utf-8")

        response = self._request_json(
            method="POST",
            url=settings.COMPLIANCE_ASSIST_AUTH_URL,
            headers={
                "Authorization": f"Basic {basic_token}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            body={
                "grant_type": "client_credentials",
                "scope": settings.COMPLIANCE_ASSIST_SCOPE,
            },
        )

        access_token = response.get("access_token")
        expires_in = int(response.get("expires_in") or 3600)

        if not access_token:
            raise Exception(f"ComplianceAssist token missing from response: {response}")

        cache.set(self.TOKEN_CACHE_KEY, access_token, max(expires_in - 60, 60))
        return access_token

    def create_or_update_applicant(self, kyc):
        return {
            "provider": self.name,
            "applicant_id": kyc.provider_applicant_id or str(kyc.user_id),
            "mode": "complianceassist",
            "note": "ComplianceAssist creates request at submit step.",
        }

    def upload_document(self, kyc):
        return {
            "provider": self.name,
            "document_id": f"local_document_{kyc.id}",
            "mode": "local_file_saved",
            "note": "Document saved locally. ComplianceAssist request is submitted at submit step.",
        }

    def upload_selfie(self, kyc):
        return {
            "provider": self.name,
            "selfie_id": f"local_selfie_{kyc.id}",
            "mode": "local_file_saved",
            "note": "Selfie saved locally. ComplianceAssist request is submitted at submit step.",
        }

    def _get_subject_details(self, kyc, extra_data=None):
        extra_data = extra_data or {}
        user = kyc.user

        name = (
            extra_data.get("name")
            or extra_data.get("full_name")
            or getattr(user, "full_name", "")
            or "Customer"
        )

        address = (
            extra_data.get("address")
            or extra_data.get("primary_address")
            or getattr(user, "location", "")
            or "Address not provided"
        )

        dob = (
            extra_data.get("dob")
            or extra_data.get("date_of_birth")
            or extra_data.get("dateOfBirth")
            or "1990-01-01"
        )

        return {
            "name": str(name),
            "address": str(address),
            "dob": str(dob),
        }

    def submit_check(self, kyc, extra_data=None):
        token = self.get_access_token()

        payload = {
            "requestType": settings.COMPLIANCE_ASSIST_REQUEST_TYPE,
            "subjectType": "INDIVIDUAL",
            "subjectReference": str(kyc.user_id),
            "subjectDetails": self._get_subject_details(kyc, extra_data),
        }

        response = self._request_json(
            method="POST",
            url=f"{settings.COMPLIANCE_ASSIST_BASE_URL.rstrip('/')}/requests",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            body=payload,
        )

        request_id = (
            response.get("id")
            or response.get("requestId")
            or response.get("request_id")
            or response.get("data", {}).get("id")
        )

        if not request_id:
            raise Exception(f"ComplianceAssist request id missing from response: {response}")

        return {
            "provider": self.name,
            "check_id": request_id,
            "status": response.get("status") or "in_progress",
            "result": response.get("result"),
            "request_payload": payload,
            "raw_response": response,
        }

    def get_check_result(self, kyc):
        if not kyc.provider_check_id:
            raise Exception("ComplianceAssist request id not found")

        token = self.get_access_token()

        response = self._request_json(
            method="GET",
            url=f"{settings.COMPLIANCE_ASSIST_BASE_URL.rstrip('/')}/requests/{kyc.provider_check_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

        return {
            "provider": self.name,
            "check_id": kyc.provider_check_id,
            "status": response.get("status"),
            "result": response.get("result"),
            "raw_response": response,
        }


def get_kyc_provider():
    provider = str(getattr(settings, "KYC_PROVIDER", "mock") or "mock").lower()

    if provider == "onfido":
        return OnfidoKYCProvider()

    if provider in ["complianceassist", "compliance_assist", "compliance"]:
        return ComplianceAssistKYCProvider()

    return MockKYCProvider()