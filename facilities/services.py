from dataclasses import dataclass
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import ClassSession, Department, Override, Room, TimetableUpload
from .parser import parse_pdf

FREE, BUSY, CHANGED, EMERGENCY = "free", "busy", "changed", "emergency"
PRIORITY = {EMERGENCY: 3, CHANGED: 2, BUSY: 1}


def mins(t: time) -> int:
    return t.hour * 60 + t.minute


def fmt(m: int) -> str:
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


# ---------------------------------------------------------------- import PDF
@transaction.atomic
def import_timetable(department_name, file_like, class_name="", room_name="", user=None,
                     upload_file=None):
    """Parse a PDF and replace that class's weekly sessions. Returns (ParseResult, created)."""
    department, _ = Department.objects.get_or_create(name=department_name.strip())
    result = parse_pdf(file_like, class_name=class_name.strip(), room_name=room_name.strip())
    if not result.sessions:
        return result, 0
    fallback_room = result.room or result.class_name or "Room 1"
    upload = TimetableUpload.objects.create(
        department=department, class_name=result.class_name, uploaded_by=user,
        pdf=upload_file if upload_file is not None else "")
    if result.class_name:   # re-upload replaces the old timetable of this class
        ClassSession.objects.filter(room__department=department,
                                    class_name=result.class_name).delete()
    rooms = {}
    created = 0
    for s in result.sessions:
        rname = (s["room"] or fallback_room).strip()
        if rname not in rooms:
            rooms[rname], _ = Room.objects.get_or_create(
                department=department, name=rname,
                defaults={"room_type": Room.LAB if "lab" in rname.lower() else Room.CLASSROOM})
        ClassSession.objects.create(
            room=rooms[rname], class_name=result.class_name, subject=s["subject"],
            teacher=s["teacher"], day=s["day"], start_time=s["start_time"],
            end_time=s["end_time"], source=upload)
        created += 1
    upload.sessions_created = created
    upload.save(update_fields=["sessions_created"])
    return result, created


# ---------------------------------------------------------------- live status
def _overlap(a_s, a_e, b_s, b_e):
    return a_s < b_e and b_s < a_e


def build_day(rooms, day):
    """Return {room_id: [block, ...]} for one date. Weekly timetable + overrides layered."""
    rooms = list(rooms)
    ids = [r.id for r in rooms]
    sessions = ClassSession.objects.filter(room_id__in=ids, day=day.weekday())
    overrides = Override.objects.filter(room_id__in=ids, date=day)
    s_by, o_by = {i: [] for i in ids}, {i: [] for i in ids}
    for s in sessions:
        s_by[s.room_id].append(s)
    for o in overrides:
        o_by[o.room_id].append(o)

    out = {}
    for r in rooms:
        cancels = [o for o in o_by[r.id] if o.kind == Override.CANCEL]
        blocks = []
        for s in s_by[r.id]:
            cancelled = [c for c in cancels
                         if _overlap(mins(s.start_time), mins(s.end_time),
                                     mins(c.start_time), mins(c.end_time))]
            blocks.append(dict(
                kind="cancelled" if cancelled else BUSY, start=mins(s.start_time),
                end=mins(s.end_time), title=s.subject, teacher=s.teacher,
                class_name=s.class_name,
                note=(cancelled[0].reason or "Class cancelled") if cancelled else ""))
        for o in o_by[r.id]:
            if o.kind == Override.OCCUPY:
                blocks.append(dict(kind=EMERGENCY, start=mins(o.start_time), end=mins(o.end_time),
                                   title=o.title or "Room reserved", teacher=o.teacher,
                                   class_name="", note=o.reason))
            elif o.kind == Override.EXTRA:
                blocks.append(dict(kind=CHANGED, start=mins(o.start_time), end=mins(o.end_time),
                                   title=o.title or "Extra class", teacher=o.teacher,
                                   class_name="", note=o.reason or "Rescheduled / extra class"))
        blocks.sort(key=lambda b: b["start"])
        for b in blocks:
            b["label"] = f"{fmt(b['start'])}–{fmt(b['end'])}"
        out[r.id] = blocks
    return out


def status_at(blocks, minute):
    """Status of one room at a minute-of-day, given its blocks for that date."""
    active = [b for b in blocks if b["kind"] in PRIORITY and b["start"] <= minute < b["end"]]
    if active:
        top = max(active, key=lambda b: PRIORITY[b["kind"]])
        return dict(state=top["kind"], title=top["title"], teacher=top["teacher"],
                    note=top["note"], until=fmt(top["end"]), class_name=top["class_name"])
    nxt = [b for b in blocks if b["kind"] in PRIORITY and b["start"] > minute]
    until = fmt(min(b["start"] for b in nxt)) if nxt else ""
    return dict(state=FREE, title="", teacher="", note="", until=until, class_name="")


def local_now():
    return timezone.localtime(timezone.now())
