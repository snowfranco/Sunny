"""Capture, researcher, angle engine, and the bounded refinement loop.
Everything runs in mock mode (no API key, no network)."""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import angle_engine, capture, db, llm, refinement, researcher
from pipeline import schemas as S
from pipeline.config import Config


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


class TestCapture(unittest.TestCase):
    def test_manual_capture(self):
        conn = _conn()
        n = capture.capture_manual(conn, "  shipped the reviewer loop  ")
        self.assertEqual(n.raw_text, "shipped the reviewer loop")
        self.assertEqual(db.get_note(conn, n.note_id).source, "manual")

    def test_inbox_split_and_ingest(self):
        chunks = capture._split_inbox(
            "first paragraph note\n\n- bullet one\n- bullet two\n\nsecond paragraph\n")
        self.assertEqual(chunks,
                         ["first paragraph note", "bullet one", "bullet two",
                          "second paragraph"])
        with tempfile.TemporaryDirectory() as td:
            inbox = Path(td) / "inbox.md"
            inbox.write_text("a note from my phone\n\n- and a bullet\n")
            cfg = Config(inbox_path=str(inbox), data_dir=td)
            conn = _conn()
            notes = capture.ingest_inbox(conn, cfg)
            self.assertEqual(len(notes), 2)
            # second pass captures nothing (marker only)
            self.assertEqual(capture.ingest_inbox(conn, cfg), [])
            self.assertIn("sunny: ingested", inbox.read_text())


class TestResearcher(unittest.TestCase):
    def test_project_scan_reads_only_known_docs_and_never_writes(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "claudegauge"
            proj.mkdir()
            (proj / "ROADMAP.md").write_text("## Q3\nShip the usage meter")
            (proj / "notes.txt").write_text("should be ignored")
            before = {p: p.read_text() for p in proj.iterdir()}
            cfg = Config(project_paths=[str(proj)], data_dir=td)
            conn = _conn()
            notes = researcher.scan_project_docs(conn, cfg)
            self.assertEqual(len(notes), 1)
            self.assertIn("claudegauge/ROADMAP.md", notes[0].raw_text)
            self.assertEqual(notes[0].source, "project_scan")
            after = {p: p.read_text() for p in proj.iterdir()}
            self.assertEqual(before, after)  # read-only, guaranteed

    def test_landscape_scan_requires_sources(self):
        conn = _conn()
        notes = researcher.scan_landscape(conn, llm.LLMClient("t"))
        self.assertGreater(len(notes), 0)
        for n in notes:
            self.assertEqual(n.source, "landscape_scan")
            self.assertTrue(n.source_url.startswith("http"))

    def test_research_writes_suggestions_file(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_dir=td)
            conn = _conn()
            payload = researcher.research(conn, cfg, llm.LLMClient("t"))
            self.assertTrue(cfg.suggestions_file.exists())
            self.assertIn("landscape_suggestions", payload)


class TestAngleEngine(unittest.TestCase):
    def test_generates_three_validated_angles(self):
        conn = _conn()
        note = capture.capture_manual(conn, "built the bounded judge loop")
        angles = angle_engine.generate_angles(conn, note)
        self.assertEqual(len(angles), 3)
        for a in angles:
            self.assertIn(a.pillar, S.PILLARS)
            self.assertIn(a.format, S.FORMATS)
            self.assertIn(a.strategic_rationale, S.STRATEGIC_RATIONALES)
        self.assertEqual(len(db.list_angles_for_note(conn, note.note_id)), 3)

    def test_refine_and_pick(self):
        conn = _conn()
        note = capture.capture_manual(conn, "topic")
        angles = angle_engine.generate_angles(conn, note)
        revised = angle_engine.refine_angle(conn, angles[0], "angle it for solo builders")
        self.assertEqual(revised.note_id, note.note_id)
        self.assertNotEqual(revised.angle_id, angles[0].angle_id)
        picked = angle_engine.pick_angle(conn, revised)
        self.assertEqual(picked.angle_id, revised.angle_id)


class TestRefinementLoop(unittest.TestCase):
    def test_five_turn_cap_then_forced_decision(self):
        conn = _conn()
        s = refinement.start_session(conn, "angle")
        for i in range(S.MAX_REFINEMENT_TURNS):
            s.user_turn(f"tweak {i}")
            s.engine_turn(f"revision {i}")
        self.assertTrue(s.cap_reached)
        self.assertEqual(s.turns_remaining, 0)
        with self.assertRaises(refinement.RefinementCapReached) as ctx:
            s.user_turn("one more tiny thing")
        self.assertIn("lock this in", str(ctx.exception))

    def test_history_orders_speakers_within_turn(self):
        conn = _conn()
        s = refinement.start_session(conn, "edit")
        s.user_turn("exclude the paragraph about X")
        s.engine_turn("done", resulting_id="draft-2")
        h = s.history()
        self.assertEqual([t["speaker"] for t in h], ["you", "engine"])
        self.assertEqual(h[1]["kind"], "edit")


class TestTokenCeiling(unittest.TestCase):
    def test_ceiling_raises(self):
        os.environ["PIPELINE_MAX_TOKENS_PER_RUN"] = "10"
        try:
            client = llm.LLMClient("t")
            with self.assertRaises(llm.TokenCeilingExceeded):
                client.complete_text("draft", "sys", "x" * 4000)
        finally:
            del os.environ["PIPELINE_MAX_TOKENS_PER_RUN"]


if __name__ == "__main__":
    unittest.main()
