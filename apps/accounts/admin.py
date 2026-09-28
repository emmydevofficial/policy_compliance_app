from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Invitation, NotificationPreference, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["full_name"]
    list_display = ["full_name", "email", "role", "department", "is_department_gm", "is_active"]
    list_filter = ["role", "is_active", "is_department_gm", "department"]
    search_fields = ["full_name", "email"]
    readonly_fields = ["last_login", "last_login_ip", "created_at", "updated_at"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Person", {"fields": ["full_name", "job_title", "phone"]}),
        ("Role", {"fields": ["role", "department", "is_department_gm", "is_active"]}),
        ("Delegation", {"fields": ["delegate_to", "delegate_from", "delegate_until"]}),
        ("Technical", {"fields": ["is_staff", "is_superuser", "last_login", "last_login_ip"]}),
    ]
    add_fieldsets = [
        (None, {"fields": ["email", "full_name", "role", "department", "password1", "password2"]})
    ]
    filter_horizontal = []


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "new_request", "deadline_reminders", "outcome_notices", "weekly_digest"]


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["user", "created_at", "expires_at", "used_at"]
    readonly_fields = ["user", "token_hash", "created_at", "expires_at", "used_at", "created_by"]
