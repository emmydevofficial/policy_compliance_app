from django.contrib import admin

from .models import (
    EvidenceRequest,
    ReportingPeriod,
    RequestAttachment,
    Submission,
    SubmissionAttachment,
)


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date", "is_open"]


class ReadOnlyAdmin(admin.ModelAdmin):
    """Workflow records change only through the application's services, which validate
    transitions and write the audit trail."""

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(EvidenceRequest)
class EvidenceRequestAdmin(ReadOnlyAdmin):
    list_display = ["obligation", "period", "assigned_department", "status", "due_date"]
    list_filter = ["status", "period", "assigned_department"]
    search_fields = ["obligation__obligation_id"]


@admin.register(Submission)
class SubmissionAdmin(ReadOnlyAdmin):
    list_display = ["request", "submitted_by", "submitted_at", "compliance_status", "is_current"]
    list_filter = ["compliance_status", "is_current"]


@admin.register(RequestAttachment)
class RequestAttachmentAdmin(ReadOnlyAdmin):
    list_display = ["original_filename", "request", "content_type", "size_bytes", "uploaded_at"]
    exclude = ["file"]


@admin.register(SubmissionAttachment)
class SubmissionAttachmentAdmin(ReadOnlyAdmin):
    list_display = ["original_filename", "submission", "content_type", "size_bytes", "uploaded_at"]
    exclude = ["file"]
