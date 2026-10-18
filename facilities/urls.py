from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("join/", views.student_signup, name="student_signup"),
    path("student/login/", views.student_login, name="student_login"),
    path("go/", views.my_campus, name="my_campus"),
    path("c/<slug:slug>/", views.dashboard, name="dashboard"),
    path("c/<slug:slug>/unlock/", views.unlock, name="unlock"),
    path("c/<slug:slug>/access/", views.access, name="access"),
    path("c/<slug:slug>/access/student/<int:pk>/remove/", views.remove_student, name="remove_student"),
    path("c/<slug:slug>/api/status/", views.api_status, name="api_status"),
    path("c/<slug:slug>/book/", views.book, name="book"),
    path("c/<slug:slug>/upload/", views.upload, name="upload"),
    path("c/<slug:slug>/upload/<int:pk>/delete/", views.delete_upload, name="delete_upload"),
    path("c/<slug:slug>/changes/", views.manage, name="manage"),
    path("c/<slug:slug>/changes/<int:pk>/delete/", views.delete_override, name="delete_override"),
]
