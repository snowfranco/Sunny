"""Analytics paste-in, growth aggregation, reviewer health, context log."""

import os
import sqlite3
import tempfile
import unittest
from unittest import mock

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import analytics, db, growth, llm
from pipeline import schemas as S
from pipeline.config import Config
from pipeline.runlog import log_step


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def _seed_post(conn, post_id: str, pillar: str):
    w = S.WriterOutput(post_id=post_id, angle_id="a", pillar=pillar,
                       format="substack_essay", draft_text="text",
                       voice_context_version="v", generated_at=S.now_iso())
    db.save_writer_output(conn, w)


class TestAnalytics(unittest.TestCase):
    def test_add_and_query_snapshot(self):
        conn = _conn()
        snap = analytics.add_snapshot(conn, "p1", "substack",
                                      views=900, likes=30, comments=5,
                                      shares=2, days_since_publish=7)
        self.assertEqual(snap.platform, "substack")
        import datetime
        today = datetime.date.today().isoformat()
        got = analytics.snapshots_between(conn, today, today)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].views, 900)

    def test_platform_validated(self):
        conn = _conn()
        with self.assertRaises(S.SchemaError):
            analytics.add_snapshot(conn, "p1", "tiktok", 1, 1, 1, 1, 1)


class TestGrowthReport(unittest.TestCase):
    def test_report_aggregates_and_persists(self):
        conn = _conn()
        _seed_post(conn, "p1", "build_in_public")
        _seed_post(conn, "p2", "ai_for_shippers")
        analytics.add_snapshot(conn, "p1", "substack", 1000, 50, 10, 5, 7)
        analytics.add_snapshot(conn, "p1", "linkedin", 400, 25, 4, 1, 7)
        analytics.add_snapshot(conn, "p2", "linkedin", 100, 3, 0, 0, 7)
        log_step(conn, "r1", "reviewer", "p1", output_ref="pass", pass_fail=True)
        log_step(conn, "r2", "reviewer", "p2",
                 output_ref="no_em_dashes: em dash found", pass_fail=False)

        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_dir=td)
            with mock.patch.object(growth, "load_config", return_value=cfg):
                report = growth.generate_report(conn, client=llm.LLMClient("t"))
            files = list((cfg.data_path / "reports").iterdir())
            self.assertEqual(len(files), 1)

        self.assertEqual(report.top_performers[0], "p1")
        self.assertIn("2 snapshot(s)", report.pillar_performance["build_in_public"])
        self.assertEqual(report.pillar_performance["transition_story"],
                         "no data this period")
        self.assertTrue(report.trend_notes)
        rows = conn.execute("SELECT COUNT(*) AS n FROM growth_reports").fetchone()
        self.assertEqual(rows["n"], 1)

    def test_reviewer_pass_stats(self):
        conn = _conn()
        log_step(conn, "r1", "reviewer", "p1", output_ref="pass", pass_fail=True)
        log_step(conn, "r1", "reviewer", "p1",
                 output_ref="no_em_dashes: found; length_bounds: 90 words",
                 pass_fail=False)
        import datetime
        today = datetime.date.today().isoformat()
        stats = growth.reviewer_pass_stats(conn, today, today)
        self.assertEqual(stats["reviews"], 2)
        self.assertEqual(stats["pass_rate"], 0.5)
        self.assertIn("no_em_dashes", stats["repeated_failure_reasons"])
        self.assertIn("length_bounds", stats["repeated_failure_reasons"])


class TestContextUpdate(unittest.TestCase):
    def test_recorded_with_snow_approval(self):
        conn = _conn()
        entry = growth.record_context_update(
            conn, ["context/brand-voice.md"], "tightened the lingo list")
        self.assertEqual(entry.approved_by, "snow")
        row = conn.execute("SELECT * FROM context_update_logs").fetchone()
        self.assertIn("brand-voice", row["changed_files_json"])


if __name__ == "__main__":
    unittest.main()
