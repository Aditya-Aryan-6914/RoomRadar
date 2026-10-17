from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/status/", views.api_status, name="api_status"),
    path("upload/", views.upload, name="upload"),
    path("manage/", views.manage, name="manage"),
    path("manage/delete/<int:pk>/", views.delete_override, name="delete_override"),
]
