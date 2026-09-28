from django.contrib import admin

from .models import Holiday, NotificationOutbox, NotificationTemplate, ReminderRule


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "is_active"]


@admin.register(ReminderRule)
class ReminderRuleAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ["date", "name"]


@admin.register(NotificationOutbox)
class NotificationOutboxAdmin(admin.ModelAdmin):
    list_display = ["scheduled_for", "kind", "recipient_email", "status", "attempts", "request"]
    list_filter = ["status", "kind"]
    search_fields = ["recipient_email", "subject"]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
