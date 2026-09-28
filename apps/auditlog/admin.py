from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Viewable, never writable."""

    list_display = ["occurred_at", "actor", "action", "object_type", "object_id", "obligation_ref"]
    list_filter = ["action"]
    search_fields = ["obligation_ref", "detail", "object_id"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def get_actions(self, request):
        return {}
