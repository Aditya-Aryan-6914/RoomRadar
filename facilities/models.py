from django.conf import settings
from django.db import models

DAYS = [(0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
        (4, "Friday"), (5, "Saturday"), (6, "Sunday")]


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Room(models.Model):
    CLASSROOM, LAB, OTHER = "classroom", "lab", "other"
    TYPES = [(CLASSROOM, "Classroom"), (LAB, "Lab"), (OTHER, "Seminar / Other")]

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=60)
    room_type = models.CharField(max_length=10, choices=TYPES, default=CLASSROOM)
    capacity = models.PositiveIntegerField(default=60)

    class Meta:
        ordering = ["department__name", "name"]
        unique_together = [("department", "name")]

    def __str__(self):
        return f"{self.name} ({self.department})"


class TimetableUpload(models.Model):
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    class_name = models.CharField(max_length=60, blank=True)
    pdf = models.FileField(upload_to="timetables/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL)
    sessions_created = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.department} {self.class_name} @ {self.uploaded_at:%Y-%m-%d %H:%M}"


class ClassSession(models.Model):
    """One weekly recurring lecture / lab slot (comes from the timetable PDF)."""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="sessions")
    class_name = models.CharField(max_length=60, blank=True)
    subject = models.CharField(max_length=150)
    teacher = models.CharField(max_length=100, blank=True)
    day = models.PositiveSmallIntegerField(choices=DAYS)
    start_time = models.TimeField()
    end_time = models.TimeField()
    source = models.ForeignKey(TimetableUpload, null=True, blank=True, on_delete=models.CASCADE,
                               related_name="sessions")

    class Meta:
        ordering = ["day", "start_time"]

    def __str__(self):
        return f"{self.subject} · {self.room.name} · {self.get_day_display()} {self.start_time:%H:%M}"


class Override(models.Model):
    """One-off change on a specific date, layered on top of the weekly timetable."""
    CANCEL, OCCUPY, EXTRA = "cancel", "occupy", "extra"
    KINDS = [
        (CANCEL, "Class cancelled / room released (becomes free)"),
        (OCCUPY, "Emergency / event occupancy (room blocked)"),
        (EXTRA, "Extra or rescheduled class (room used)"),
    ]

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="overrides")
    kind = models.CharField(max_length=10, choices=KINDS)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    title = models.CharField(max_length=150, blank=True, help_text="Subject or event name")
    teacher = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.room.name} · {self.date} {self.start_time:%H:%M}"
