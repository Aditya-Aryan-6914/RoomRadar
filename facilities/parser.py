"""Timetable PDF -> list of weekly sessions.

Expected layout (the most common one in colleges): a table where the header row holds
time slots (e.g. "9:00-10:00") and the first column holds the weekday (Mon, Tue ...).
Each cell has 1-3 lines:   Subject / Teacher / Room (room optional).
Merged cells (a 2-hour lab) are handled; LUNCH / BREAK cells are skipped.
"""
import re
from dataclasses import dataclass, field
from datetime import time

import pdfplumber

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
TIME_RE = re.compile(
    r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*(?:-|–|—|to)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?",
    re.I)
BREAK_RE = re.compile(r"\b(lunch|break|recess|interval)\b", re.I)
TEACHER_RE = re.compile(r"^\(?\s*(dr|prof|mr|mrs|ms|er|sir|madam)\b\.?", re.I)
ROOM_RE = re.compile(
    r"\b(?:room|rm|lab|lh|cr|hall)[\s.:#-]*[A-Za-z]*\d+[A-Za-z]?\b|\b[A-Z]{1,3}-\d{2,4}\b", re.I)
PAGE_ROOM_RE = re.compile(r"(?:class\s*room|room)\s*(?:no\.?|number)?\s*[:\-]\s*([A-Za-z0-9\- ]{1,20})", re.I)
PAGE_CLASS_RE = re.compile(r"(?:class|division|section|batch)\s*[:\-]\s*([A-Za-z0-9\-]{1,20})", re.I)


@dataclass
class ParseResult:
    sessions: list = field(default_factory=list)   # dicts
    warnings: list = field(default_factory=list)
    class_name: str = ""
    room: str = ""


def _hour(h, mer, is_end=False):
    h = int(h)
    if mer:
        mer = mer.lower()
        if mer == "pm" and h < 12:
            h += 12
        if mer == "am" and h == 12:
            h = 0
    elif h < 8:           # "1-2" in a college timetable means afternoon
        h += 12
    return h


def parse_time_range(text):
    m = TIME_RE.search(text or "")
    if not m:
        return None
    sh, sm, smer, eh, em, emer = m.groups()
    s = _hour(sh, smer)
    e = _hour(eh, emer)
    if e <= s and not emer:
        e += 12
    if e > 23 or s > 23:
        return None
    return time(s, int(sm or 0)), time(e % 24, int(em or 0))


def _clean(cell):
    return [ln.strip() for ln in (cell or "").replace("\r", "").split("\n") if ln.strip()]


def _parse_cell(cell):
    lines = _clean(cell)
    if not lines:
        return None
    text = " ".join(lines)
    if BREAK_RE.search(text) and len(text) < 40:
        return None
    room = ""
    rest = []
    for ln in lines:
        m = ROOM_RE.search(ln)
        if m and not room and len(ln) <= len(m.group(0)) + 8:
            room = m.group(0).strip()
        else:
            rest.append(ln)
    teacher, subject_lines = "", []
    for ln in rest:
        if not teacher and TEACHER_RE.match(ln):
            teacher = ln.strip("() ")
        else:
            subject_lines.append(ln)
    if not teacher and len(subject_lines) >= 2:
        teacher = subject_lines.pop().strip("() ")
    subject = " ".join(subject_lines).strip()
    if not subject:
        return None
    return {"subject": subject, "teacher": teacher, "room": room}


def parse_pdf(file_like, class_name="", room_name=""):
    result = ParseResult(class_name=class_name, room=room_name)
    raw = []
    with pdfplumber.open(file_like) as pdf:
        page_text = "\n".join((p.extract_text() or "") for p in pdf.pages[:1])
        if not result.room:
            m = PAGE_ROOM_RE.search(page_text)
            if m:
                result.room = m.group(1).strip()
        if not result.class_name:
            m = PAGE_CLASS_RE.search(page_text)
            if m:
                result.class_name = m.group(1).strip()
        tables = []
        for page in pdf.pages:
            tables.extend(page.extract_tables())
    if not tables:
        result.warnings.append("No table found in the PDF. Use a PDF that has a grid-style timetable.")
        return result

    for table in tables:
        header_idx, columns = None, {}
        for i, row in enumerate(table):
            found = {}
            for j, cell in enumerate(row):
                rng = parse_time_range(cell or "")
                if rng:
                    found[j] = rng
            if len(found) >= 2:
                header_idx, columns = i, found
                break
        if header_idx is None:
            result.warnings.append("A table without a time header row was skipped.")
            continue
        for row in table[header_idx + 1:]:
            day_txt = (row[0] or "").strip().lower()[:3]
            if day_txt not in DAY_MAP:
                continue
            day = DAY_MAP[day_txt]
            last = None
            for j in sorted(columns):
                if j >= len(row):
                    break
                cell = row[j]
                start, end = columns[j]
                if cell is None:                       # merged with previous cell
                    if last is not None:
                        last["end_time"] = end
                    continue
                if not cell.strip():
                    last = None
                    continue
                info = _parse_cell(cell)
                if not info:
                    last = None
                    continue
                last = {**info, "day": day, "start_time": start, "end_time": end}
                raw.append(last)

    # merge back-to-back identical periods (e.g. 2-hour lab printed twice)
    raw.sort(key=lambda s: (s["day"], s["room"], s["subject"], s["start_time"]))
    merged = []
    for s in raw:
        p = merged[-1] if merged else None
        if (p and p["day"] == s["day"] and p["subject"] == s["subject"] and p["room"] == s["room"]
                and p["teacher"] == s["teacher"] and p["end_time"] == s["start_time"]):
            p["end_time"] = s["end_time"]
        else:
            merged.append(dict(s))
    result.sessions = merged
    if not merged:
        result.warnings.append("The table was read but no class cells were recognised.")
    return result
