from django.contrib import admin
from .models import ClassSession, Department, Override, Room, TimetableUpload

admin.site.register(Department)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "room_type", "capacity")
    list_filter = ("department", "room_type")
    search_fields = ("name",)


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ("subject", "class_name", "teacher", "room", "day", "start_time", "end_time")
    list_filter = ("room__department", "day", "class_name")
    search_fields = ("subject", "teacher")


@admin.register(Override)
class OverrideAdmin(admin.ModelAdmin):
    list_display = ("room", "kind", "date", "start_time", "end_time", "title", "reason")
    list_filter = ("kind", "date")


@admin.register(TimetableUpload)
class TimetableUploadAdmin(admin.ModelAdmin):
    list_display = ("department", "class_name", "uploaded_at", "sessions_created")
