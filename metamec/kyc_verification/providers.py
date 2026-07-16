# import base64
# import json
# import uuid
# from urllib.error import HTTPError, URLError
# from urllib.parse import urlencode
# from urllib.request import Request, urlopen

# from django.conf import settings
# from django.core.cache import cache


# class MockKYCProvider:
#     name = "mock"

#     def create_or_update_applicant(self, kyc):
#         return {
#             "provider": self.name,
#             "applicant_id": kyc.provider_applicant_id or f"mock_applicant_{uuid.uuid4().hex[:16]}",
#             "mode": "mock",
#         }

#     def upload_document(self, kyc):
#         return {
#             "provider": self.name,
#             "document_id": f"mock_document_{uuid.uuid4().hex[:16]}",
#             "mode": "mock",
#         }

#     def upload_selfie(self, kyc):
#         return {
#             "provider": self.name,
#             "selfie_id": f"mock_selfie_{uuid.uuid4().hex[:16]}",
#             "mode": "mock",
#         }

#     def submit_check(self, kyc, extra_data=None):
#         return {
#             "provider": self.name,
#             "check_id": f"mock_check_{uuid.uuid4().hex[:16]}",
#             "status": "in_progress",
#             "result": None,
#             "mode": "mock",
#             "note": "Mock KYC check created.",
#         }

#     def get_check_result(self, kyc):
#         return {
#             "provider": self.name,
#             "check_id": kyc.provider_check_id,
#             "status": "in_progress",
#             "result": None,
#             "mode": "mock",
#         }


# class OnfidoKYCProvider(MockKYCProvider):
#     name = "onfido"

#     def _credentials_ready(self):
#         return bool(getattr(settings, "ONFIDO_API_TOKEN", ""))

#     def create_or_update_applicant(self, kyc):
#         if not self._credentials_ready():
#             return {
#                 "provider": self.name,
#                 "applicant_id": kyc.provider_applicant_id or f"onfido_pending_applicant_{uuid.uuid4().hex[:16]}",
#                 "warning": "ONFIDO_API_TOKEN missing.",
#             }

#         return {
#             "provider": self.name,
#             "applicant_id": kyc.provider_applicant_id or f"onfido_ready_applicant_{uuid.uuid4().hex[:16]}",
#         }

#     def upload_document(self, kyc):
#         return {
#             "provider": self.name,
#             "document_id": f"onfido_document_{uuid.uuid4().hex[:16]}",
#         }

#     def upload_selfie(self, kyc):
#         return {
#             "provider": self.name,
#             "selfie_id": f"onfido_selfie_{uuid.uuid4().hex[:16]}",
#         }

#     def submit_check(self, kyc, extra_data=None):
#         return {
#             "provider": self.name,
#             "check_id": f"onfido_check_{uuid.uuid4().hex[:16]}",
#             "status": "in_progress",
#             "result": None,
#         }


# class ComplianceAssistKYCProvider(MockKYCProvider):
#     name = "complianceassist"

#     TOKEN_CACHE_KEY = "complianceassist_access_token"

#     def _credentials_ready(self):
#         return bool(
#             getattr(settings, "COMPLIANCE_ASSIST_CLIENT_ID", "")
#             and getattr(settings, "COMPLIANCE_ASSIST_CLIENT_SECRET", "")
#         )

#     def _request_json(self, method, url, headers=None, body=None):
#         headers = headers or {}

#         data = None
#         if body is not None:
#             if headers.get("Content-Type") == "application/x-www-form-urlencoded":
#                 data = urlencode(body).encode("utf-8")
#             else:
#                 data = json.dumps(body).encode("utf-8")

#         req = Request(url=url, data=data, headers=headers, method=method)

#         try:
#             with urlopen(req, timeout=getattr(settings, "COMPLIANCE_ASSIST_TIMEOUT", 30)) as response:
#                 raw = response.read().decode("utf-8")
#                 return json.loads(raw) if raw else {}
#         except HTTPError as exc:
#             error_body = exc.read().decode("utf-8", errors="ignore")
#             raise Exception(f"ComplianceAssist HTTP {exc.code}: {error_body}")
#         except URLError as exc:
#             raise Exception(f"ComplianceAssist connection error: {exc}")
#         except Exception as exc:
#             raise Exception(f"ComplianceAssist error: {exc}")

#     def get_access_token(self):
#         cached_token = cache.get(self.TOKEN_CACHE_KEY)
#         if cached_token:
#             return cached_token

#         if not self._credentials_ready():
#             raise Exception("ComplianceAssist credentials missing in .env")

#         raw_basic = (
#             f"{settings.COMPLIANCE_ASSIST_CLIENT_ID}:"
#             f"{settings.COMPLIANCE_ASSIST_CLIENT_SECRET}"
#         )
#         basic_token = base64.b64encode(raw_basic.encode("utf-8")).decode("utf-8")

#         response = self._request_json(
#             method="POST",
#             url=settings.COMPLIANCE_ASSIST_AUTH_URL,
#             headers={
#                 "Authorization": f"Basic {basic_token}",
#                 "Content-Type": "application/x-www-form-urlencoded",
#                 "Accept": "application/json",
#             },
#             body={
#                 "grant_type": "client_credentials",
#                 "scope": settings.COMPLIANCE_ASSIST_SCOPE,
#             },
#         )

#         access_token = response.get("access_token")
#         expires_in = int(response.get("expires_in") or 3600)

#         if not access_token:
#             raise Exception(f"ComplianceAssist token missing from response: {response}")

#         cache.set(self.TOKEN_CACHE_KEY, access_token, max(expires_in - 60, 60))
#         return access_token

#     def create_or_update_applicant(self, kyc):
#         return {
#             "provider": self.name,
#             "applicant_id": kyc.provider_applicant_id or str(kyc.user_id),
#             "mode": "complianceassist",
#             "note": "ComplianceAssist creates request at submit step.",
#         }

#     def upload_document(self, kyc):
#         return {
#             "provider": self.name,
#             "document_id": f"local_document_{kyc.id}",
#             "mode": "local_file_saved",
#             "note": "Document saved locally. ComplianceAssist request is submitted at submit step.",
#         }

#     def upload_selfie(self, kyc):
#         return {
#             "provider": self.name,
#             "selfie_id": f"local_selfie_{kyc.id}",
#             "mode": "local_file_saved",
#             "note": "Selfie saved locally. ComplianceAssist request is submitted at submit step.",
#         }

#     def _get_subject_details(self, kyc, extra_data=None):
#         extra_data = extra_data or {}
#         user = kyc.user

#         name = (
#             extra_data.get("name")
#             or extra_data.get("full_name")
#             or getattr(user, "full_name", "")
#             or "Customer"
#         )

#         address = (
#             extra_data.get("address")
#             or extra_data.get("primary_address")
#             or getattr(user, "location", "")
#             or "Address not provided"
#         )

#         dob = (
#             extra_data.get("dob")
#             or extra_data.get("date_of_birth")
#             or extra_data.get("dateOfBirth")
#             or "1990-01-01"
#         )

#         return {
#             "name": str(name),
#             "address": str(address),
#             "dob": str(dob),
#         }

#     def submit_check(self, kyc, extra_data=None):
#         token = self.get_access_token()

#         payload = {
#             "requestType": settings.COMPLIANCE_ASSIST_REQUEST_TYPE,
#             "subjectType": "INDIVIDUAL",
#             "subjectReference": str(kyc.user_id),
#             "subjectDetails": self._get_subject_details(kyc, extra_data),
#         }

#         response = self._request_json(
#             method="POST",
#             url=f"{settings.COMPLIANCE_ASSIST_BASE_URL.rstrip('/')}/requests",
#             headers={
#                 "Authorization": f"Bearer {token}",
#                 "Content-Type": "application/json",
#                 "Accept": "application/json",
#             },
#             body=payload,
#         )

#         request_id = (
#             response.get("id")
#             or response.get("requestId")
#             or response.get("request_id")
#             or response.get("data", {}).get("id")
#         )

#         if not request_id:
#             raise Exception(f"ComplianceAssist request id missing from response: {response}")

#         return {
#             "provider": self.name,
#             "check_id": request_id,
#             "status": response.get("status") or "in_progress",
#             "result": response.get("result"),
#             "request_payload": payload,
#             "raw_response": response,
#         }

#     def get_check_result(self, kyc):
#         if not kyc.provider_check_id:
#             raise Exception("ComplianceAssist request id not found")

#         token = self.get_access_token()

#         response = self._request_json(
#             method="GET",
#             url=f"{settings.COMPLIANCE_ASSIST_BASE_URL.rstrip('/')}/requests/{kyc.provider_check_id}",
#             headers={
#                 "Authorization": f"Bearer {token}",
#                 "Accept": "application/json",
#             },
#         )

#         return {
#             "provider": self.name,
#             "check_id": kyc.provider_check_id,
#             "status": response.get("status"),
#             "result": response.get("result"),
#             "raw_response": response,
#         }


# def get_kyc_provider():
#     provider = str(getattr(settings, "KYC_PROVIDER", "mock") or "mock").lower()

#     if provider == "onfido":
#         return OnfidoKYCProvider()

#     if provider in ["complianceassist", "compliance_assist", "compliance"]:
#         return ComplianceAssistKYCProvider()

#     return MockKYCProvider()


import base64
import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


class KYCProviderError(Exception):
    def __init__(
        self,
        message,
        status_code=None,
        response_data=None,
        api_request_id=None,
    ):
        super().__init__(message)

        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        self.api_request_id = api_request_id

    def as_dict(self):
        return {
            "message": self.message,
            "statusCode": self.status_code,
            "apiRequestId": self.api_request_id,
            "providerResponse": self.response_data,
        }


class MockKYCProvider:
    name = "mock"

    def create_or_update_applicant(self, kyc):
        return {
            "provider": self.name,
            "applicant_id": (
                kyc.provider_applicant_id
                or f"mock_applicant_{uuid.uuid4().hex[:16]}"
            ),
            "mode": "mock",
        }

    def upload_document(self, kyc):
        return {
            "provider": self.name,
            "document_id": (
                f"mock_document_{uuid.uuid4().hex[:16]}"
            ),
            "mode": "mock",
        }

    def upload_selfie(self, kyc):
        return {
            "provider": self.name,
            "selfie_id": (
                f"mock_selfie_{uuid.uuid4().hex[:16]}"
            ),
            "mode": "mock",
        }

    def submit_check(self, kyc, extra_data=None):
        return {
            "provider": self.name,
            "check_id": (
                f"mock_check_{uuid.uuid4().hex[:16]}"
            ),
            "status": "in_progress",
            "result": None,
            "verification_url": None,
            "mode": "mock",
        }

    def get_check_result(self, kyc):
        return {
            "provider": self.name,
            "check_id": kyc.provider_check_id,
            "status": "in_progress",
            "result": None,
            "verification_url": None,
            "mode": "mock",
        }


class OnfidoKYCProvider(MockKYCProvider):
    name = "onfido"

    def _credentials_ready(self):
        return bool(
            getattr(settings, "ONFIDO_API_TOKEN", "")
        )

    def create_or_update_applicant(self, kyc):
        if not self._credentials_ready():
            return {
                "provider": self.name,
                "applicant_id": (
                    kyc.provider_applicant_id
                    or (
                        "onfido_pending_applicant_"
                        f"{uuid.uuid4().hex[:16]}"
                    )
                ),
                "warning": "ONFIDO_API_TOKEN missing.",
            }

        return {
            "provider": self.name,
            "applicant_id": (
                kyc.provider_applicant_id
                or (
                    "onfido_ready_applicant_"
                    f"{uuid.uuid4().hex[:16]}"
                )
            ),
        }

    def upload_document(self, kyc):
        return {
            "provider": self.name,
            "document_id": (
                f"onfido_document_{uuid.uuid4().hex[:16]}"
            ),
        }

    def upload_selfie(self, kyc):
        return {
            "provider": self.name,
            "selfie_id": (
                f"onfido_selfie_{uuid.uuid4().hex[:16]}"
            ),
        }

    def submit_check(self, kyc, extra_data=None):
        return {
            "provider": self.name,
            "check_id": (
                f"onfido_check_{uuid.uuid4().hex[:16]}"
            ),
            "status": "in_progress",
            "result": None,
            "verification_url": None,
        }


class ComplianceAssistKYCProvider:
    name = "complianceassist"

    def _credentials_ready(self):
        return bool(
            getattr(
                settings,
                "COMPLIANCE_ASSIST_CLIENT_ID",
                "",
            )
            and getattr(
                settings,
                "COMPLIANCE_ASSIST_CLIENT_SECRET",
                "",
            )
        )

    @staticmethod
    def _decode_response(raw_body):
        if not raw_body:
            return {}

        decoded = raw_body.decode(
            "utf-8",
            errors="replace",
        )

        try:
            return json.loads(decoded)
        except json.JSONDecodeError:
            return {"raw": decoded}

    def _request_json(
        self,
        method,
        url,
        headers=None,
        body=None,
    ):
        headers = headers or {}
        request_data = None

        if body is not None:
            content_type = headers.get(
                "Content-Type",
                "",
            )

            if content_type.startswith(
                "application/x-www-form-urlencoded"
            ):
                request_data = urlencode(body).encode(
                    "utf-8"
                )
            else:
                request_data = json.dumps(
                    body,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")

        request_object = Request(
            url=url,
            data=request_data,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urlopen(
                request_object,
                timeout=getattr(
                    settings,
                    "COMPLIANCE_ASSIST_TIMEOUT",
                    30,
                ),
            ) as response:
                return self._decode_response(
                    response.read()
                )

        except HTTPError as exc:
            response_data = self._decode_response(
                exc.read()
            )

            api_request_id = None

            if isinstance(response_data, dict):
                api_request_id = response_data.get(
                    "apiRequestId"
                )

            raise KYCProviderError(
                message=(
                    "ComplianceAssist returned "
                    f"HTTP {exc.code}"
                ),
                status_code=exc.code,
                response_data=response_data,
                api_request_id=api_request_id,
            ) from exc

        except URLError as exc:
            raise KYCProviderError(
                message=(
                    "Could not connect to "
                    "ComplianceAssist"
                ),
                response_data={
                    "reason": str(exc.reason),
                },
            ) from exc

        except TimeoutError as exc:
            raise KYCProviderError(
                message=(
                    "ComplianceAssist request timed out"
                ),
            ) from exc

    @staticmethod
    def _token_cache_key(scope):
        safe_scope = (
            str(scope)
            .replace("/", "_")
            .replace(".", "_")
        )

        return (
            "complianceassist_access_token_"
            f"{safe_scope}"
        )

    def get_access_token(
        self,
        scope,
        force_refresh=False,
    ):
        if not self._credentials_ready():
            raise KYCProviderError(
                "ComplianceAssist credentials "
                "are missing in .env"
            )

        cache_key = self._token_cache_key(scope)

        if not force_refresh:
            cached_token = cache.get(cache_key)

            if cached_token:
                return cached_token

        credentials = (
            f"{settings.COMPLIANCE_ASSIST_CLIENT_ID}:"
            f"{settings.COMPLIANCE_ASSIST_CLIENT_SECRET}"
        )

        basic_token = base64.b64encode(
            credentials.encode("utf-8")
        ).decode("ascii")

        response = self._request_json(
            method="POST",
            url=settings.COMPLIANCE_ASSIST_AUTH_URL,
            headers={
                "Authorization": f"Basic {basic_token}",
                "Accept": "application/json",
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
            },
            body={
                "grant_type": "client_credentials",
                "scope": scope,
            },
        )

        access_token = response.get("access_token")
        expires_in = int(
            response.get("expires_in") or 3600
        )

        if not access_token:
            raise KYCProviderError(
                message=(
                    "ComplianceAssist access token "
                    "missing from response"
                ),
                response_data=response,
            )

        
        cache_timeout = max(
            expires_in - 120,
            60,
        )

        cache.set(
            cache_key,
            access_token,
            cache_timeout,
        )

        return access_token

    def _authenticated_request(
        self,
        method,
        endpoint,
        scope,
        body=None,
    ):
        url = (
            f"{settings.COMPLIANCE_ASSIST_BASE_URL}/"
            f"{endpoint.lstrip('/')}"
        )

        for attempt in range(2):
            token = self.get_access_token(
                scope=scope,
                force_refresh=(attempt == 1),
            )

            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            if body is not None:
                headers["Content-Type"] = (
                    "application/json"
                )

            try:
                return self._request_json(
                    method=method,
                    url=url,
                    headers=headers,
                    body=body,
                )

            except KYCProviderError as exc:
                if (
                    exc.status_code == 401
                    and attempt == 0
                ):
                    cache.delete(
                        self._token_cache_key(scope)
                    )
                    continue

                raise

        raise KYCProviderError(
            "ComplianceAssist authentication failed"
        )

    def create_or_update_applicant(self, kyc):
        return {
            "provider": self.name,
            "applicant_id": str(kyc.user_id),
            "mode": "complianceassist",
        }

    def upload_document(self, kyc):
        return {
            "provider": self.name,
            "document_id": None,
            "mode": "hosted_verification",
            "note": (
                "ComplianceAssist captures the ID "
                "through verificationUrl."
            ),
        }

    def upload_selfie(self, kyc):
        return {
            "provider": self.name,
            "selfie_id": None,
            "mode": "hosted_verification",
            "note": (
                "ComplianceAssist captures the selfie "
                "through verificationUrl."
            ),
        }

    @staticmethod
    def _clean_text(value):
        if value is None:
            return None

        value = str(value).strip()

        return value or None

    def _get_subject_details(
        self,
        extra_data=None,
    ):
        extra_data = extra_data or {}

        subject_details = (
            extra_data.get("subjectDetails")
            or extra_data.get("subject_details")
            or {}
        )

        if not isinstance(subject_details, dict):
            raise KYCProviderError(
                message=(
                    "subjectDetails must be "
                    "a JSON object"
                ),
                status_code=400,
            )

        allowed_fields = [
            "firstName",
            "surname",
            "gender",
            "country",
            "addressLine1",
            "addressLine2",
            "city",
            "postcode",
            "dateOfBirth",
        ]

        cleaned = {}

        for field_name in allowed_fields:
            value = self._clean_text(
                subject_details.get(field_name)
            )

            if value is not None:
                cleaned[field_name] = value

        required_fields = [
            "firstName",
            "surname",
            "gender",
            "country",
            "addressLine1",
            "city",
            "dateOfBirth",
        ]

        missing_fields = [
            field_name
            for field_name in required_fields
            if not cleaned.get(field_name)
        ]

        if missing_fields:
            raise KYCProviderError(
                message=(
                    "Required subjectDetails fields "
                    "are missing"
                ),
                status_code=400,
                response_data={
                    "missingFields": missing_fields,
                },
            )

        cleaned["gender"] = (
            cleaned["gender"].upper()
        )

        if cleaned["gender"] not in [
            "MALE",
            "FEMALE",
        ]:
            raise KYCProviderError(
                message=(
                    "gender must be MALE or FEMALE"
                ),
                status_code=400,
                response_data={
                    "gender": [
                        "Allowed values: MALE, FEMALE"
                    ]
                },
            )

        return cleaned

    @staticmethod
    def _subject_reference(kyc):
        # প্রতি KYC record-এর জন্য unique reference।
        return f"METAMEC-KYC-{kyc.id}"

    @staticmethod
    def _request_reference(kyc):
        if (
            kyc.application
            and kyc.application.application_number
        ):
            return (
                "METAMEC-"
                f"{kyc.application.application_number}"
            )

        return f"METAMEC-KYC-{kyc.id}"

    @staticmethod
    def _extract_verification_url(response):
        results = response.get("results") or {}

        physical_results = (
            results.get(
                "physicalIdVerificationResults"
            )
            or results.get(
                "physicalIDVerificationResults"
            )
            or {}
        )

        if not isinstance(
            physical_results,
            dict,
        ):
            return None

        return physical_results.get("url")

    def submit_check(
        self,
        kyc,
        extra_data=None,
    ):
        if kyc.provider_check_id:
            existing_check = (
                (kyc.provider_response or {})
                .get("check")
                or {}
            )

            return {
                "provider": self.name,
                "check_id": kyc.provider_check_id,
                "status": (
                    existing_check.get("status")
                    or kyc.status
                ),
                "result": existing_check.get("result"),
                "verification_url": (
                    existing_check.get(
                        "verification_url"
                    )
                ),
                "raw_response": (
                    existing_check.get(
                        "raw_response"
                    )
                    or {}
                ),
                "already_submitted": True,
            }

        subject_details = self._get_subject_details(
            extra_data
        )

        payload = {
            "requestType": (
                settings
                .COMPLIANCE_ASSIST_REQUEST_TYPE
            ),
            "subjectType": "INDIVIDUAL",
            "subjectReference": (
                self._subject_reference(kyc)
            ),
            "requestReference": (
                self._request_reference(kyc)
            ),
            "subjectDetails": subject_details,
        }

        response = self._authenticated_request(
            method="POST",
            endpoint="requests",
            scope=(
                settings
                .COMPLIANCE_ASSIST_WRITE_SCOPE
            ),
            body=payload,
        )

        request_id = response.get("requestId")

        if not request_id:
            raise KYCProviderError(
                message=(
                    "ComplianceAssist requestId "
                    "missing from response"
                ),
                response_data=response,
                api_request_id=response.get(
                    "apiRequestId"
                ),
            )

        return {
            "provider": self.name,
            "check_id": str(request_id),
            "subject_id": response.get("subjectId"),
            "api_request_id": response.get(
                "apiRequestId"
            ),
            "status": (
                response.get("requestStatus")
                or response.get("status")
            ),
            "result": response.get("results"),
            "verification_url": (
                self._extract_verification_url(
                    response
                )
            ),
            "request_payload": payload,
            "raw_response": response,
            "already_submitted": False,
        }

    def get_check_result(self, kyc):
        if not kyc.provider_check_id:
            raise KYCProviderError(
                "ComplianceAssist requestId "
                "was not found"
            )

        response = self._authenticated_request(
            method="GET",
            endpoint=(
                "requests/"
                f"{kyc.provider_check_id}"
            ),
            scope=(
                settings
                .COMPLIANCE_ASSIST_READ_SCOPE
            ),
        )

        return {
            "provider": self.name,
            "check_id": kyc.provider_check_id,
            "subject_id": response.get("subjectId"),
            "api_request_id": response.get(
                "apiRequestId"
            ),
            "status": (
                response.get("requestStatus")
                or response.get("status")
            ),
            "result": response.get("results"),
            "verification_url": (
                self._extract_verification_url(
                    response
                )
            ),
            "raw_response": response,
        }


def get_kyc_provider():
    provider_name = str(
        getattr(
            settings,
            "KYC_PROVIDER",
            "mock",
        )
        or "mock"
    ).strip().lower()

    if provider_name == "onfido":
        return OnfidoKYCProvider()

    if provider_name in [
        "complianceassist",
        "compliance_assist",
        "compliance",
    ]:
        return ComplianceAssistKYCProvider()

    return MockKYCProvider()