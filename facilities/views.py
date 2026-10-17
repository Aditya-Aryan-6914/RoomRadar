from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import OverrideForm, QuickOccupyForm, UploadForm
from .models import ClassSession, Department, Override, Room
from .services import (BUSY, CHANGED, EMERGENCY, FREE, build_day, fmt, import_timetable,
                       local_now, mins, status_at)

STATE_TEXT = {FREE: "Free", BUSY: "In class", CHANGED: "Rescheduled class", EMERGENCY: "Reserved / emergency"}


def _filtered_rooms(request):
    rooms = Room.objects.select_related("department")
    if request.GET.get("dept"):
        rooms = rooms.filter(department_id=request.GET["dept"])
    if request.GET.get("type"):
        rooms = rooms.filter(room_type=request.GET["type"])
    return rooms


def dashboard(request):
    now = local_now()
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = now.date()
    is_today = day == now.date()
    minute = mins(now.time())

    rooms = list(_filtered_rooms(request))
    blocks = build_day(rooms, day)

    w0, w1 = 8 * 60, 18 * 60
    for bl in blocks.values():
        for b in bl:
            w0 = min(w0, b["start"] // 60 * 60)
            w1 = max(w1, -(-b["end"] // 60) * 60)
    span = w1 - w0
    hours = [{"label": fmt(h), "width": 60 / span * 100} for h in range(w0, w1, 60)]
    now_left = (minute - w0) / span * 100 if is_today and w0 <= minute <= w1 else None

    sections, counts = {}, {FREE: 0, BUSY: 0, CHANGED: 0, EMERGENCY: 0}
    for r in rooms:
        bl = blocks[r.id]
        for b in bl:
            b["left"] = (b["start"] - w0) / span * 100
            b["width"] = (b["end"] - b["start"]) / span * 100
        st = status_at(bl, minute) if is_today else None
        if st:
            counts[st["state"]] += 1
            st["text"] = STATE_TEXT[st["state"]]
        sections.setdefault(r.department, []).append({"room": r, "blocks": bl, "status": st})

    ctx = dict(
        sections=list(sections.items()), hours=hours, cols=len(hours), now_left=now_left,
        is_today=is_today, day=day, now=now, counts=counts, total=len(rooms),
        departments=Department.objects.all(), room_types=Room.TYPES,
        sel_dept=request.GET.get("dept", ""), sel_type=request.GET.get("type", ""),
        prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
    )
    return render(request, "dashboard.html", ctx)


def api_status(request):
    now = local_now()
    rooms = list(_filtered_rooms(request))
    blocks = build_day(rooms, now.date())
    data = []
    for r in rooms:
        st = status_at(blocks[r.id], mins(now.time()))
        data.append(dict(room=r.name, department=r.department.name, type=r.room_type,
                         capacity=r.capacity, **st))
    return JsonResponse({"as_of": now.isoformat(), "rooms": data})


@staff_member_required(login_url="login")
def upload(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    result = created = None
    if request.method == "POST" and form.is_valid():
        f = form.cleaned_data["pdf"]
        result, created = import_timetable(
            form.cleaned_data["department"], f, form.cleaned_data["class_name"],
            form.cleaned_data["room"], user=request.user, upload_file=f)
        if created:
            messages.success(request, f"Imported {created} class slots. Dashboard is updated.")
        else:
            messages.error(request, "Nothing could be imported from that PDF.")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    preview = []
    if result:
        for s in result.sessions:
            preview.append({**s, "day_name": days[s["day"]]})
    return render(request, "upload.html", dict(form=form, result=result, preview=preview))


@staff_member_required(login_url="login")
def manage(request):
    now = local_now()
    form = OverrideForm(initial={"date": now.date(), "kind": Override.CANCEL})
    quick = QuickOccupyForm()
    if request.method == "POST":
        if "quick" in request.POST:
            quick = QuickOccupyForm(request.POST)
            if quick.is_valid():
                start = now
                end = start + timedelta(minutes=quick.cleaned_data["minutes"])
                if end.date() != start.date():
                    end = end.replace(hour=23, minute=59)
                Override.objects.create(
                    room=quick.cleaned_data["room"], kind=Override.OCCUPY, date=start.date(),
                    start_time=start.time().replace(second=0, microsecond=0),
                    end_time=end.time().replace(second=0, microsecond=0),
                    title="Emergency occupancy", reason=quick.cleaned_data["reason"],
                    created_by=request.user)
                messages.success(request, "Room marked as occupied right now.")
                return redirect("manage")
        else:
            form = OverrideForm(request.POST)
            if form.is_valid():
                o = form.save(commit=False)
                o.created_by = request.user
                o.save()
                messages.success(request, "Change saved. Dashboard updated instantly.")
                return redirect("manage")
    upcoming = Override.objects.filter(date__gte=now.date()).select_related("room", "room__department")
    return render(request, "manage.html", dict(form=form, quick=quick, upcoming=upcoming))


@staff_member_required(login_url="login")
@require_POST
def delete_override(request, pk):
    get_object_or_404(Override, pk=pk).delete()
    messages.success(request, "Change removed - room is back to its normal timetable.")
    return redirect("manage")
