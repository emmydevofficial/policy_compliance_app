from django.urls import path

from . import views

dashboard_patterns = (
    [
        path("", views.admin_dashboard, name="admin"),
        path("executive/", views.executive_dashboard, name="executive"),
    ],
    "dashboard",
)

reports_patterns = (
    [
        path("", views.index, name="index"),
        path("preview/", views.preview, name="preview"),
        path("register.xlsx", views.register_xlsx, name="register_xlsx"),
        path("tracker.xlsx", views.tracker_xlsx, name="tracker_xlsx"),
        path("report.pdf", views.report_pdf, name="report_pdf"),
        path("pack.zip", views.submission_pack, name="pack_zip"),
    ],
    "reports",
)
