from django.urls import path

from apps.accounts.views import my_settings

from . import views

requests_patterns = (
    [
        path("", views.request_list, name="list"),
        path("new/", views.request_create, name="create"),
        path("new/obligations/", views.request_picker, name="picker"),
        path("new/preview/", views.request_preview, name="preview"),
        path("officers/", views.officers_options, name="officers"),
        path("verify/", views.verify_queue, name="verify_queue"),
        path("overdue/", views.overdue, name="overdue"),
        path("<int:pk>/", views.request_detail, name="detail"),
        path("<int:pk>/issue/", views.request_issue, name="issue"),
        path("<int:pk>/deadline/", views.request_deadline, name="deadline"),
        path("<int:pk>/reassign/", views.request_reassign, name="reassign"),
        path("<int:pk>/close/", views.request_close_na, name="close_na"),
        path("<int:pk>/attach/", views.request_attach, name="attach"),
        path("submissions/<int:pk>/verify/", views.verify_submission, name="verify"),
        path(
            "files/request/<int:pk>/", views.request_attachment_download, name="attachment_download"
        ),
        path(
            "files/evidence/<int:pk>/",
            views.submission_attachment_download,
            name="evidence_download",
        ),
    ],
    "requests",
)

my_patterns = (
    [
        path("", views.inbox, name="inbox"),
        path("requests/<int:pk>/", views.submit, name="submit"),
        path("history/", views.history, name="history"),
        path("settings/", my_settings, name="settings"),
    ],
    "my",
)
