from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (BookingForm, InstitutePasswordForm, InstituteSignupForm, OverrideForm,
                    QuickOccupyForm, StudentLoginForm, StudentSignupForm, UnlockForm, UploadForm)
from .models import (ClassSession, Department, Institute, Notification, Override, Room,
                     StudentProfile, TimetableUpload)
from .services import (BOOKED, announce_override, announce_removed, announce_timetable,
                       announce_update, snapshot, sync_room_states, BUSY, CHANGED, EMERGENCY, FREE, STATE_TEXT, build_day,
                       cleanup_empty, fmt, import_timetable, local_now, mins, room_conflict,
                       status_at)


def owner_only(view):
    """The logged-in user must be the owner of the institute in the URL."""
    @wraps(view)
    @login_required
    def wrapper(request, slug, *a, **kw):
        inst = get_object_or_404(Institute, slug=slug)
        if inst.owner_id != request.user.id:
            raise Http404
        return view(request, inst, *a, **kw)
    return wrapper


def is_member(user, inst):
    """Owner of the institute, or a student registered with it."""
    if not user.is_authenticated:
        return False
    if inst.owner_id == user.id:
        return True
    sp = getattr(user, "student_profile", None)
    return bool(sp and sp.institute_id == inst.id)


def can_view(request, inst):
    return is_member(request.user, inst) or inst.id in request.session.get("unlocked", [])


def member_view(view):
    """Logged-in users only; other institutes need the institute password (unlock)."""
    @wraps(view)
    def wrapper(request, slug, *a, **kw):
        inst = get_object_or_404(Institute, slug=slug)
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not can_view(request, inst):
            return redirect(f"{reverse('unlock', args=[inst.slug])}?next={request.path}")
        return view(request, inst, *a, **kw)
    return wrapper


def member_only(view):
    """Only the owner or students of this institute (not visitors who merely unlocked it)."""
    @wraps(view)
    @login_required
    def wrapper(request, slug, *a, **kw):
        inst = get_object_or_404(Institute, slug=slug)
        if not is_member(request.user, inst):
            messages.error(request, "Only members of this institute can do that.")
            return redirect("dashboard", slug=inst.slug)
        return view(request, inst, *a, **kw)
    return wrapper


def _flash_form_errors(request, form):
    """Show form problems as a pop-up alert (messages are rendered as pop-ups by flash.js)."""
    parts = []
    for field, errs in form.errors.items():
        label = "" if field == "__all__" else f"{form.fields[field].label or field.title()}: "
        parts.append(label + " ".join(errs))
    if parts:
        messages.error(request, "Couldn't save. " + " ".join(parts[:3]))


def can_edit_event(user, inst, o):
    if inst.owner_id == user.id:
        return True
    return o.kind == Override.BOOKING and o.created_by_id == user.id and o.date >= local_now().date()


# ------------------------------------------------------------------ public pages
def home(request):
    return render(request, "home.html", dict(
        campuses=Institute.objects.all()[:12], n_campuses=Institute.objects.count(),
        n_rooms=Room.objects.count(), n_students=StudentProfile.objects.count()))


def signup(request):
    if request.user.is_authenticated and hasattr(request.user, "institute"):
        return redirect("my_campus")
    form = InstituteSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        inst = form.save()
        login(request, inst.owner)
        messages.success(request, "Account created. Upload your first timetable PDF to build the dashboard.")
        return redirect("upload", slug=inst.slug)
    return render(request, "signup.html", dict(form=form))


def student_signup(request):
    if request.user.is_authenticated:
        return redirect("my_campus")
    form = StudentSignupForm(request.POST or None, initial={"institute": request.GET.get("institute")})
    if request.method == "POST" and form.is_valid():
        profile = form.save()
        login(request, profile.user)
        messages.success(request, f"Welcome, {profile.full_name}! You joined {profile.institute.name}.")
        return redirect("dashboard", slug=profile.institute.slug)
    return render(request, "student_signup.html", dict(form=form, has_institutes=Institute.objects.exists()))


def student_login(request):
    if request.user.is_authenticated:
        return redirect("my_campus")
    form = StudentLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.cleaned_data["user"])
        return redirect("dashboard", slug=form.cleaned_data["institute"].slug)
    return render(request, "student_login.html", dict(form=form))


@login_required
def my_campus(request):
    profile = getattr(request.user, "student_profile", None)
    if profile:
        return redirect("dashboard", slug=profile.institute.slug)
    inst = getattr(request.user, "institute", None)
    if not inst:
        return redirect("home")
    return redirect("upload" if not Room.objects.filter(department__institute=inst).exists()
                    else "dashboard", slug=inst.slug)


def _rooms(inst, request):
    rooms = Room.objects.filter(department__institute=inst).select_related("department")
    if request.GET.get("dept", "").isdigit():
        rooms = rooms.filter(department_id=request.GET["dept"])
    if request.GET.get("type") in dict(Room.TYPES):
        rooms = rooms.filter(room_type=request.GET["type"])
    return rooms


def _url(**params):
    from urllib.parse import urlencode
    return "?" + urlencode({k: v for k, v in params.items() if v})


@member_view
def dashboard(request, inst):
    now = local_now()
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = now.date()
    is_today = day == now.date()
    minute = mins(now.time())
    sel_dept = request.GET.get("dept", "") if request.GET.get("dept", "").isdigit() else ""
    sel_type = request.GET.get("type", "") if request.GET.get("type") in dict(Room.TYPES) else ""
    dept_obj = Department.objects.filter(institute=inst, pk=sel_dept).first() if sel_dept else None
    if sel_dept and not dept_obj:
        sel_dept = ""

    rooms = list(_rooms(inst, request))
    blocks = build_day(rooms, day)

    w0, w1 = 8 * 60, 18 * 60
    for bl in blocks.values():
        for b in bl:
            w0 = min(w0, b["start"] // 60 * 60)
            w1 = max(w1, -(-b["end"] // 60) * 60)
    span = w1 - w0
    hours = [{"label": fmt(h), "width": 60 / span * 100} for h in range(w0, w1, 60)]
    now_left = (minute - w0) / span * 100 if is_today and w0 <= minute <= w1 else None

    # grouped by room type (Classrooms / Labs / Other) - for the whole institute or one department
    type_label = dict(Room.TYPES)
    sections, counts = {}, {FREE: 0, BUSY: 0, CHANGED: 0, BOOKED: 0, EMERGENCY: 0}
    dept_free = {}
    for r in rooms:
        bl = blocks[r.id]
        for b in bl:
            b["left"] = (b["start"] - w0) / span * 100
            b["width"] = (b["end"] - b["start"]) / span * 100
        st = status_at(bl, minute) if is_today else None
        sec = sections.setdefault(r.room_type, dict(key=r.room_type, label=type_label[r.room_type] + "s"
                                                    if r.room_type != Room.OTHER else "Seminar & other rooms",
                                                    rows=[], free=0))
        if st:
            counts[st["state"]] += 1
            st["text"] = STATE_TEXT[st["state"]]
            sec["free"] += st["state"] == FREE
            dept_free[r.department_id] = dept_free.get(r.department_id, 0) + (st["state"] == FREE)
        sec["rows"].append({"room": r, "blocks": bl, "status": st})
    order = [Room.CLASSROOM, Room.LAB, Room.OTHER]
    section_list = [sections[k] for k in order if k in sections]

    base = dict(dept=sel_dept, type=sel_type, date=day.isoformat() if not is_today else "")
    dept_chips = [dict(id="", name="All departments", active=not sel_dept,
                       url=_url(**{**base, "dept": ""}), n=Room.objects.filter(department__institute=inst).count())]
    for d in Department.objects.filter(institute=inst).annotate(n=Count("rooms")):
        dept_chips.append(dict(id=d.id, name=d.name, n=d.n, active=str(d.id) == sel_dept,
                               free=dept_free.get(d.id) if is_today and not sel_dept else None,
                               url=_url(**{**base, "dept": d.id})))
    type_chips = [dict(label="All", active=not sel_type, url=_url(**{**base, "type": ""}))] + [
        dict(label=l + "s" if v != Room.OTHER else "Other", active=sel_type == v, url=_url(**{**base, "type": v}))
        for v, l in Room.TYPES]

    dept_info = None
    if dept_obj:
        all_rooms = Room.objects.filter(department=dept_obj)
        divisions = sorted(set(ClassSession.objects.filter(room__department=dept_obj)
                               .exclude(class_name="").values_list("class_name", flat=True)))
        teachers = (ClassSession.objects.filter(room__department=dept_obj).exclude(teacher="")
                    .values("teacher").distinct().count())
        dept_info = dict(obj=dept_obj, classrooms=all_rooms.filter(room_type=Room.CLASSROOM).count(),
                         labs=all_rooms.filter(room_type=Room.LAB).count(),
                         other=all_rooms.filter(room_type=Room.OTHER).count(),
                         divisions=divisions, teachers=teachers,
                         weekly_slots=ClassSession.objects.filter(room__department=dept_obj).count(),
                         free_now=sum(s["free"] for s in section_list) if is_today else None)

    switch = [dict(inst=i, url=reverse("dashboard", args=[i.slug]), current=i.id == inst.id,
                   joined=is_member(request.user, i)) for i in Institute.objects.all()]

    ctx = dict(
        inst=inst, sections=section_list, hours=hours, now_left=now_left,
        is_today=is_today, day=day, now=now, counts=counts, total=len(rooms),
        dept_chips=dept_chips, type_chips=type_chips, dept_info=dept_info, switch=switch,
        sel_dept=sel_dept, sel_type=sel_type, can_book=is_member(request.user, inst),
        is_owner=inst.owner_id == request.user.id,
        prev_url=_url(**{**base, "date": (day - timedelta(days=1)).isoformat()}),
        next_url=_url(**{**base, "date": (day + timedelta(days=1)).isoformat()}),
        today_url=_url(**{**base, "date": ""}),
    )
    return render(request, "dashboard.html", ctx)


@login_required
def unlock(request, slug):
    """Browse another institute by entering its institute password."""
    inst = get_object_or_404(Institute, slug=slug)
    nxt = request.GET.get("next") or request.POST.get("next") or reverse("dashboard", args=[slug])
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = reverse("dashboard", args=[slug])
    if can_view(request, inst):
        return redirect(nxt)
    form = UnlockForm(request.POST or None)
    attempts = request.session.get("unlock_tries", {})
    if request.method == "POST" and form.is_valid():
        if attempts.get(str(inst.id), 0) >= 5:
            form.add_error("password", "Too many wrong attempts. Please try again later.")
        elif inst.check_access_password(form.cleaned_data["password"]):
            request.session["unlocked"] = list(set(request.session.get("unlocked", []) + [inst.id]))
            return redirect(nxt)
        else:
            attempts[str(inst.id)] = attempts.get(str(inst.id), 0) + 1
            request.session["unlock_tries"] = attempts
            form.add_error("password", "Wrong institute password.")
    return render(request, "unlock.html", dict(form=form, target=inst, next=nxt))


@owner_only
def access(request, inst):
    form = InstitutePasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        inst.set_access_password(form.cleaned_data["password1"])
        inst.save(update_fields=["access_password"])
        messages.success(request, "Institute password updated. Share the new one with your students.")
        return redirect("access", slug=inst.slug)
    return render(request, "access.html", dict(
        inst=inst, form=form, has_password=bool(inst.access_password),
        students=StudentProfile.objects.filter(institute=inst)))


@owner_only
@require_POST
def remove_student(request, inst, pk):
    sp = get_object_or_404(StudentProfile, pk=pk, institute=inst)
    sp.user.delete()
    messages.success(request, "Student removed.")
    return redirect("access", slug=inst.slug)


@member_view
def api_status(request, inst):
    now = local_now()
    rooms = list(_rooms(inst, request))
    blocks = build_day(rooms, now.date())
    data = []
    for r in rooms:
        st = status_at(blocks[r.id], mins(now.time()))
        data.append(dict(room=r.name, department=r.department.name, type=r.room_type,
                         capacity=r.capacity, **st))
    return JsonResponse({"institute": inst.name, "as_of": now.isoformat(), "rooms": data})


@member_only
def book(request, inst):
    """Members (students and faculty of this institute) can hold a session in a free room."""
    now = local_now()
    profile = getattr(request.user, "student_profile", None)
    initial = {"date": now.date(), "start_time": now.time().replace(second=0, microsecond=0),
               "room": request.GET.get("room"), "teacher": profile.full_name if profile else ""}
    form = BookingForm(request.POST or None, institute=inst, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        clash = room_conflict(d["room"], d["date"], d["start_time"], d["end_time"])
        if clash:
            messages.error(request, f"Booking failed: {d['room'].name} is not free then "
                                    f"({clash['title']}, {clash['label']}). Pick another room or time.")
        else:
            o = Override.objects.create(
                room=d["room"], kind=Override.BOOKING, role=d["role"], date=d["date"],
                start_time=d["start_time"], end_time=d["end_time"], title=d["title"],
                teacher=d["teacher"], created_by=request.user)
            announce_override(inst, o, request.user)
            messages.success(request, f"{d['room'].name} is yours on {d['date']:%d %b}, "
                                      f"{d['start_time']:%H:%M}–{d['end_time']:%H:%M}.")
            return redirect("dashboard", slug=inst.slug)
    if request.method == "POST" and form.errors:
        _flash_form_errors(request, form)
    mine = []
    today = now.date()
    for o in Override.objects.filter(room__department__institute=inst, kind=Override.BOOKING,
                                     date__gte=today).select_related("room")[:25]:
        o.editable = can_edit_event(request.user, inst, o)
        mine.append(o)
    return render(request, "book.html", dict(inst=inst, form=form, upcoming=mine,
                                             has_rooms=form.fields["room"].queryset.exists()))


# ------------------------------------------------------------------ institute-owner pages
@owner_only
def upload(request, inst):
    form = UploadForm(request.POST or None, request.FILES or None)
    result = groups = None
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["pdf"]
        result, groups = import_timetable(inst, f, form.cleaned_data["department"],
                                          filename=f.name, upload_file=f)
        if groups:
            messages.success(request, f"Imported {sum(g['sessions'] for g in groups)} class slots "
                                      f"for {len(groups)} division(s). Dashboard is updated.")
            announce_timetable(inst, "Timetable updated", f"{sum(g['sessions'] for g in groups)} class slots "
                               + "for " + ", ".join(f"{g['department']} {g['class_name']}" for g in groups[:4])
                               + ("..." if len(groups) > 4 else "") + ".", request.user)
        else:
            messages.error(request, "Nothing could be imported from that PDF.")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    preview = [{**s, "day_name": days[s["day"]]} for s in (result.sessions[:60] if result and groups else [])]
    return render(request, "upload.html", dict(
        inst=inst, form=form, result=result, groups=groups, preview=preview,
        extractor=(result.data or {}).get("extractor") if result else "",
        upload_id=getattr(result, "upload_id", None),
        uploads=TimetableUpload.objects.filter(institute=inst)[:10]))


@owner_only
def upload_json(request, inst, pk):
    """Download the structured JSON that was read from an uploaded timetable PDF."""
    up = get_object_or_404(TimetableUpload, pk=pk, institute=inst)
    if not up.parsed_json:
        raise Http404("This upload has no parsed JSON (it was imported with an older version).")
    name = (up.filename.rsplit(".", 1)[0] or "timetable") + ".json"
    resp = HttpResponse(up.parsed_json, content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


@owner_only
@require_POST
def delete_upload(request, inst, pk):
    up = get_object_or_404(TimetableUpload, pk=pk, institute=inst)
    label = up.summary or up.filename or "A timetable"
    up.delete()
    cleanup_empty(inst)
    announce_timetable(inst, "Timetable removed", f"{label} was removed. Affected rooms may have changed.", request.user)
    messages.success(request, "Timetable removed from the dashboard.")
    return redirect("upload", slug=inst.slug)


@owner_only
def manage(request, inst):
    now = local_now()
    form = OverrideForm(institute=inst, initial={"date": now.date(), "kind": Override.CANCEL})
    quick = QuickOccupyForm(institute=inst)
    if request.method == "POST":
        if "quick" in request.POST:
            quick = QuickOccupyForm(request.POST, institute=inst)
            if quick.is_valid():
                end = now + timedelta(minutes=quick.cleaned_data["minutes"])
                if end.date() != now.date():
                    end = end.replace(hour=23, minute=59)
                o = Override.objects.create(
                    room=quick.cleaned_data["room"], kind=Override.OCCUPY, date=now.date(),
                    start_time=now.time().replace(second=0, microsecond=0),
                    end_time=end.time().replace(second=0, microsecond=0),
                    title="Emergency occupancy", reason=quick.cleaned_data["reason"],
                    created_by=request.user)
                announce_override(inst, o, request.user)
                messages.success(request, "Room marked as occupied right now.")
                return redirect("manage", slug=inst.slug)
        else:
            form = OverrideForm(request.POST, institute=inst)
            if form.is_valid():
                o = Override.objects.create(created_by=request.user, **form.cleaned_data)
                announce_override(inst, o, request.user)
                messages.success(request, "Change saved. Dashboard updated instantly.")
                return redirect("manage", slug=inst.slug)
    for f in (form, quick):
        if f.is_bound and f.errors:
            _flash_form_errors(request, f)
    upcoming = Override.objects.filter(room__department__institute=inst, date__gte=now.date()
                                       ).select_related("room", "room__department")
    return render(request, "manage.html", dict(inst=inst, form=form, quick=quick, upcoming=upcoming,
                                               has_rooms=form.fields["room"].queryset.exists()))


def _event_or_404(inst, pk):
    return get_object_or_404(Override.objects.select_related("room"), pk=pk,
                             room__department__institute=inst)


def _back(request, inst):
    return redirect("manage" if inst.owner_id == request.user.id else "book", slug=inst.slug)


@member_only
def edit_event(request, inst, pk):
    """Edit a booking or change. Owners can edit anything; students only their own bookings."""
    o = _event_or_404(inst, pk)
    if not can_edit_event(request.user, inst, o):
        messages.error(request, "You can only edit your own upcoming bookings.")
        return _back(request, inst)
    is_booking = o.kind == Override.BOOKING
    Form = BookingForm if is_booking else OverrideForm
    initial = dict(room=o.room_id, kind=o.kind, role=o.role or "student", date=o.date,
                   start_time=o.start_time, end_time=o.end_time, title=o.title,
                   teacher=o.teacher, reason=o.reason)
    form = Form(request.POST or None, institute=inst, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        clash = room_conflict(d["room"], d["date"], d["start_time"], d["end_time"],
                              ignore_id=o.pk) if is_booking else None
        if clash:
            messages.error(request, f"Couldn't save: {d['room'].name} is not free then "
                                    f"({clash['title']}, {clash['label']}). Pick another room or time.")
        else:
            old = snapshot(o)
            for k, v in d.items():
                setattr(o, k, v)
            o.save()
            announce_update(inst, o, old, request.user)
            messages.success(request, "Changes saved. Everyone has been notified.")
            return _back(request, inst)
    elif request.method == "POST":
        _flash_form_errors(request, form)
    return render(request, "edit_event.html", dict(inst=inst, form=form, o=o, is_booking=is_booking,
                                                   back=reverse("manage" if inst.owner_id == request.user.id
                                                                else "book", args=[inst.slug])))


@member_only
@require_POST
def delete_event(request, inst, pk):
    o = _event_or_404(inst, pk)
    if not can_edit_event(request.user, inst, o):
        messages.error(request, "You can only remove your own upcoming bookings.")
        return _back(request, inst)
    old = snapshot(o)
    o.delete()
    announce_removed(inst, old, request.user)
    messages.success(request, "Removed. The room is back to its normal timetable.")
    return _back(request, inst)


@member_only
def notifications(request, inst):
    """JSON for the bell. Every call also checks for rooms that just became free."""
    sync_room_states(inst)
    qs = Notification.objects.filter(user=request.user, institute=inst)
    items = [dict(id=n.id, kind=n.kind, title=n.title, body=n.body, read=n.is_read,
                  ago=("just now" if (timezone.now() - n.created_at).total_seconds() < 60
                       else timesince(n.created_at).split(",")[0].replace("\xa0", " ") + " ago"),
                  age_s=int((timezone.now() - n.created_at).total_seconds()))
             for n in qs[:15]]
    return JsonResponse({"unread": qs.filter(is_read=False).count(), "items": items})


@member_only
@require_POST
def notifications_read(request, inst):
    Notification.objects.filter(user=request.user, institute=inst, is_read=False).update(is_read=True)
    return JsonResponse({"unread": 0})