"""Builds AIML_all_divisions_timetable.pdf: ONE department PDF holding three divisions (dev/test only).
Needs: pip install reportlab"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SLOTS = ["9:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-1:00", "1:00-2:00", "2:00-3:00", "3:00-4:00"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SUBJ = [("Machine Learning", "Dr. Mehta"), ("Deep Learning", "Prof. Iyer"), ("NLP", "Dr. Khan"),
        ("Computer Vision", "Ms. Rao"), ("Data Mining", "Prof. Das")]


def grid(shift):
    rows = [["Day"] + SLOTS]
    for d, day in enumerate(DAYS):
        row = [day]
        for c in range(len(SLOTS)):
            if c == 3:
                row.append("LUNCH BREAK")
            elif day in ("Wed",) and c == 5:
                row.append("ML Lab\nDr. Mehta\nLab AI-1")
            elif day in ("Wed",) and c == 6:
                row.append("")
            elif (d + c + shift) % 4 == 3:
                row.append("")
            else:
                n, t = SUBJ[(d + c + shift) % len(SUBJ)]
                row.append(f"{n}\n{t}")
        rows.append(row)
    t = Table(rows, colWidths=[40] + [100] * len(SLOTS), rowHeights=[24] + [50] * len(DAYS))
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 7),
                           ("SPAN", (6, 3), (7, 3)) if False else ("FONTSIZE", (0, 0), (0, 0), 7),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    return t


st = getSampleStyleSheet()
doc = SimpleDocTemplate("samples/AIML_all_divisions_timetable.pdf", pagesize=landscape(A4),
                        leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
story = []
for i, (div, room) in enumerate([("TE-A", "Room 401"), ("TE-B", "Room 402"), ("TE-C", "Room 403")]):
    story += [Paragraph("Artificial Intelligence and Machine Learning - Time Table", st["Title"]),
              Paragraph(f"Class: {div} &nbsp;&nbsp; Room No: {room}", st["Heading3"]), Spacer(1, 8), grid(i)]
    story.append(PageBreak()) if i < 2 else None
doc.build(story)
