from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import BookingForm, InstituteSignupForm, OverrideForm, QuickOccupyForm, UploadForm
from .models import Department, Institute, Override, Room, TimetableUpload
from .services import (BOOKED, BUSY, CHANGED, EMERGENCY, FREE, STATE_TEXT, build_day,
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


# ------------------------------------------------------------------ public pages
def home(request):
    return render(request, "home.html", dict(campuses=Institute.objects.all()[:12]))


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


@login_required
def my_campus(request):
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


def dashboard(request, slug):
    inst = get_object_or_404(Institute, slug=slug)
    now = local_now()
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = now.date()
    is_today = day == now.date()
    minute = mins(now.time())

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

    sections, counts = {}, {FREE: 0, BUSY: 0, CHANGED: 0, BOOKED: 0, EMERGENCY: 0}
    for r in rooms:
        bl = blocks[r.id]
        for b in bl:
            b["left"] = (b["start"] - w0) / span * 100
            b["width"] = (b["end"] - b["start"]) / span * 100
        st = status_at(bl, minute) if is_today else None
        sec = sections.setdefault(r.department, dict(rows=[], free=0))
        if st:
            counts[st["state"]] += 1
            st["text"] = STATE_TEXT[st["state"]]
            sec["free"] += st["state"] == FREE
        sec["rows"].append({"room": r, "blocks": bl, "status": st})

    ctx = dict(
        inst=inst, sections=list(sections.items()), hours=hours, now_left=now_left,
        is_today=is_today, day=day, now=now, counts=counts, total=len(rooms),
        departments=Department.objects.filter(institute=inst), room_types=Room.TYPES,
        sel_dept=request.GET.get("dept", ""), sel_type=request.GET.get("type", ""),
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
    )
    return render(request, "dashboard.html", ctx)


def api_status(request, slug):
    inst = get_object_or_404(Institute, slug=slug)
    now = local_now()
    rooms = list(_rooms(inst, request))
    blocks = build_day(rooms, now.date())
    data = []
    for r in rooms:
        st = status_at(blocks[r.id], mins(now.time()))
        data.append(dict(room=r.name, department=r.department.name, type=r.room_type,
                         capacity=r.capacity, **st))
    return JsonResponse({"institute": inst.name, "as_of": now.isoformat(), "rooms": data})


def book(request, slug):
    """Anyone (student or faculty) can hold a session in a room that is free."""
    inst = get_object_or_404(Institute, slug=slug)
    now = local_now()
    initial = {"date": now.date(), "start_time": now.time().replace(second=0, microsecond=0),
               "room": request.GET.get("room")}
    form = BookingForm(request.POST or None, institute=inst, initial=initial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        clash = room_conflict(d["room"], d["date"], d["start_time"], d["end_time"])
        if clash:
            form.add_error(None, f"{d['room'].name} is not free then: {clash['title']} "
                                 f"({clash['label']}). Pick another room or time.")
        else:
            Override.objects.create(
                room=d["room"], kind=Override.BOOKING, role=d["role"], date=d["date"],
                start_time=d["start_time"], end_time=d["end_time"], title=d["title"],
                teacher=d["teacher"], created_by=request.user if request.user.is_authenticated else None)
            messages.success(request, f"{d['room'].name} is yours on {d['date']:%d %b}, "
                                      f"{d['start_time']:%H:%M}–{d['end_time']:%H:%M}.")
            return redirect("dashboard", slug=inst.slug)
    mine = []
    today = now.date()
    for o in Override.objects.filter(room__department__institute=inst, kind=Override.BOOKING,
                                     date__gte=today).select_related("room")[:15]:
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
        else:
            messages.error(request, "Nothing could be imported from that PDF.")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    preview = [{**s, "day_name": days[s["day"]]} for s in (result.sessions[:60] if result and groups else [])]
    return render(request, "upload.html", dict(
        inst=inst, form=form, result=result, groups=groups, preview=preview,
        uploads=TimetableUpload.objects.filter(institute=inst)[:10]))


@owner_only
@require_POST
def delete_upload(request, inst, pk):
    get_object_or_404(TimetableUpload, pk=pk, institute=inst).delete()
    cleanup_empty(inst)
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
                Override.objects.create(
                    room=quick.cleaned_data["room"], kind=Override.OCCUPY, date=now.date(),
                    start_time=now.time().replace(second=0, microsecond=0),
                    end_time=end.time().replace(second=0, microsecond=0),
                    title="Emergency occupancy", reason=quick.cleaned_data["reason"],
                    created_by=request.user)
                messages.success(request, "Room marked as occupied right now.")
                return redirect("manage", slug=inst.slug)
        else:
            form = OverrideForm(request.POST, institute=inst)
            if form.is_valid():
                Override.objects.create(created_by=request.user, **form.cleaned_data)
                messages.success(request, "Change saved. Dashboard updated instantly.")
                return redirect("manage", slug=inst.slug)
    upcoming = Override.objects.filter(room__department__institute=inst, date__gte=now.date()
                                       ).select_related("room", "room__department")
    return render(request, "manage.html", dict(inst=inst, form=form, quick=quick, upcoming=upcoming,
                                               has_rooms=form.fields["room"].queryset.exists()))


@owner_only
@require_POST
def delete_override(request, inst, pk):
    get_object_or_404(Override, pk=pk, room__department__institute=inst).delete()
    messages.success(request, "Removed. The room is back to its normal timetable.")
    return redirect("manage", slug=inst.slug)
