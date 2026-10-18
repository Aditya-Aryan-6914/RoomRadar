from datetime import time, timedelta

from django.db import transaction
from django.utils import timezone

from .models import (ClassSession, Department, Notification, Override, Room, RoomState,
                     StudentProfile, TimetableUpload)
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

    upload = TimetableUpload.objects.create(institute=institute, filename=filename,
                                            pdf=upload_file if upload_file is not None else "")
    groups = {}
    for s in result.sessions:
        groups.setdefault((s["department"], s["class_name"]), []).append(s)

    summary, total, out = [], 0, []
    room_cache = {}
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
            ClassSession.objects.create(
                room=room_cache[key], class_name=cname, subject=s["subject"], teacher=s["teacher"],
                day=s["day"], start_time=s["start_time"], end_time=s["end_time"], source=upload)
            rooms_used.add(rname)
        total += len(items)
        out.append(dict(department=dname, class_name=cname, room=home, sessions=len(items),
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
                class_name=s.class_name,
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
                               note=o.reason, override_id=o.id))
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
                    note=top["note"], until=fmt(top["end"]), class_name=top["class_name"])
    nxt = [b for b in blocks if b["kind"] in PRIORITY and b["start"] > minute]
    until = fmt(min(b["start"] for b in nxt)) if nxt else ""
    return dict(state=FREE, title="", teacher="", note="", until=until, class_name="")


def room_conflict(room, day, start, end, ignore_id=None):
    """First block that makes `room` unavailable in [start, end) on `day`, or None."""
    for b in build_day([room], day)[room.id]:
        if ignore_id and b.get("override_id") == ignore_id:
            continue
        if b["kind"] in PRIORITY and _overlap(b["start"], b["end"], mins(start), mins(end)):
            return b
    return None


# ---------------------------------------------------------------- notifications
def notify_members(inst, kind, title, body="", room=None, exclude=None):
    """One notification per member (owner + students), except the person who caused it."""
    ids = {inst.owner_id, *StudentProfile.objects.filter(institute=inst).values_list("user_id", flat=True)}
    ids.discard(getattr(exclude, "id", None))
    Notification.objects.bulk_create([Notification(user_id=u, institute=inst, room=room, kind=kind,
                                                   title=title, body=body) for u in ids])


def announce_override(inst, o, actor=None):
    """Alert members about a cancellation / booking / extra class / emergency block."""
    when = f"{o.date:%d %b}, {o.start_time:%H:%M}-{o.end_time:%H:%M}"
    name = o.room.name
    if o.kind == Override.CANCEL:
        what = o.title or "Class"
        notify_members(inst, Notification.CANCELLED, f"Class cancelled · {name}",
                       f"{what} ({when}) is cancelled. The room is free.", o.room, actor)
    elif o.kind == Override.BOOKING:
        who = f" by {o.teacher}" if o.teacher else ""
        notify_members(inst, Notification.BOOKED, f"New session booked · {name}",
                       f"{o.title}{who}, {when}.", o.room, actor)
    elif o.kind == Override.EXTRA:
        notify_members(inst, Notification.EXTRA, f"Extra class added · {name}",
                       f"{o.title or 'Extra class'}, {when}.", o.room, actor)
    else:
        notify_members(inst, Notification.RESERVED, f"Room reserved · {name}",
                       f"{o.reason or o.title or 'Reserved'}, {when}.", o.room, actor)
    sync_room_states(inst, notify=False)   # do not also announce 'free'/'busy' for this change


def _when(o):
    return f"{o.date:%d %b}, {o.start_time:%H:%M}-{o.end_time:%H:%M}"


def snapshot(o):
    """Remember what an override looked like before it is edited or deleted."""
    return dict(kind=o.kind, room=o.room, title=o.title, where=f"{o.room.name} · {_when(o)}")


_LABEL = {Override.BOOKING: "Booking", Override.EXTRA: "Extra class",
          Override.CANCEL: "Cancellation", Override.OCCUPY: "Reservation"}


def announce_update(inst, o, old, actor=None):
    """An existing booking / change was edited."""
    new = f"{o.room.name} · {_when(o)}"
    what = o.title or _LABEL[o.kind]
    body = f"{what}: {old['where']} → {new}." if old["where"] != new else f"{what} ({new}): details updated."
    notify_members(inst, Notification.UPDATED, f"{_LABEL[o.kind]} updated · {o.room.name}", body, o.room, actor)
    sync_room_states(inst, notify=False)


def announce_removed(inst, old, actor=None):
    """A booking / change was deleted."""
    what = old["title"] or _LABEL[old["kind"]]
    title, body = {
        Override.BOOKING: ("Booking cancelled", f"{what} ({old['where']}) was cancelled. The room is available again."),
        Override.CANCEL: ("Cancellation withdrawn", f"The class ({old['where']}) is back on the timetable."),
        Override.EXTRA: ("Extra class removed", f"{what} ({old['where']}) was removed."),
        Override.OCCUPY: ("Room reservation lifted", f"{what} ({old['where']}) no longer blocks the room."),
    }[old["kind"]]
    notify_members(inst, Notification.REMOVED, f"{title} · {old['room'].name}", body, old["room"], actor)
    sync_room_states(inst, notify=False)


def announce_timetable(inst, title, body, actor=None):
    notify_members(inst, Notification.TIMETABLE, title, body, None, actor)
    sync_room_states(inst, notify=False)


def sync_room_states(inst, notify=True):
    """Compare each room's live status with the last one stored; alert when it became free."""
    now = local_now()
    rooms = list(Room.objects.filter(department__institute=inst))
    if not rooms:
        return
    blocks = build_day(rooms, now.date())
    minute = mins(now.time())
    known = {r.room_id: r for r in RoomState.objects.filter(room__in=rooms)}
    new, freed = [], []
    for r in rooms:
        st = status_at(blocks[r.id], minute)
        rec = known.get(r.id)
        if rec is None:
            new.append(RoomState(room=r, state=st["state"]))
        elif rec.state != st["state"]:
            # conditional update: if two clients poll at once, only one wins and notifies
            won = RoomState.objects.filter(pk=rec.pk, state=rec.state).update(state=st["state"])
            if won and notify and st["state"] == FREE:
                freed.append((r, st))
    RoomState.objects.bulk_create(new, ignore_conflicts=True)
    if len(freed) > 3:
        notify_members(inst, Notification.FREED, f"{len(freed)} rooms are free now",
                       ", ".join(r.name for r, _ in freed[:6]) + ("..." if len(freed) > 6 else ""))
    else:
        for r, st in freed:
            until = st.get("until")
            notify_members(inst, Notification.FREED, f"{r.name} is free now",
                           f"Free until {until}." if until else "Free for the rest of the day.", r)
    Notification.objects.filter(institute=inst, created_at__lt=now - timedelta(days=7)).delete()
