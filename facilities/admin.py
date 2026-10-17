from django.contrib import admin

from .models import ClassSession, Department, Institute, Override, Room, TimetableUpload

admin.site.register([Institute, Department, Room, ClassSession, Override, TimetableUpload])
