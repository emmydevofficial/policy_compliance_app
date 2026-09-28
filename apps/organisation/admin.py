from django.contrib import admin

from .models import Department


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "gm", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False  # soft delete only
