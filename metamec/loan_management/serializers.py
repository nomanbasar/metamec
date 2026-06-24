from rest_framework import serializers
from .models import LoanType, LoanTemplate, LoanTemplateSection


def file_relative_url(file_field):
    if not file_field:
        return None

    try:
        return file_field.url
    except Exception:
        return None


class LoanTemplateMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanTemplate
        fields = ("id", "name", "status")


class LoanTemplateDropdownSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanTemplate
        fields = ("id", "name")


class LoanTypeSerializer(serializers.ModelSerializer):
    templateId = serializers.PrimaryKeyRelatedField(
        source="template",
        queryset=LoanTemplate.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    iconImage = serializers.FileField(
        source="icon_image",
        write_only=True,
        required=False,
        allow_null=True,
    )

    iconImageUrl = serializers.SerializerMethodField()

    isActive = serializers.BooleanField(source="is_active", required=False)
    assignedTemplate = LoanTemplateMiniSerializer(source="template", read_only=True)

    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = LoanType
        fields = (
            "id",
            "name",
            "iconImage",
            "iconImageUrl",
            "description",
            "templateId",
            "isActive",
            "assignedTemplate",
            "createdAt",
            "updatedAt",
        )

    def get_iconImageUrl(self, obj):
        return file_relative_url(obj.icon_image)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Loan type name is required.")
        return value

    def validate(self, attrs):
        template = attrs.get("template")

        if template and template.status != LoanTemplate.STATUS_PUBLISHED:
            raise serializers.ValidationError({
                "templateId": "Only published templates can be assigned to loan type."
            })

        return attrs


class CustomerLoanTypeSerializer(serializers.ModelSerializer):
    iconImageUrl = serializers.SerializerMethodField()

    class Meta:
        model = LoanType
        fields = ("id", "name", "iconImageUrl", "description")

    def get_iconImageUrl(self, obj):
        return file_relative_url(obj.icon_image)


class LoanTemplateListSerializer(serializers.ModelSerializer):
    sectionsCount = serializers.IntegerField(source="sections_count", read_only=True)
    lastUpdated = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = LoanTemplate
        fields = (
            "id",
            "name",
            "description",
            "status",
            "sectionsCount",
            "lastUpdated",
        )


class LoanTemplateCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanTemplate
        fields = (
            "id",
            "name",
            "description",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Template name is required.")
        return value


class LoanTemplateSectionSerializer(serializers.ModelSerializer):
    templateId = serializers.UUIDField(source="template_id", read_only=True)

    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = LoanTemplateSection
        fields = (
            "id",
            "templateId",
            "title",
            "description",
            "order",
            "createdAt",
            "updatedAt",
        )
        read_only_fields = (
            "id",
            "templateId",
            "order",
            "createdAt",
            "updatedAt",
        )

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Section title is required.")
        return value

    def validate_description(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Section description is required.")
        return value


class LoanTemplateDetailSerializer(serializers.ModelSerializer):
    sectionsCount = serializers.IntegerField(source="sections_count", read_only=True)
    sections = LoanTemplateSectionSerializer(many=True, read_only=True)

    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = LoanTemplate
        fields = (
            "id",
            "name",
            "description",
            "status",
            "sectionsCount",
            "sections",
            "createdAt",
            "updatedAt",
        )