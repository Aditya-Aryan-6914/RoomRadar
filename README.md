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

## Reading complex timetables (JSON)
Upload any department timetable; RoomRadar turns it into **structured JSON** (also downloadable from the *Timetables* page, or via the command line) and builds the dashboard from it:

```bash
python manage.py parse_timetable samples/KIT_AIML_DS_2026-27_timetable.pdf --out parsed.json
```
What it understands (see `samples/KIT_AIML_DS_2026-27_parsed.json`):
- **Year / branch / division** from each page title (`SY AIML-A`, `TY AIML-C`, `BTech DS` ...).
- **Default classroom** from the title (`... CSAMCR-06 ...`). Any slot with no room written in its cell gets it. If a title has no room (e.g. `BTech DS`), the room used most often in that class is used and a warning is shown.
- **Subject and teacher** per slot, **practical batches** (`A1,A2`) and their labs, several parallel entries in one cell, 2-hour merged blocks, thin extra columns, breaks/lunch skipped.
- **Shared electives**: `MDM-I (NB/DDK/Gupta) (CSAMCR 06/CSDSCR 01/CSAMCR 02)` becomes one session per room with the matching teacher, stored once.

How it works: code reads the table geometry; the *meaning* of each cell is read by built-in rules, or by a **small LLM** if you configure one. The model only sees cell text, must return JSON, and every field is validated; if it fails the rules take over for that page.

| Setting (env var) | Example |
|---|---|
| `TIMETABLE_LLM_PROVIDER` | `anthropic` or `openai` (any OpenAI-compatible server) or `none` (default) |
| `TIMETABLE_LLM_MODEL` | `claude-haiku-5-5`, `qwen2.5:3b` (Ollama), `llama-3.1-8b-instant` (Groq) |
| `TIMETABLE_LLM_API_KEY` | your key (`ANTHROPIC_API_KEY` also works; not needed for local Ollama) |
| `TIMETABLE_LLM_BASE_URL` | `http://localhost:11434/v1` (Ollama), `https://api.groq.com/openai/v1` |

Privacy: with a hosted model, the text of the timetable cells is sent to that provider. Use a local model (Ollama) to keep everything on your machine. Tests: `python manage.py test facilities`.

## PDF format
Grid timetable: time slots across the top (`9:00-10:00`), weekdays down the left, each cell `Subject / Teacher / Room(optional)`. Title line `Artificial Intelligence - Time Table` and `Class: TE-A   Room No: 401`. Scanned image-only PDFs are not supported. Samples are in `/samples`.

## Layout
`facilities/timetable_extract.py` PDF → JSON · `llm.py` optional small-LLM reader · `parser.py` entry point + older grid parser · `services.py` import + status engine · `models.py` · `forms.py` · `views.py` · `templates/` · `static/` (CSS, `theme.js`, `live.js`).

## Deploy (Render / Railway / PythonAnywhere)
Build `pip install -r requirements.txt && python manage.py migrate`, start `gunicorn roomradar.wsgi`, env vars `DEBUG=0`, `SECRET_KEY=<random>`, `ALLOWED_HOSTS=your.domain`, `CSRF_TRUSTED_ORIGINS=https://your.domain`. Use PostgreSQL for permanent data.
