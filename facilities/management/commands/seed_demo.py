from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from facilities.models import Department, Room
from facilities.services import import_timetable

DEMO = [
    ("Computer Engineering", "CSE_SE-A_timetable.pdf"),
    ("Electronics", "ECE_TE-B_timetable.pdf"),
    ("Mechanical", "MECH_SE-C_timetable.pdf"),
]


class Command(BaseCommand):
    help = "Load demo timetables from /samples and create a demo staff user (admin / admin123)."

    def handle(self, *args, **opts):
        for dept, fname in DEMO:
            path = Path(settings.BASE_DIR) / "samples" / fname
            with open(path, "rb") as fh:
                res, n = import_timetable(dept, fh)
            self.stdout.write(f"{dept}: {n} slots from {fname} (class {res.class_name}, room {res.room})")
        cse = Department.objects.get(name="Computer Engineering")
        Room.objects.get_or_create(department=cse, name="Seminar Hall",
                                   defaults={"room_type": Room.OTHER, "capacity": 120})
        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@example.com", "admin123")
            self.stdout.write("Created demo staff user: admin / admin123  (change it!)")
