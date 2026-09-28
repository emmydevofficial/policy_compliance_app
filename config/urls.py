from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import home
from apps.auditlog import views as audit_views
from apps.notifications import views as notice_views
from apps.organisation import views as org_views
from apps.reporting.urls import dashboard_patterns, reports_patterns
from apps.workflow import periods
from apps.workflow.urls import my_patterns, requests_patterns

admin_area_patterns = (
    [
        path("departments/", org_views.departments, name="departments"),
        path("departments/new/", org_views.department_edit, name="department_create"),
        path("departments/<int:pk>/", org_views.department_edit, name="department_edit"),
        path(
            "departments/<int:pk>/deactivate/",
            org_views.department_deactivate,
            name="department_deactivate",
        ),
        path(
            "departments/<int:pk>/reactivate/",
            org_views.department_reactivate,
            name="department_reactivate",
        ),
        path("people/", org_views.people, name="people"),
        path("people/new/", org_views.person_edit, name="person_create"),
        path("people/import/", org_views.people_import, name="people_import"),
        path("people/<int:pk>/", org_views.person_edit, name="person_edit"),
        path("people/<int:pk>/deactivate/", org_views.person_deactivate, name="person_deactivate"),
        path("people/<int:pk>/reactivate/", org_views.person_reactivate, name="person_reactivate"),
        path("people/<int:pk>/invite/", org_views.person_invite, name="person_invite"),
        path("reminders/", notice_views.reminders, name="reminders"),
        path("reminders/holidays/", notice_views.holiday_add, name="holiday_add"),
        path(
            "reminders/holidays/<int:pk>/remove/",
            notice_views.holiday_remove,
            name="holiday_remove",
        ),
        path("templates/", notice_views.templates, name="templates"),
        path("templates/<int:pk>/", notice_views.template_edit, name="template_edit"),
        path("templates/<int:pk>/preview/", notice_views.template_preview, name="template_preview"),
        path("periods/", periods.periods, name="periods"),
        path("periods/<int:pk>/toggle/", periods.period_toggle, name="period_toggle"),
        path("audit/", audit_views.audit, name="audit"),
    ],
    "admin_area",
)

urlpatterns = [
    path("", home, name="home"),
    path("accounts/", include("apps.accounts.urls")),
    path("register/", include("apps.obligations.urls")),
    path("requests/", include(requests_patterns)),
    path("my/", include(my_patterns)),
    path("dashboard/", include(dashboard_patterns)),
    path("reports/", include(reports_patterns)),
    path("manage/", include(admin_area_patterns)),
    path("django-admin/", admin.site.urls),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
