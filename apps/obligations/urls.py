from django.urls import path

from . import views

app_name = "obligations"

urlpatterns = [
    path("", views.register, name="list"),
    path("<str:obligation_id>/", views.detail, name="detail"),
]
