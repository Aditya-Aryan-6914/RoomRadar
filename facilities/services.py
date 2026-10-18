import json
from datetime import time

from django.db import transaction
from django.utils import timezone

from .models import ClassSession, Department, Override, Room, TimetableUpload
from .parser import parse_pdf

FREE, BUSY, CHANGED, EMERGENCY, BOOKED = "free", "busy", "changed", "emergency", "booked"
PRIORITY = {EMERGENCY: 4, CHANGED: 3, BOOKED: 2, BUSY: 1}
STATE_TEXT = {FREE: "Free", BUSY: "In class", CHANGED: "Extra class",
              EMERGENCY: "Reserved", BOOKED: "Booked"}


def mins(t: time) -> int:
    return t.hour * 60 + t.minute


def fmt(m: int) -> str:
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def local_now():
    return timezone.localtime(timezone.now())


# ---------------------------------------------------------------- import PDF
def cleanup_empty(institute):
    """Drop rooms/departments that no longer have any timetable data."""
    # a room only exists while some timetable defines it (its bookings/changes go with it)
    Room.objects.filter(department__institute=institute, sessions__isnull=True).delete()
    Department.objects.filter(institute=institute, rooms__isnull=True).delete()


@transaction.atomic
def import_timetable(institute, file_like, default_department="", class_name="", room_name="",
                     filename="", upload_file=None):
    """Parse a PDF. Every division found becomes one class; its home room is created from the
    PDF. Re-uploading a division replaces its old weekly timetable. Returns (result, groups)."""
    result = parse_pdf(file_like, class_name=class_name.strip(), room_name=room_name.strip(),
                       department=default_department.strip())
    if not result.sessions:
        return result, []
    missing = [s for s in result.sessions if not s["department"]]
    if missing:
        result.warnings.append("No department name found in the PDF - type it in the upload form.")
        return result, []

    upload = TimetableUpload.objects.create(
        institute=institute, filename=filename, pdf=upload_file if upload_file is not None else "",
        parsed_json=json.dumps(result.data, ensure_ascii=False, indent=2) if result.data else "")
    result.upload_id = upload.pk
    groups = {}
    for s in result.sessions:
        groups.setdefault((s["department"], s["class_name"]), []).append(s)

    summary, total, out = [], 0, []
    room_cache, seen = {}, set()
    for (dname, cname), items in groups.items():
        dept, _ = Department.objects.get_or_create(institute=institute, name=dname)
        ClassSession.objects.filter(room__department=dept, class_name=cname).delete()
        home = (items[0]["home_room"] or f"{cname} Room").strip()
        rooms_used = set()
        for s in items:
            rname = (s["room"] or home).strip()
            key = (dept.id, rname)
            if key not in room_cache:
                room_cache[key], _ = Room.objects.get_or_create(
                    department=dept, name=rname,
                    defaults={"room_type": Room.LAB if "lab" in rname.lower() else Room.CLASSROOM})
            # a shared elective appears on several class pages: store it once
            ident = (key, s["day"], s["start_time"], s["end_time"], s["subject"], s["teacher"],
                     s.get("batch", ""))
            if ident in seen:
                continue
            seen.add(ident)
            ClassSession.objects.create(
                room=room_cache[key], class_name=cname, year=s.get("year", ""),
                batch=s.get("batch", ""), subject=s["subject"], teacher=s["teacher"],
                day=s["day"], start_time=s["start_time"], end_time=s["end_time"], source=upload)
            rooms_used.add(rname)
        total += len(items)
        out.append(dict(department=dname, class_name=cname, room=home, sessions=len(items),
                        year=items[0].get("year", ""),
                        rooms=sorted(rooms_used)))
        summary.append(f"{dname}: {cname}")
    upload.sessions_created = total
    upload.summary = "; ".join(summary)[:300]
    upload.save(update_fields=["sessions_created", "summary"])
    cleanup_empty(institute)
    return result, out


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
                class_name=s.class_name, year=s.year, batch=s.batch,
                note=(cancelled[0].reason or "Class cancelled") if cancelled else ""))
        for o in o_by[r.id]:
            kind = {Override.OCCUPY: EMERGENCY, Override.EXTRA: CHANGED,
                    Override.BOOKING: BOOKED}.get(o.kind)
            if not kind:
                continue
            default = {EMERGENCY: "Room reserved", CHANGED: "Extra class", BOOKED: "Group session"}[kind]
            who = o.teacher + (f" ({o.get_role_display()})" if o.role else "")
            blocks.append(dict(kind=kind, start=mins(o.start_time), end=mins(o.end_time),
                               title=o.title or default, teacher=who.strip(), class_name="",
                               year="", batch="", note=o.reason, override_id=o.id))
        blocks.sort(key=lambda b: b["start"])
        for b in blocks:
            b["label"] = f"{fmt(b['start'])}–{fmt(b['end'])}"
        out[r.id] = blocks
    return out


def status_at(blocks, minute):
    active = [b for b in blocks if b["kind"] in PRIORITY and b["start"] <= minute < b["end"]]
    if active:
        top = max(active, key=lambda b: PRIORITY[b["kind"]])
        return dict(state=top["kind"], title=top["title"], teacher=top["teacher"],
                    note=top["note"], until=fmt(top["end"]), class_name=top["class_name"],
                    year=top.get("year", ""), batch=top.get("batch", ""))
    nxt = [b for b in blocks if b["kind"] in PRIORITY and b["start"] > minute]
    until = fmt(min(b["start"] for b in nxt)) if nxt else ""
    return dict(state=FREE, title="", teacher="", note="", until=until, class_name="",
                year="", batch="")


def room_conflict(room, day, start, end):
    """First block that makes `room` unavailable in [start, end) on `day`, or None."""
    for b in build_day([room], day)[room.id]:
        if b["kind"] in PRIORITY and _overlap(b["start"], b["end"], mins(start), mins(end)):
            return b
    return None
