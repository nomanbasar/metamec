from django.contrib import admin

from .models import LoanType, LoanTemplate, LoanTemplateSection


class LoanTemplateSectionInline(admin.TabularInline):
    model = LoanTemplateSection
    extra = 0
    fields = ("title", "description", "order")
    ordering = ("order",)


@admin.register(LoanTemplate)
class LoanTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "sections_count",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("name", "description")
    inlines = [LoanTemplateSectionInline]

    def sections_count(self, obj):
        return obj.sections.count()


@admin.register(LoanTemplateSection)
class LoanTemplateSectionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "template",
        "title",
        "order",
        "updated_at",
    )
    list_filter = ("template",)
    search_fields = ("title", "description", "template__name")
    ordering = ("template", "order")


@admin.register(LoanType)
class LoanTypeAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "template",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "template")
    search_fields = ("name", "description", "template__name")