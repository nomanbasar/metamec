from rest_framework import serializers

from .models import LoanApplicationDocument


class LoanApplicationDocumentSerializer(serializers.ModelSerializer):
    documentType = serializers.CharField(source="document_type", read_only=True)
    documentTitle = serializers.SerializerMethodField()

    fileUrl = serializers.SerializerMethodField()
    originalFileName = serializers.CharField(source="original_file_name", read_only=True)
    fileSize = serializers.IntegerField(source="file_size", read_only=True)
    mimeType = serializers.CharField(source="mime_type", read_only=True)

    uploadedAt = serializers.DateTimeField(source="uploaded_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = LoanApplicationDocument
        fields = (
            "id",
            "documentType",
            "documentTitle",
            "fileUrl",
            "originalFileName",
            "fileSize",
            "mimeType",
            "status",
            "uploadedAt",
            "updatedAt",
        )

    def get_documentTitle(self, obj):
        return obj.get_document_type_display()

    def get_fileUrl(self, obj):
        if obj.file:
            return obj.file.url
        return None