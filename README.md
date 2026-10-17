# RoomRadar 📡 — Live free-room finder for campus

> Hackathon problem: **Dynamic Resource Allocation for College Facilities.**
> Classrooms and labs often sit empty, but nobody knows which. RoomRadar shows every room's live status
> (free / in class) so students find a space instantly and faculty see empty slots.

## Features
- **Upload a timetable PDF → dashboard builds itself** (department, rooms, weekly schedule parsed automatically).
- **Live cards + day timeline** per department. 🟥 Red = class running (subject, teacher, class shown) · 🟩 Green = free (with "free until HH:MM") · 🟪 Purple = rescheduled/extra class · 🟧 Amber = emergency/event · hatched green = class cancelled (room free).
- **Changes & emergencies** (staff only): one-click "occupy this room now", or schedule cancel / extra / event for any date. Dashboard updates instantly and auto-refreshes every 30 s. Removing the change returns the room to its normal timetable.
- Filters: department, classroom/lab, date, "free rooms only". JSON API: `/api/status/`.

## Run it
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # loads 3 sample timetables + demo staff user admin / admin123
python manage.py runserver
```
Open http://127.0.0.1:8000 . Staff login: `admin / admin123` (change it, or run `python manage.py createsuperuser`).
Time zone is set in `roomradar/settings.py` (`Asia/Kolkata`).

## PDF format that is parsed
A grid timetable: **time slots across the top** (`9:00-10:00`), **weekdays down the left** (`Mon`, `Tue`…),
each cell `Subject / Teacher / Room(optional)`. Merged cells (2-hour labs) and LUNCH/BREAK cells are handled.
Class name and room are auto-detected from lines like `Class: SE-A   Room No: 101`, or typed in the upload form.
Samples in `/samples` (regenerate: `pip install reportlab && python samples/make_sample_pdfs.py`).
Scanned (image-only) PDFs are not supported — use the original exported PDF. If the parse is off, fix rows in `/admin/`.

## Project layout
- `facilities/parser.py` – PDF → sessions (pdfplumber)
- `facilities/services.py` – status engine (timetable + overrides, priority: emergency > rescheduled > class > free)
- `facilities/models.py` – Department, Room, ClassSession, Override, TimetableUpload
- `facilities/views.py`, `templates/`, `static/` – UI

## Deploy
GitHub Pages cannot run Django. Push the repo to GitHub, then deploy free on Render / Railway / PythonAnywhere:
build `pip install -r requirements.txt && python manage.py migrate`, start `gunicorn roomradar.wsgi`,
env vars `DEBUG=0`, `SECRET_KEY=<random>`, `ALLOWED_HOSTS=your.domain`, `CSRF_TRUSTED_ORIGINS=https://your.domain`.
(For permanent data use PostgreSQL; SQLite on free hosts can reset.)

## Ideas for the next version
Room booking requests by students, QR code on each room door, push notifications, multi-sheet/Excel import, 
sensor/Wi-Fi occupancy data to detect rooms that are scheduled but actually empty.
