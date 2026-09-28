from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("sign-in/", views.LoginView.as_view(), name="login"),
    path("sign-out/", views.LogoutView.as_view(), name="logout"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path("password/done/", views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("password/reset/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/reset/sent/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "password/reset/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password/reset/complete/",
        views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path("activate/<str:token>/", views.activate, name="activate"),
]
