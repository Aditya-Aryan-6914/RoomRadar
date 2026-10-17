# RoomRadar 📡 — Live free-room finder for campus

> Hackathon problem: **Dynamic Resource Allocation for College Facilities.**
> Classrooms and labs sit empty because nobody knows they are free. RoomRadar reads a timetable PDF and shows every room's live status, so students find a space instantly and faculty see empty slots.

## What changed in this version
- **Home page** explaining the project, with a campus directory.
- **Multi-college accounts.** Any institute registers itself (`/signup/`) and gets its own dashboard at `/c/<campus>/`. Data is isolated per institute.
- **No seed data.** The database starts empty; every department, division and room comes from the PDF a college uploads. (`seed_demo` was removed.)
- **One PDF = many divisions.** Each grid table becomes a division (`AIML-A`, `AIML-B`...). Department name is read from the title (`... - Time Table`), the division and its room from `Class: TE-A  Room No: 401`. Each division gets its own classroom automatically; labs written inside a cell become their own rooms.
- **Hold a session** menu: students *and* faculty can reserve a free room (group study, project work, extra lecture). Clashes with classes, emergencies or other bookings are rejected.
- **Changes & emergencies** for the institute account: occupy a room now, cancel a class, add an extra class, remove any change.
- **Cleaner dashboard**: stat pills, collapsible departments, a "Now" card view and a "Day timeline" view, search, free-only filter, dark-mode support.
- Deleting an uploaded timetable removes its rooms, departments and related bookings.

## Colours
Green = free · Red = class running (subject + teacher) · Purple = extra/rescheduled class · Blue = booked by student/faculty · Amber = emergency · hatched green = class cancelled (room free)

## Run it
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
Open http://127.0.0.1:8000, click **Register campus**, then upload a PDF. JSON API: `/c/<campus>/api/status/`.
`python manage.py createsuperuser` is only needed for the Django admin at `/admin/`.
Time zone: `roomradar/settings.py` (`Asia/Kolkata`).

## PDF format
Grid timetable: time slots across the top (`9:00-10:00`), weekdays down the left, each cell `Subject / Teacher / Room(optional)`. Merged 2-hour cells and LUNCH/BREAK cells are handled.
Text above each grid: `Artificial Intelligence - Time Table` and `Class: TE-A   Room No: 401` (or `Division: A`). If the department is not found you can type it on the upload page.
Scanned image-only PDFs are not supported. Test PDFs are in `/samples` (never loaded automatically): `AIML_all_divisions_timetable.pdf` has 3 divisions in one file.
Regenerate with `pip install reportlab && python samples/make_multi_division_pdf.py`.

## Layout
`facilities/parser.py` PDF to sessions · `services.py` import + live status engine · `models.py` Institute, Department, Room, ClassSession, Override, TimetableUpload · `views.py`, `templates/`, `static/` UI.

## Deploy (Render / Railway / PythonAnywhere)
Build `pip install -r requirements.txt && python manage.py migrate`, start `gunicorn roomradar.wsgi`, env vars `DEBUG=0`, `SECRET_KEY=<random>`, `ALLOWED_HOSTS=your.domain`, `CSRF_TRUSTED_ORIGINS=https://your.domain`. Use PostgreSQL for permanent data (SQLite resets on free hosts).

## Known limits / next ideas
Self-booking is open to anyone with the campus link (name required; the institute account can remove any booking). Next: student login or campus access code, approval flow, QR code per room, Excel import.
