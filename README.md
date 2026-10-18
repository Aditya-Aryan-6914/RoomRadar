# RoomRadar 📡

**Live classroom and lab availability for your institute.** RoomRadar reads a timetable PDF and shows every room's live status, so students find a free space instantly and faculty see empty slots.

## Features
- **Two kinds of accounts**
  - **Institute**: registers with an *institute password*, uploads timetables, manages changes and students.
  - **Student / member**: selects their institute, enters PRN / ID number and the institute password (set by the college), and creates a personal password. Later logs in with institute + PRN + password.
- **Institute → department drill-down**: pick an institute on the dashboard, see all its classrooms and labs, then pick a department to see its divisions, rooms, teachers and weekly slots.
- **Institute switcher with password unlock**: browse another institute (view only) after entering its institute password.
- **Live status** with "free until", Now cards and a day timeline, search, free-only filter, auto refresh.
- **Hold a session**: members reserve a free room; clashes are blocked.
- **Changes & emergencies** for institutes: occupy a room, cancel or add a class.
- **Students & access** page: change the institute password, view/remove students.
- **Light / dark mode** toggle (next to Log out), remembered per browser.
- Multi-division PDF import, JSON API at `/c/<institute>/api/status/` (login required).

## Run it
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
Open http://127.0.0.1:8000. Institutes: **Get started → I'm an institute**. Students: **I'm a student → Join your institute**.
Existing institutes from an older version have no institute password: log in and set one under **Students & access**.
Time zone: `roomradar/settings.py` (`Asia/Kolkata`).

## PDF format
Grid timetable: time slots across the top (`9:00-10:00`), weekdays down the left, each cell `Subject / Teacher / Room(optional)`. Title line `Artificial Intelligence - Time Table` and `Class: TE-A   Room No: 401`. Scanned image-only PDFs are not supported. Samples are in `/samples`.

## Layout
`facilities/parser.py` PDF → sessions · `services.py` import + status engine · `models.py` · `forms.py` · `views.py` · `templates/` · `static/` (CSS, `theme.js`, `live.js`).

## Deploy (Render / Railway / PythonAnywhere)
Build `pip install -r requirements.txt && python manage.py migrate`, start `gunicorn roomradar.wsgi`, env vars `DEBUG=0`, `SECRET_KEY=<random>`, `ALLOWED_HOSTS=your.domain`, `CSRF_TRUSTED_ORIGINS=https://your.domain`. Use PostgreSQL for permanent data.
