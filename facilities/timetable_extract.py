"""Complex timetable PDF -> structured JSON.

Pipeline (one PDF page = one class table):

1. GEOMETRY (code, deterministic): pdfplumber finds the cells. We do not trust the table's own
   column grid (these PDFs often contain thin "sliver" columns and vertically merged cells), so each
   body cell is mapped to a day / time slot by *overlap with the header cells*.
2. HEADER (code): the first row, e.g. ``SY AIML-A CSAMCR-06 Class Teacher: Mrs. X`` gives the
   year, branch, division, **default classroom** and class teacher.
3. CELL MEANING (small LLM if configured, otherwise rules): the messy text of each cell
   (``DBMS (SSS)A1,A2 LAB 2 MP-I (NB)A3,A4 LAB1``) becomes entries
   ``{subject, teacher, batch, room}``. The model only ever sees cell text and must answer with
   JSON, which is validated here. Anything invalid falls back to the rules for that page.
4. DEFAULT ROOM: an entry with no room written in its cell gets the class's default classroom.
   If the header has none, the room used most often in the class's own cells is inferred.

The result is a plain dict (see ``extract_timetable``) that can be saved as a ``.json`` file.
"""
import re
from datetime import time

import pdfplumber

from .parser import BREAK_RE, DAY_MAP, parse_time_range

# ----------------------------------------------------------------------------- patterns
DAY_HDR_RE = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?$", re.I)
BATCH_GROUP_RE = re.compile(r"\b[A-D]\d\b(?:\s*,\s*[A-D]\d\b)*")
BATCH_ONE_RE = re.compile(r"\b[A-D]\d\b")
ROOM_TOKEN_RE = re.compile(
    r"\b(?:(?P<cr>[A-Za-z]{2,6}CR)|(?P<lab>lab))\s*[-–]?\s*(?P<n>\d{1,3})"
    r"(?:\s*(?:&|and)\s*(?P<n2>\d{1,3}))?", re.I)
PAREN_RE = re.compile(r"\(([^()]*)\)")
TITLE_RE = re.compile(
    r"^\s*(?P<year>FY|SY|TY|LY|B\.?\s?Tech|BE|SE|TE)\b\s*(?P<branch>[A-Za-z&]+)?"
    r"(?:\s*[-–]\s*(?P<div>[A-Za-z0-9]))?\s*(?P<room>[A-Za-z]{2,8}\s*[-–]?\s*\d{1,3})?\s*"
    r"(?:Class\s*Teacher\s*[:\-–]?\s*(?P<teacher>.*))?$", re.I)
YEAR_LABELS = {
    "FY": "First Year (FY)", "SY": "Second Year (SY)", "TY": "Third Year (TY)",
    "LY": "Final Year (LY)", "BTECH": "Final Year (B.Tech)",
    "SE": "Second Year (SE)", "TE": "Third Year (TE)", "BE": "Final Year (BE)"}
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ----------------------------------------------------------------------------- small helpers
def _flat(text):
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


def norm_room(raw):
    """'LAB1' -> 'Lab 1', 'CSAMCR – 04' -> 'CSAMCR-04', 'SAMCR06' (typo) -> 'CSAMCR-06'."""
    rooms = find_rooms(raw)
    return rooms[0] if rooms else _flat(raw)[:60]


def find_rooms(text):
    """All room names written in `text` ('Lab 2& 3' gives two rooms)."""
    out = []
    for m in ROOM_TOKEN_RE.finditer(text or ""):
        nums = [m.group("n")] + ([m.group("n2")] if m.group("n2") else [])
        for n in nums:
            if m.group("lab"):
                out.append(f"Lab {int(n)}")
            else:
                cr = m.group("cr").upper()
                if cr.startswith("SAMCR"):          # typo seen in real timetables
                    cr = "C" + cr
                out.append(f"{cr}-{n}")
    return out


def _expand_room_list(group):
    """'CSAMCR 02/ 03/ 04' -> CSAMCR-02, CSAMCR-03, CSAMCR-04 (bare numbers reuse the prefix)."""
    rooms, prefix = [], None
    for part in group.split("/"):
        part = part.strip()
        found = find_rooms(part)
        if found:
            rooms.extend(found)
            prefix = found[-1].rsplit("-", 1)[0] if "-" in found[-1] else None
        elif re.fullmatch(r"\d{1,3}", part) and prefix:
            rooms.append(f"{prefix}-{part}")
    return rooms


def clean_teacher(t):
    t = _flat(t).strip(" ()-–,")
    if " " in t and t.isupper() and len(t) > 5:                       # 'SHAMKUMAR GUPTA'
        t = t.title()
    if len(t) >= 10 and re.fullmatch(r"[A-Z][a-z]+[A-Z][a-z]+", t):   # 'MeghaThombare'
        t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
    return t


def clean_subject(t):
    s = re.sub(r"\s+", " ", t or "").strip(" ,-–:.")
    s = re.sub(r"\s*-\s*(?=\d)", "-", s)                          # 'MDM- 5'  -> 'MDM-5'
    s = re.sub(r"(?<=[A-Za-z])\s+-\s+(?=[IVX]+\b)", " ", s)        # 'Project Phase - I'
    return s


def split_teachers(t):
    """'NB,DDK/Gupta' / 'NB/DDKGupta' -> ['NB', 'DDK', 'Gupta']."""
    t = re.sub(r"(?<=[A-Z]{2})(?=[A-Z][a-z])", "/", t or "")
    return [clean_teacher(p) for p in re.split(r"[/,]", t) if clean_teacher(p)]


def _hhmm(t):
    return f"{t.hour:02d}:{t.minute:02d}"


# ----------------------------------------------------------------------------- rule-based cells
def _parse_entry(text, in_batch_cell=False):
    """One timetable entry (one subject) -> list of dicts {subject, teacher, batch, room, shared}."""
    t = _flat(text)
    if not t:
        return []
    # room list in parentheses -> shared elective across several rooms
    list_rooms = []
    for m in PAREN_RE.finditer(t):
        if find_rooms(m.group(1)):
            list_rooms = _expand_room_list(m.group(1))
            t = t.replace(m.group(0), " ", 1)
            break
    teacher = ""
    m = PAREN_RE.search(t)
    if m:
        teacher = m.group(1)
        t = t.replace(m.group(0), " ", 1)
    free_rooms = []
    if not list_rooms:
        free_rooms = find_rooms(t)
    t = ROOM_TOKEN_RE.sub(" ", t)
    batch = ""
    bm = BATCH_GROUP_RE.search(t)
    if bm:
        batch = ",".join(BATCH_ONE_RE.findall(bm.group(0)))
        t = t.replace(bm.group(0), " ", 1)
    if not teacher and in_batch_cell:
        dm = re.search(r"\s[–-]\s*(.+)$", t)
        if dm and len(dm.group(1).strip()) >= 2 and not re.fullmatch(r"[IVX]+", dm.group(1).strip()):
            teacher = dm.group(1)
            t = t[:dm.start()]
    subject = clean_subject(t)
    if not subject:
        return []
    teachers = split_teachers(teacher)
    rooms = list_rooms or free_rooms or [""]
    out = []
    if len(rooms) > 1 and list_rooms:
        for i, r in enumerate(rooms):
            tt = teachers[i] if len(teachers) == len(rooms) else "/".join(teachers)
            out.append(dict(subject=subject, teacher=tt, batch=batch, room=r, shared=True))
    else:
        tt = "/".join(teachers)
        for r in rooms:
            out.append(dict(subject=subject, teacher=tt, batch=batch, room=r, shared=False))
    return out


def _split_batch_entries(text):
    """'DBMS (SSS)A1,A2 LAB 2 MP-I (NB)A3,A4 LAB1' -> one text per batch entry."""
    t = _flat(text)
    groups = list(BATCH_GROUP_RE.finditer(t))
    if len(groups) < 2:
        return [t], len(groups) == 1
    cuts, prev_end = [0], 0
    for g_prev, g_next in zip(groups, groups[1:]):
        gap_start, gap_end = g_prev.end(), g_next.start()
        gap = t[gap_start:gap_end]
        rm = ROOM_TOKEN_RE.search(gap)
        if rm:                                   # entry ends at its room: 'Lab 3 (KVJ) MP III ...'
            cut = gap_start + rm.end()
            tail = re.match(r"\s*\([^()]*\)", t[cut:gap_end])
            if tail:
                cut += tail.end()
        else:                                    # no room between them: 'C3,C4 MP-I (X) C1,C2'
            cut = gap_start
            tail = re.match(r"\s*\([^()]*\)", gap)
            if tail:
                cut += tail.end()
        cuts.append(cut)
    cuts.append(len(t))
    return [t[a:b].strip() for a, b in zip(cuts, cuts[1:]) if t[a:b].strip()], True


def parse_cell_rules(text):
    t = _flat(text)
    if not t or (BREAK_RE.search(t) and len(t) < 40):
        return []
    parts, has_batch = _split_batch_entries(t)
    out = []
    for p in parts:
        out.extend(_parse_entry(p, in_batch_cell=has_batch))
    return out


# ----------------------------------------------------------------------------- header
def parse_title(text):
    t = _flat(text)
    m = TITLE_RE.match(t)
    meta = dict(name=t, year_code="", year="", branch="", division="", default_room="",
                class_teacher="")
    if not m:
        return meta
    ycode = re.sub(r"[.\s]", "", m.group("year")).upper()
    year_txt = "BTech" if ycode == "BTECH" else ycode
    branch = (m.group("branch") or "").strip()
    div = (m.group("div") or "").strip().upper()
    rooms = find_rooms(m.group("room") or "")
    meta.update(
        year_code=year_txt, year=YEAR_LABELS.get(ycode, ""), branch=branch.upper(), division=div,
        default_room=rooms[0] if rooms else "",
        class_teacher=clean_teacher(m.group("teacher") or ""),
        name=" ".join(x for x in [year_txt, branch.upper() + (f"-{div}" if div else "")] if x))
    return meta


def parse_page_header(text):
    out = dict(institute="", department="", academic_year="", semester="")
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if lines:
        out["institute"] = lines[0]
    for ln in lines:
        m = re.match(r"department\s*(?:of)?\s*[:\-]?\s*(.+)$", ln, re.I)
        if m and not out["department"]:
            out["department"] = m.group(1).strip()
        m = re.search(r"A\.?\s?Y\.?\s*(\d{4}\s*-\s*\d{2,4})", ln)
        if m:
            out["academic_year"] = m.group(1).replace(" ", "")
        m = re.search(r"\b(odd|even)\s*sem", ln, re.I)
        if m:
            out["semester"] = m.group(1).capitalize()
    return out


# ----------------------------------------------------------------------------- geometry
def _overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))


def _cell_text(page, bbox):
    """Text whose characters have their centre inside the cell (no bleed from the neighbour)."""
    x0, top, x1, bottom = bbox
    if x1 - x0 < 3 or bottom - top < 3:
        return ""

    def inside(o):
        if o.get("object_type") != "char":
            return False
        cx, cy = (o["x0"] + o["x1"]) / 2, (o["top"] + o["bottom"]) / 2
        return x0 <= cx <= x1 and top <= cy <= bottom
    try:
        return page.filter(inside).extract_text(x_tolerance=2, y_tolerance=3) or ""
    except Exception:
        return ""


def read_grid(page, table):
    """Return dict(title, days=[(idx,x0,x1)], slots=[(start,end,top,bottom)], cells=[...]) or None.

    Works for the layout 'times down the left, weekdays across the top' and ignores sliver columns.
    """
    cells = [c for c in table.cells if c]
    if not cells:
        return None
    min_x0 = min(c[0] for c in cells)
    min_top = min(c[1] for c in cells)
    width = max(c[2] for c in cells) - min_x0
    title, days, slots, body = "", [], [], []
    for c in cells:
        txt = _flat(_cell_text(page, c))
        x0, top, x1, bottom = c
        if (x1 - x0) >= 0.9 * width and top - min_top < 3:
            title = title or txt
        elif DAY_HDR_RE.match(txt):
            days.append((DAY_MAP[txt.lower()[:3]], x0, x1))
        elif x0 - min_x0 < 4 and (parse_time_range(txt) or BREAK_RE.search(txt)):
            rng = parse_time_range(txt)
            if rng:
                slots.append((rng[0], rng[1], top, bottom))
        elif txt:
            body.append((c, txt))
    if len(days) < 2 or len(slots) < 2:
        return None
    days.sort(key=lambda d: d[1])
    slots.sort(key=lambda s: s[2])
    out = []
    for c, txt in body:
        x0, top, x1, bottom = c
        if x0 - min_x0 < 4:
            continue
        d_hit = [d for d in days if _overlap(x0, x1, d[1], d[2]) >= 0.5 * (d[2] - d[1])]
        if not d_hit:
            cx = (x0 + x1) / 2
            d_hit = [d for d in days if d[1] <= cx < d[2]]
        s_hit = [s for s in slots if _overlap(top, bottom, s[2], s[3]) >= 0.5 * (s[3] - s[2])]
        if not d_hit or not s_hit:
            continue
        out.append(dict(days=[d[0] for d in d_hit], start=s_hit[0][0], end=s_hit[-1][1], text=txt))
    out.sort(key=lambda c: (c["days"][0], c["start"]))
    return dict(title=title, cells=out)


# ----------------------------------------------------------------------------- assembly
def _infer_default_room(entries):
    """Most common non-lab room among entries that are not shared electives."""
    from collections import Counter
    cnt = Counter(e["room"] for e in entries
                  if e["room"] and not e["room"].lower().startswith("lab") and not e["shared"])
    return cnt.most_common(1)[0][0] if cnt else ""


def build_class(grid, llm, warnings, page_no):
    meta = parse_title(grid["title"])
    cells = grid["cells"]
    per_cell = None
    if llm is not None:
        try:
            per_cell, llm_meta = llm.interpret(grid["title"], cells)
            if not meta["year_code"] and llm_meta:           # rules could not read the title
                meta.update({k: v for k, v in llm_meta.items() if v})
        except Exception as exc:                              # network, bad JSON, schema ...
            warnings.append(f"Page {page_no}: the AI model failed ({exc}); used built-in rules.")
            per_cell = None
    all_entries, raw = [], []
    for i, c in enumerate(cells):
        ents = per_cell[i] if per_cell is not None and per_cell[i] is not None \
            else parse_cell_rules(c["text"])
        for e in ents:
            for d in c["days"]:
                raw.append((d, c["start"], c["end"], e))
            all_entries.append(e)
    default_room, source = meta["default_room"], "header"
    if not default_room:
        default_room = _infer_default_room(all_entries)
        source = "inferred from the most used classroom" if default_room else "none"
        if default_room:
            warnings.append(f"{meta['name']}: no classroom in the page header, "
                            f"used {default_room} (most frequent in its cells).")
    shared_name = " ".join(x for x in [meta["year_code"], meta["branch"]] if x) or meta["name"]
    sessions = []
    for d, start, end, e in raw:
        room, room_src = e["room"], "cell"
        if not room:
            room, room_src = default_room, "default"
        if not room:
            warnings.append(f"{meta['name']} {DAY_NAMES[d]} {_hhmm(start)}: '{e['subject']}' "
                            f"has no room and the class has no default room; skipped.")
            continue
        sessions.append(dict(
            class_name=shared_name if e["shared"] else meta["name"],
            day=d, day_name=DAY_NAMES[d], start=_hhmm(start), end=_hhmm(end),
            subject=e["subject"], teacher=e["teacher"], batch=e["batch"],
            room=room, room_source=room_src, shared=bool(e["shared"])))
    sessions = sorted(_merge(sessions), key=lambda x: (x["day"], x["start"], x["room"], x["batch"]))
    meta.update(default_room=default_room, default_room_source=source, page=page_no,
                sessions=sessions)
    return meta


def _merge(sessions):
    """Join back-to-back slots of the same subject/teacher/batch/room, drop exact duplicates."""
    seen, uniq = set(), []
    for s in sorted(sessions, key=lambda s: (s["class_name"], s["day"], s["room"], s["subject"],
                                             s["batch"], s["teacher"], s["start"])):
        key = (s["class_name"], s["day"], s["start"], s["end"], s["room"], s["subject"],
               s["teacher"], s["batch"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    out = []
    for s in uniq:
        p = out[-1] if out else None
        if (p and p["class_name"] == s["class_name"] and p["day"] == s["day"]
                and p["room"] == s["room"] and p["subject"] == s["subject"]
                and p["teacher"] == s["teacher"] and p["batch"] == s["batch"]
                and p["end"] == s["start"]):
            p["end"] = s["end"]
        else:
            out.append(dict(s))
    return out


def extract_timetable(file_like, llm=None, department=""):
    """PDF -> dict:

        {"institute", "department", "academic_year", "semester", "extractor", "warnings",
         "classes": [{"name", "year_code", "year", "branch", "division", "default_room",
                      "default_room_source", "class_teacher", "page",
                      "sessions": [{"class_name","day","day_name","start","end","subject",
                                    "teacher","batch","room","room_source","shared"}]}]}
    """
    data = dict(institute="", department=department, academic_year="", semester="",
                extractor=f"llm:{llm.model}" if llm else "rules", warnings=[], classes=[])
    with pdfplumber.open(file_like) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            tables = page.find_tables()
            top = 0
            for t in tables:
                if not data["institute"] and t.bbox[1] - top > 4:
                    try:
                        head = page.crop((0, top, page.width, t.bbox[1])).extract_text() or ""
                    except Exception:
                        head = ""
                    info = parse_page_header(head)
                    for k, v in info.items():
                        if v and not data.get(k):
                            data[k] = v
                top = t.bbox[3]
                grid = read_grid(page, t)
                if not grid:
                    continue
                cls = build_class(grid, llm, data["warnings"], page_no)
                if cls["sessions"]:
                    data["classes"].append(cls)
    _repair_spaced_subjects(data)
    return data


SPACED_RE = re.compile(r"^(?:\S ){3,}\S$")


def _repair_spaced_subjects(data):
    """Some PDFs justify a line with real spaces ('L e e t C o d e'). Re-join such subjects using
    the spelling of the same words seen elsewhere in the file."""
    from collections import Counter
    sessions = [s for c in data["classes"] for s in c["sessions"]]
    key_of = lambda x: re.sub(r"[\s\-]+", "", x).lower()
    vocab = Counter(s["subject"] for s in sessions if not SPACED_RE.match(s["subject"]))
    by_key = {}
    for subj, _ in vocab.most_common():              # most common spelling of each subject wins
        by_key.setdefault(key_of(subj), subj)
    for s in sessions:
        s["subject"] = by_key.get(key_of(s["subject"])) or re.sub(r"\s+", "", s["subject"])


def to_sessions(data, fallback_department=""):
    """Flatten the JSON into the session dicts that services.import_timetable stores."""
    out = []
    dept = data.get("department") or fallback_department
    for c in data["classes"]:
        for s in c["sessions"]:
            h, m = map(int, s["start"].split(":"))
            h2, m2 = map(int, s["end"].split(":"))
            out.append(dict(
                department=dept, class_name=s["class_name"], home_room=c["default_room"],
                room=s["room"], cell_room=s["room"] if s["room_source"] == "cell" else "",
                subject=s["subject"], teacher=s["teacher"], batch=s["batch"],
                year=c["year"], day=s["day"], start_time=time(h, m), end_time=time(h2, m2)))
    return out
