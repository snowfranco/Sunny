"""DB round-trips: what goes in as a schema comes out as a schema."""

import sqlite3
import unittest

from pipeline import db
from pipeline import schemas as S


class TestDbRoundTrip(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_note_roundtrip(self):
        n = S.CaptureNote(note_id=S.new_id(), source="manual",
                          raw_text="text", created_at=S.now_iso())
        db.save_note(self.conn, n)
        got = db.get_note(self.conn, n.note_id)
        self.assertEqual(got.to_dict(), n.to_dict())

    def test_angle_roundtrip(self):
        n = S.CaptureNote(note_id=S.new_id(), source="manual",
                          raw_text="text", created_at=S.now_iso())
        db.save_note(self.conn, n)
        a = S.AngleOption(note_id=n.note_id, angle_id=S.new_id(),
                          pillar="transition_story", format="linkedin_post",
                          title="t", hook="h", strategic_rationale="long_term_bet",
                          rationale="r")
        db.save_angle(self.conn, a)
        self.assertEqual(db.get_angle(self.conn, a.angle_id).to_dict(), a.to_dict())
        self.assertEqual(len(db.list_angles_for_note(self.conn, n.note_id)), 1)

    def test_export_bundle_check_constraint_in_sql(self):
        # Even a raw SQL insert bypassing the schema layer cannot store a
        # non-draft bundle.
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO export_bundles VALUES "
                "('p','published','t','e','h',NULL,NULL,'build_in_public','now')")

    def test_run_log_and_turn_count(self):
        from pipeline.runlog import log_step
        log_step(self.conn, run_id="r1", step="writer", ref_id="p1",
                 pass_fail=None)
        log_step(self.conn, run_id="r1", step="reviewer", ref_id="p1",
                 pass_fail=False)
        rows = self.conn.execute("SELECT * FROM pipeline_run_log").fetchall()
        self.assertEqual(len(rows), 2)

        t = S.RefinementTurn(session_id="s1", turn_number=1, speaker="you",
                             message="combine 2 and 3",
                             resulting_angle_or_draft_id=None,
                             timestamp=S.now_iso())
        db.save_refinement_turn(self.conn, t, kind="angle")
        self.assertEqual(db.refinement_turn_count(self.conn, "s1"), 1)


if __name__ == "__main__":
    unittest.main()
