from __future__ import annotations

import unittest

from backend.app.timeline.errors import TimelineImportError
from backend.app.timeline.importers import import_narration_timeline
from backend.app.timeline.normalizer import normalize_narration_events
from backend.app.timeline.parsers_srt import parse_srt
from backend.app.timeline.parsers_timestamped_txt import parse_timestamped_txt


class TimestampedParserTests(unittest.TestCase):
    def test_parse_timestamped_txt_basic(self) -> None:
        content = """
        [00:00] Intro line
        [00:03] Next line
        """
        events = parse_timestamped_txt(content)
        self.assertEqual(2, len(events))
        self.assertEqual(0, events[0]["start_ms"])
        self.assertEqual(3000, events[1]["start_ms"])
        self.assertEqual("Intro line", events[0]["text"])

    def test_parse_timestamped_txt_invalid_line_reports_line_number(self) -> None:
        content = "[00:00] good\ninvalid line\n"
        with self.assertRaises(TimelineImportError) as ctx:
            parse_timestamped_txt(content)
        self.assertEqual(2, ctx.exception.line_number)


class SrtParserTests(unittest.TestCase):
    def test_parse_srt_basic(self) -> None:
        content = """1
00:00:00,000 --> 00:00:02,500
hello world

2
00:00:03,000 --> 00:00:04,000
second block
"""
        events = parse_srt(content)
        self.assertEqual(2, len(events))
        self.assertEqual(0, events[0]["start_ms"])
        self.assertEqual(2500, events[0]["end_ms"])
        self.assertEqual("hello world", events[0]["text"])

    def test_parse_srt_invalid_timestamp_reports_line_number(self) -> None:
        content = """1
no timestamp
hello
"""
        with self.assertRaises(TimelineImportError) as ctx:
            parse_srt(content)
        self.assertEqual(2, ctx.exception.line_number)


class NormalizationTests(unittest.TestCase):
    def test_normalize_assigns_unique_ids_and_sorts(self) -> None:
        raw = [
            {"id": "n1", "start_ms": 4000, "text": "later"},
            {"id": "n1", "start_ms": 0, "text": "first"},
        ]
        normalized = normalize_narration_events(raw)
        self.assertEqual("n1", normalized[0]["id"])
        self.assertEqual("n1_1", normalized[1]["id"])
        self.assertEqual(0, normalized[0]["start_ms"])
        self.assertEqual(4000, normalized[0]["end_ms"])

    def test_normalize_raises_on_empty_text(self) -> None:
        raw = [{"id": "n1", "start_ms": 0, "text": "  ", "meta": {"source_line": 9}}]
        with self.assertRaises(TimelineImportError) as ctx:
            normalize_narration_events(raw)
        self.assertEqual(9, ctx.exception.line_number)


class ImportServiceTests(unittest.TestCase):
    def test_import_auto_detects_srt(self) -> None:
        content = """1
00:00:00,000 --> 00:00:02,000
line one
"""
        timeline = import_narration_timeline(content, import_format="auto", source_name="script.srt")
        self.assertEqual(1, len(timeline.narration_events))
        self.assertEqual("line one", timeline.narration_events[0].text)

    def test_import_json_pass_through(self) -> None:
        content = """{
  "timeline_version": "1.0",
  "narration_events": [{"id":"n1","start_ms":0,"end_ms":1000,"text":"hi"}],
  "action_events": [{"id":"a1","at_ms":0,"action":"goto","args":{"url":"https://example.com","x":1}}]
}"""
        timeline = import_narration_timeline(content, import_format="json")
        self.assertEqual(1, len(timeline.action_events))
        self.assertEqual(1, timeline.action_events[0].args["x"])

    def test_import_txt_infers_end_ms(self) -> None:
        content = "[00:00] first\n[00:02] second\n"
        timeline = import_narration_timeline(content, import_format="timestamped_txt")
        self.assertEqual(2, len(timeline.narration_events))
        self.assertEqual(2000, timeline.narration_events[0].end_ms)


if __name__ == "__main__":
    unittest.main()
