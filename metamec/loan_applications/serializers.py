import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from rest_framework import serializers

from loan_management.models import LoanType, LoanTemplate
from loan_management.serializers import CustomerLoanTypeSerializer

from .models import LoanApplication


class LoanApplicationSerializer(serializers.ModelSerializer):
    loanTypeId = serializers.PrimaryKeyRelatedField(
        source="loan_type",
        queryset=LoanType.objects.all(),
        write_only=True,
        required=False,
    )

    loanType = serializers.SerializerMethodField()
    applicationNumber = serializers.CharField(source="application_number", read_only=True)

    loanAmount = serializers.DecimalField(
        source="loan_amount",
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    loanTerm = serializers.CharField(
        source="loan_term",
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    propertyValue = serializers.DecimalField(
        source="property_value",
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    mortgageBalance = serializers.DecimalField(
        source="mortgage_balance",
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    mortgagePayment = serializers.DecimalField(
        source="mortgage_payment",
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    mortgageLender = serializers.CharField(
        source="mortgage_lender",
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    termRemaining = serializers.CharField(
        source="term_remaining",
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    interestRate = serializers.CharField(
        source="interest_rate",
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    employmentType = serializers.CharField(
        source="employment_type",
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    annualIncome = serializers.DecimalField(
        source="annual_income",
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    hasCcj = serializers.BooleanField(source="has_ccj", required=False, allow_null=True)
    hasDefaults = serializers.BooleanField(source="has_defaults", required=False, allow_null=True)
    hasActiveDmp = serializers.BooleanField(source="has_active_dmp", required=False, allow_null=True)
    hasActiveIva = serializers.BooleanField(source="has_active_iva", required=False, allow_null=True)

    currentStep = serializers.IntegerField(source="current_step", required=False)

    totalSteps = serializers.SerializerMethodField()
    progressPercent = serializers.SerializerMethodField()

    estimatedRate = serializers.SerializerMethodField()
    estimatedMonthlyPayment = serializers.SerializerMethodField()
    dtiRatio = serializers.SerializerMethodField()
    dtiRatioDisplay = serializers.SerializerMethodField()
    employmentDisplay = serializers.SerializerMethodField()

    documentsSummary = serializers.SerializerMethodField()
    reviewSummary = serializers.SerializerMethodField()

    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    actions = serializers.SerializerMethodField()

    class Meta:
        model = LoanApplication
        fields = (
            "id",
            "applicationNumber",
            "loanTypeId",
            "loanType",

            "loanAmount",
            "loanTerm",
            "notes",

            "propertyValue",
            "mortgageBalance",
            "mortgagePayment",
            "mortgageLender",
            "termRemaining",
            "interestRate",

            "employmentType",
            "employmentDisplay",
            "annualIncome",

            "hasCcj",
            "hasDefaults",
            "hasActiveDmp",
            "hasActiveIva",

            "status",
            "currentStep",
            "totalSteps",
            "progressPercent",

            "estimatedRate",
            "estimatedMonthlyPayment",
            "dtiRatio",
            "dtiRatioDisplay",
            "documentsSummary",
            "reviewSummary",

            "submittedAt",
            "createdAt",
            "updatedAt",
            "actions",
        )
        read_only_fields = (
            "id",
            "applicationNumber",
            "loanType",
            "status",
            "submittedAt",
            "createdAt",
            "updatedAt",
            "actions",
        )

    def get_loanType(self, obj):
        return CustomerLoanTypeSerializer(obj.loan_type).data

    def get_totalSteps(self, obj):
        return LoanApplication.TOTAL_STEPS

    def get_progressPercent(self, obj):
        return obj.progress_percent

    def get_estimatedRate(self, obj):
        if obj.interest_rate:
            text = str(obj.interest_rate).strip()

            if "apr" in text.lower():
                return text

            if "%" in text:
                return f"{text} APR"

            return f"{text}% APR"

        return "9.5% APR"

    def get_estimatedMonthlyPayment(self, obj):
        if not obj.loan_amount:
            return None

        months = self._extract_months(obj.loan_term)

        if not months:
            return None

        principal = Decimal(obj.loan_amount)
        annual_rate = self._extract_rate_decimal(self.get_estimatedRate(obj))

        if annual_rate is None or annual_rate <= 0:
            monthly_payment = principal / Decimal(months)
        else:
            monthly_rate = annual_rate / Decimal("100") / Decimal("12")
            factor = (Decimal("1") + monthly_rate) ** months
            monthly_payment = principal * monthly_rate * factor / (factor - Decimal("1"))

        monthly_payment = monthly_payment.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return str(monthly_payment)

    def get_dtiRatio(self, obj):
        ratio = self._calculate_dti(obj)

        if ratio is None:
            return None

        return float(ratio)

    def get_dtiRatioDisplay(self, obj):
        ratio = self._calculate_dti(obj)

        if ratio is None:
            return None

        return f"{ratio}%"

    def get_employmentDisplay(self, obj):
        mapping = {
            "employed": "Full-time Employee",
            "self_employed": "Self-employed",
            "other": "Other",
            "full_time": "Full-time Employee",
            "part_time": "Part-time Employee",
            "contract": "Contract",
        }

        return mapping.get(obj.employment_type, obj.employment_type)

    def get_documentsSummary(self, obj):
        required_count = 5

        uploaded_count = 0

        try:
            uploaded_count = obj.documents.count()
        except Exception:
            uploaded_count = 0

        remaining_count = max(required_count - uploaded_count, 0)
        progress_percent = int(round((uploaded_count / required_count) * 100)) if required_count else 0

        return {
            "requiredCount": required_count,
            "uploadedCount": uploaded_count,
            "remainingCount": remaining_count,
            "progressPercent": progress_percent,
            "uploadedText": f"{uploaded_count}/{required_count} uploaded",
            "statusText": f"{remaining_count} required remaining",
        }

    def get_reviewSummary(self, obj):
        return {
            "loanType": obj.loan_type.name if obj.loan_type else None,
            "loanAmount": str(obj.loan_amount) if obj.loan_amount is not None else None,
            "loanTerm": obj.loan_term,
            "estimatedRate": self.get_estimatedRate(obj),
            "estimatedMonthlyPayment": self.get_estimatedMonthlyPayment(obj),
            "employment": self.get_employmentDisplay(obj),
            "annualIncome": str(obj.annual_income) if obj.annual_income is not None else None,
            "dtiRatio": self.get_dtiRatio(obj),
            "dtiRatioDisplay": self.get_dtiRatioDisplay(obj),
            "documents": self.get_documentsSummary(obj),
        }

    def get_actions(self, obj):
        return {
            "canEdit": obj.status == LoanApplication.STATUS_DRAFT,
            "canSubmit": obj.status == LoanApplication.STATUS_DRAFT,
            "canUploadDocuments": obj.status in [
                LoanApplication.STATUS_SUBMITTED,
                LoanApplication.STATUS_UNDER_REVIEW,
                LoanApplication.STATUS_PENDING_DOCUMENTS,
                LoanApplication.STATUS_KYC_REQUIRED,
                LoanApplication.STATUS_APPROVED,
            ],
            "canViewMyLoan": obj.status != LoanApplication.STATUS_DRAFT,
        }

    def _extract_months(self, loan_term):
        if not loan_term:
            return None

        text = str(loan_term).lower()
        numbers = re.findall(r"\d+", text)

        if not numbers:
            return None

        number = int(numbers[0])

        if "year" in text or "yr" in text:
            return number * 12

        return number

    def _extract_rate_decimal(self, rate_text):
        if not rate_text:
            return None

        try:
            clean = str(rate_text).lower().replace("apr", "").replace("%", "").strip()
            return Decimal(clean)
        except (InvalidOperation, ValueError):
            return None

    def _calculate_dti(self, obj):
        if not obj.annual_income:
            return None

        annual_income = Decimal(obj.annual_income)

        if annual_income <= 0:
            return None

        monthly_income = annual_income / Decimal("12")
        monthly_debt = Decimal("0")

        if obj.mortgage_payment:
            monthly_debt += Decimal(obj.mortgage_payment)

        estimated_payment = self.get_estimatedMonthlyPayment(obj)

        if estimated_payment:
            monthly_debt += Decimal(estimated_payment)

        if monthly_debt <= 0:
            return None

        ratio = (monthly_debt / monthly_income) * Decimal("100")
        return ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def validate_currentStep(self, value):
        if value < 1 or value > LoanApplication.TOTAL_STEPS:
            raise serializers.ValidationError("Current step must be between 1 and 6.")

        return value

    def validate_employmentType(self, value):
        if not value:
            return value

        allowed = [
            LoanApplication.EMPLOYMENT_EMPLOYED,
            LoanApplication.EMPLOYMENT_SELF_EMPLOYED,
            LoanApplication.EMPLOYMENT_OTHER,
            "full_time",
            "part_time",
            "contract",
        ]

        if value not in allowed:
            raise serializers.ValidationError(
                "Invalid employment type. Use employed, self_employed, other, full_time, part_time, or contract."
            )

        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("loan_type"):
            raise serializers.ValidationError({
                "loanTypeId": "This field is required."
            })

        loan_type = attrs.get("loan_type")

        if loan_type:
            if not loan_type.is_active:
                raise serializers.ValidationError({
                    "loanTypeId": "This loan type is not active."
                })

            if loan_type.template and loan_type.template.status != LoanTemplate.STATUS_PUBLISHED:
                raise serializers.ValidationError({
                    "loanTypeId": "This loan type is not available for application."
                })

        return attrs


class MyLoanListSerializer(serializers.ModelSerializer):
    applicationNumber = serializers.CharField(source="application_number", read_only=True)
    loanType = serializers.CharField(source="loan_type.name", read_only=True)
    iconImageUrl = serializers.SerializerMethodField()

    loanAmount = serializers.DecimalField(source="loan_amount", max_digits=14, decimal_places=2, read_only=True)
    loanTerm = serializers.CharField(source="loan_term", read_only=True)

    estimatedRate = serializers.SerializerMethodField()
    estimatedMonthlyPayment = serializers.SerializerMethodField()

    progressPercent = serializers.SerializerMethodField()
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = LoanApplication
        fields = (
            "id",
            "applicationNumber",
            "loanType",
            "iconImageUrl",
            "loanAmount",
            "loanTerm",
            "estimatedRate",
            "estimatedMonthlyPayment",
            "status",
            "progressPercent",
            "submittedAt",
            "createdAt",
        )

    def get_iconImageUrl(self, obj):
        if obj.loan_type and obj.loan_type.icon_image:
            return obj.loan_type.icon_image.url
        return None

    def get_progressPercent(self, obj):
        return obj.progress_percent

    def get_estimatedRate(self, obj):
        return LoanApplicationSerializer().get_estimatedRate(obj)

    def get_estimatedMonthlyPayment(self, obj):
        return LoanApplicationSerializer().get_estimatedMonthlyPayment(obj)