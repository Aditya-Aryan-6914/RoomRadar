"""Generates demo timetable PDFs. Needs: pip install reportlab (dev only)."""
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SLOTS = ["9:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-1:00", "1:00-2:00", "2:00-3:00", "3:00-4:00", "4:00-5:00"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def build(path, dept, cls, room, subjects, lab, lab_room):
    """subjects: list of (name, teacher). lab: (name, teacher) 2-hour merged lab."""
    st = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    rows = [["Day"] + SLOTS]
    spans = []
    for d, day in enumerate(DAYS):
        row = [day]
        for c in range(8):
            if c == 3:
                row.append("LUNCH BREAK")
                continue
            if day in ("Tue", "Thu") and c == 5:
                row.append(f"{lab[0]}\n{lab[1]}\n{lab_room}")
            elif day in ("Tue", "Thu") and c == 6:
                row.append("")
                spans.append(((7, d + 1), (7, d + 1)))  # placeholder, replaced below
            else:
                if day == "Sat" and c > 3:
                    row.append("")
                    continue
                n, t = subjects[(d * 3 + c) % len(subjects)]
                row.append(f"{n}\n{t}")
        rows.append(row)
    style = [("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 7),
             ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("BACKGROUND", (4, 1), (4, -1), colors.whitesmoke)]
    for d, day in enumerate(DAYS):
        if day in ("Tue", "Thu"):
            style.append(("SPAN", (6, d + 1), (7, d + 1)))   # 2-hour lab spans 2:00-4:00
    # move lab text to merged cell start: columns are 1-based (col0=Day) so slot c -> column c+1
    for d, day in enumerate(DAYS):
        if day in ("Tue", "Thu"):
            rows[d + 1][6] = f"{lab[0]}\n{lab[1]}\n{lab_room}"
            rows[d + 1][7] = ""
    t = Table(rows, colWidths=[40] + [88] * 8, rowHeights=[24] + [52] * len(DAYS))
    t.setStyle(TableStyle(style))
    doc.build([Paragraph(f"{dept} - Time Table", st["Title"]),
               Paragraph(f"Class: {cls} &nbsp;&nbsp;&nbsp; Room No: {room}", st["Heading3"]), Spacer(1, 8), t])


if __name__ == "__main__":
    build("samples/CSE_SE-A_timetable.pdf", "Computer Engineering", "SE-A", "Room 101",
          [("DBMS", "Dr. Sharma"), ("OS", "Prof. Patil"), ("DSA", "Dr. Kulkarni"), ("Maths-III", "Prof. Joshi"), ("COA", "Ms. Deshmukh")],
          ("DBMS Lab", "Dr. Sharma"), "Lab 1")
    build("samples/ECE_TE-B_timetable.pdf", "Electronics", "TE-B", "Room 205",
          [("VLSI", "Dr. Rao"), ("DSP", "Prof. Nair"), ("Embedded", "Dr. Iyer"), ("Control Sys", "Prof. Menon")],
          ("Embedded Lab", "Dr. Iyer"), "Lab 3")
    build("samples/MECH_SE-C_timetable.pdf", "Mechanical", "SE-C", "Room 310",
          [("Thermodynamics", "Dr. Gupta"), ("Fluid Mech", "Prof. Verma"), ("Mfg Process", "Dr. Singh"), ("Mechanics", "Prof. Khan")],
          ("Workshop", "Prof. Khan"), "Workshop 1")
