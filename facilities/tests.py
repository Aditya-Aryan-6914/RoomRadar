import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .llm import parse_llm_json
from .models import ClassSession, Institute
from .services import build_day, import_timetable, status_at
from .timetable_extract import (extract_timetable, find_rooms, parse_cell_rules, parse_title)

PDF = Path(__file__).resolve().parent.parent / "samples" / "KIT_AIML_DS_2026-27_timetable.pdf"


class CellRules(TestCase):
    def test_simple_cell(self):
        self.assertEqual(parse_cell_rules("DMGT (SGB)")[0]["teacher"], "SGB")

    def test_two_batches_two_labs(self):
        e = parse_cell_rules("DBMS (SSS)A1,A2 LAB 2 MP-I (NB)A3,A4 LAB1")
        self.assertEqual([(x["subject"], x["teacher"], x["batch"], x["room"]) for x in e],
                         [("DBMS", "SSS", "A1,A2", "Lab 2"), ("MP-I", "NB", "A3,A4", "Lab 1")])

    def test_teacher_after_lab_and_dash_teacher(self):
        e = parse_cell_rules("MP III A1,A2 Lab 3 (KVJ) MP III A3,A4 Lab 6 (SGB)")
        self.assertEqual([(x["teacher"], x["room"]) for x in e], [("KVJ", "Lab 3"), ("SGB", "Lab 6")])
        e = parse_cell_rules("CEE A1,A2 – SK Lab 4 EE A3, A4 – Rohit D. Lab 5")
        self.assertEqual([(x["subject"], x["teacher"], x["room"]) for x in e],
                         [("CEE", "SK", "Lab 4"), ("EE", "Rohit D.", "Lab 5")])

    def test_elective_pairs_teachers_with_rooms(self):
        e = parse_cell_rules("MDM-I (NB,DDK/Gupta) (CSAMCR 06/CSDSCR 01/CSAMCR 02)")
        self.assertEqual([(x["teacher"], x["room"]) for x in e],
                         [("NB", "CSAMCR-06"), ("DDK", "CSDSCR-01"), ("Gupta", "CSAMCR-02")])
        e = parse_cell_rules("MDM 3 (SL/KVJ/SC) ( CSAMCR 02/ 03/ 04)")
        self.assertEqual([x["room"] for x in e], ["CSAMCR-02", "CSAMCR-03", "CSAMCR-04"])
        self.assertTrue(all(x["shared"] for x in e))

    def test_rooms_and_title(self):
        self.assertEqual(find_rooms("Lab 2& 3"), ["Lab 2", "Lab 3"])
        self.assertEqual(find_rooms("SAMCR06"), ["CSAMCR-06"])
        m = parse_title("TY AIML-A CSAMCR – 03 Class Teacher – Ms. Sayali Mane")
        self.assertEqual((m["year"], m["branch"], m["division"], m["default_room"]),
                         ("Third Year (TY)", "AIML", "A", "CSAMCR-03"))
        m = parse_title("BTech DS Class Teacher – Ms. Vrushali Prabhu")
        self.assertEqual((m["year_code"], m["branch"], m["default_room"]), ("BTech", "DS", ""))


class RealPdf(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = extract_timetable(str(PDF))

    def test_classes_years_and_default_rooms(self):
        got = {c["name"]: (c["year_code"], c["default_room"]) for c in self.data["classes"]}
        self.assertEqual(len(got), 9)
        self.assertEqual(got["SY AIML-A"], ("SY", "CSAMCR-06"))
        self.assertEqual(got["SY AIML-C"], ("SY", "CSDSCR-01"))
        self.assertEqual(got["TY AIML-B"], ("TY", "CSAMCR-04"))
        self.assertEqual(got["BTech AIML-A"], ("BTech", "CSAMCR-01"))
        self.assertEqual(self.data["department"], "CSE-AIML and CSE-DS")

    def test_default_room_is_used_when_cell_has_none(self):
        sy_a = next(c for c in self.data["classes"] if c["name"] == "SY AIML-A")
        tue = [s for s in sy_a["sessions"] if s["day_name"] == "Tue" and s["subject"] == "ADS"
               and not s["batch"]][0]
        self.assertEqual((tue["start"], tue["room"], tue["room_source"], tue["teacher"]),
                         ("10:00", "CSAMCR-06", "default", "SS"))

    def test_merged_cells_become_long_sessions(self):
        sy_a = next(c for c in self.data["classes"] if c["name"] == "SY AIML-A")
        tp = [s for s in sy_a["sessions"] if s["subject"] == "T & P" and s["day_name"] == "Thu"][0]
        self.assertEqual((tp["start"], tp["end"]), ("09:00", "11:00"))
        lab = [s for s in sy_a["sessions"] if s["subject"] == "SST" and s["batch"] == "A1,A2"
               and s["day_name"] == "Tue"][0]
        self.assertEqual((lab["start"], lab["end"], lab["room"], lab["teacher"]),
                         ("14:00", "16:00", "Lab 2", "NS"))

    def test_sliver_columns_do_not_shift_days(self):
        ty_a = next(c for c in self.data["classes"] if c["name"] == "TY AIML-A")
        # BCVS/EDA labs sit in the thin extra column that belongs to Thursday
        days = {s["day_name"] for s in ty_a["sessions"] if s["subject"] == "BCVS" and s["batch"] == "A1,A2"}
        self.assertEqual(days, {"Thu"})

    def test_no_leftover_garbage_in_subjects(self):
        for c in self.data["classes"]:
            for s in c["sessions"]:
                self.assertNotIn("(", s["subject"].replace("LA (T)", ""))
                self.assertFalse(s["subject"].startswith("."))
                self.assertNotRegex(s["subject"], r"^(\S ){3,}")


class EndToEnd(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user("kit", password="pw12345")
        self.inst = Institute.objects.create(owner=user, name="KIT", slug="kit")
        self.client.login(username="kit", password="pw12345")

    def test_import_stores_year_batch_and_json(self):
        with open(PDF, "rb") as f:
            up = SimpleUploadedFile("kit.pdf", f.read(), content_type="application/pdf")
        resp = self.client.post(reverse("upload", kwargs={"slug": "kit"}), {"pdf": up})
        self.assertEqual(resp.status_code, 200)
        data = extract_timetable(str(PDF))
        unique = {(s["room"], s["day"], s["start"], s["end"], s["subject"], s["teacher"], s["batch"])
                  for c in data["classes"] for s in c["sessions"]}
        self.assertEqual(ClassSession.objects.count(), len(unique))     # nothing lost, shared once
        s = ClassSession.objects.filter(class_name="SY AIML-A", batch="A1,A2", subject="SST").first()
        self.assertEqual((s.year, s.teacher, s.room.name), ("Second Year (SY)", "NS", "Lab 2"))
        # shared elective stored once per room, not once per class page
        self.assertEqual(ClassSession.objects.filter(subject="MDM-I", room__name="CSAMCR-06",
                                                     day=1, start_time__hour=9).count(), 1)
        up_obj = self.inst.uploads.first()
        r = self.client.get(reverse("upload_json", kwargs={"slug": "kit", "pk": up_obj.pk}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(json.loads(r.content)["classes"]), 9)
        # live status carries teacher + year + batch
        import datetime
        room = s.room
        blocks = build_day([room], datetime.date(2026, 10, 20))[room.id]       # a Tuesday
        st = status_at(blocks, 14 * 60 + 30)
        self.assertEqual((st["state"], st["teacher"], st["year"], st["batch"]),
                         ("busy", "NS", "Second Year (SY)", "A1,A2"))


class LlmJson(TestCase):
    def test_valid_answer_is_accepted_and_normalised(self):
        answer = '''```json
        {"class": {"year_code": "SY", "branch": "AIML", "division": "A", "default_room": "CSAMCR 06"},
         "cells": [{"id": 0, "entries": [{"subject": "DBMS", "teacher": "SSS", "batch": "a1, a2", "room": "LAB 2"}]},
                   {"id": 1, "entries": []}]}
        ```'''
        per_cell, meta = parse_llm_json(answer, 2)
        self.assertEqual(per_cell[0][0]["room"], "Lab 2")
        self.assertEqual(per_cell[0][0]["batch"], "A1,A2")
        self.assertEqual(meta["default_room"], "CSAMCR-06")

    def test_garbage_is_rejected(self):
        with self.assertRaises(Exception):
            parse_llm_json("sorry, I cannot do that", 3)
        with self.assertRaises(ValueError):
            parse_llm_json('{"cells": []}', 5)

    def test_llm_failure_falls_back_to_rules(self):
        class Broken:
            model = "broken"

            def interpret(self, title, cells):
                raise RuntimeError("HTTP 500")
        data = extract_timetable(str(PDF), llm=Broken())
        self.assertEqual(len(data["classes"]), 9)
        self.assertTrue(any("used built-in rules" in w for w in data["warnings"]))

    def test_llm_answer_replaces_rules(self):
        class Fake:
            model = "fake-small"

            def interpret(self, title, cells):
                per = [[dict(subject="X", teacher="T", batch="", room="", shared=False)] for _ in cells]
                return per, {}
        data = extract_timetable(str(PDF), llm=Fake())
        subjects = {s["subject"] for c in data["classes"] for s in c["sessions"]}
        self.assertEqual(subjects, {"X"})
        self.assertEqual(data["extractor"], "llm:fake-small")
