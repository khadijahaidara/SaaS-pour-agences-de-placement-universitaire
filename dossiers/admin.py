from django.contrib import admin

from .models import (
    DocumentFile, DocumentRequest, DocumentTemplate, Dossier, DossierEvent, DossierStage,
    Notification, Payment, ServiceFee, StageTemplate, WorkflowTemplate,
)


class StageTemplateInline(admin.TabularInline):
    model = StageTemplate
    extra = 0


class DocumentTemplateInline(admin.TabularInline):
    model = DocumentTemplate
    extra = 0


@admin.register(WorkflowTemplate)
class WorkflowTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "agency", "destination_country", "is_active")
    list_filter = ("agency", "is_active")
    inlines = [StageTemplateInline, DocumentTemplateInline]


class DossierStageInline(admin.TabularInline):
    model = DossierStage
    extra = 0


@admin.register(Dossier)
class DossierAdmin(admin.ModelAdmin):
    list_display = ("reference", "student", "agency", "destination_country", "status", "counselor", "last_activity_at")
    list_filter = ("agency", "status", "destination_country")
    search_fields = ("reference", "student__email", "student__last_name")
    raw_id_fields = ("student", "counselor")
    inlines = [DossierStageInline]


@admin.register(DocumentRequest)
class DocumentRequestAdmin(admin.ModelAdmin):
    list_display = ("name", "dossier", "status", "due_date")
    list_filter = ("status",)


admin.site.register([DocumentFile, ServiceFee, Payment, DossierEvent, Notification])
