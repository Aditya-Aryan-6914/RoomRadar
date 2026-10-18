"""python manage.py parse_timetable samples/KIT_AIML_DS_2026-27_timetable.pdf --out parsed.json

Reads a timetable PDF and writes the structured JSON (classes, years, default rooms, sessions with
subject / teacher / batch / room). Uses the small LLM from settings.TIMETABLE_LLM when configured,
otherwise the built-in rules. Use --rules to force the rules.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from facilities.llm import get_llm
from facilities.timetable_extract import extract_timetable


class Command(BaseCommand):
    help = "Read a timetable PDF and write the structured JSON."

    def add_arguments(self, parser):
        parser.add_argument("pdf")
        parser.add_argument("--out", help="JSON file to write (default: print to the screen)")
        parser.add_argument("--rules", action="store_true", help="do not use the LLM even if configured")

    def handle(self, *args, **opts):
        llm = None if opts["rules"] else get_llm()
        try:
            data = extract_timetable(opts["pdf"], llm=llm)
        except FileNotFoundError:
            raise CommandError(f"File not found: {opts['pdf']}")
        text = json.dumps(data, ensure_ascii=False, indent=2)
        if opts["out"]:
            with open(opts["out"], "w", encoding="utf-8") as f:
                f.write(text)
        else:
            self.stdout.write(text)
        n = sum(len(c["sessions"]) for c in data["classes"])
        self.stderr.write(self.style.SUCCESS(
            f"{len(data['classes'])} classes, {n} sessions, read by {data['extractor']}"
            + (f" -> {opts['out']}" if opts["out"] else "")))
        for w in data["warnings"]:
            self.stderr.write(self.style.WARNING(w))
