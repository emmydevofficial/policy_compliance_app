from django.contrib import admin

from .models import Obligation, RegulatoryInstrument


@admin.register(RegulatoryInstrument)
class RegulatoryInstrumentAdmin(admin.ModelAdmin):
    list_display = ["name", "short_code", "citation", "is_active"]


@admin.register(Obligation)
class ObligationAdmin(admin.ModelAdmin):
    list_display = ["obligation_id", "instrument", "primary_department", "risk_level", "is_active"]
    list_filter = ["instrument", "risk_level", "is_active"]
    search_fields = ["obligation_id", "description", "category", "document_reference"]
    filter_horizontal = ["supporting_departments"]

    def has_delete_permission(self, request, obj=None) -> bool:
        return False  # versioned by is_active, never deleted
