"""Reviewer mechanics, the bounded judge loop, and the edit stage."""

import os
import sqlite3
import unittest

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import capture, db, llm, orchestrator, refinement, reviewer
from pipeline import angle_engine
from pipeline import schemas as S


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def _fails(items):
    return [c.criterion for c in items if not c.passed]


GOOD_LINKEDIN = (
    "I have been sitting with something after the reviewer build this week.\n\n"
    "The bounded loop failed my draft twice on Tuesday, and the second "
    "failure was the useful one because it named a conclusion that resolved "
    "too cleanly. I would have shipped that exact sentence without noticing, "
    "and honestly the machine catching my own writing tic before it caught "
    "the model's felt backwards in a genuinely instructive way.\n\n"
    "I'm not sure if you'd agree, but a reviewer that fails fast with a named "
    "reason reads more like a colleague than a gate. Where does that leave "
    "the morning reread I have done for fifteen years?"
)


class TestMechanicalChecks(unittest.TestCase):
    def test_clean_text_passes(self):
        items = reviewer.mechanical_checklist(GOOD_LINKEDIN, "linkedin_post")
        self.assertEqual(_fails(items), [])

    def test_em_dash_caught(self):
        items = reviewer.check_banned_patterns("A thought — with an em dash.")
        self.assertIn("no_em_dashes", _fails(items))

    def test_performed_lingo_caught(self):
        for phrase in ("this is a game-changer", "we can leverage this",
                       "unlocks new value", "a paradigm shift",
                       "the future of work", "truly transformative"):
            items = reviewer.check_banned_patterns(phrase)
            self.assertIn("no_performed_lingo", _fails(items), phrase)
        # 'unlock' as a noun-ish compound or 'leverage' as noun is fine
        items = reviewer.check_banned_patterns(
            "the door had an unlocked feel and financial leverage is a noun here")
        self.assertNotIn("no_performed_lingo", _fails(items))

    def test_signpost_caught(self):
        items = reviewer.check_banned_patterns(
            "We shipped it. Here's where it gets interesting. The data moved.")
        self.assertIn("no_signpost_sentences", _fails(items))

    def test_not_x_but_y_caught(self):
        for s in ("This is not about scaling, it's about judgment.",
                  "This isn't just better tooling; it's a different job.",
                  "It works not only for teams but also for solo builders."):
            items = reviewer.check_banned_patterns(s)
            self.assertIn("no_not_x_but_y", _fails(items), s)

    def test_plain_contrastive_but_is_not_flagged(self):
        # "not X, but Y" as a genuine contrast is on-voice and must pass;
        # only the "not X, it's Y" / "not only X but Y" pivots are banned.
        for s in ("This is not something I planned, but I learned from it.",
                  "That didn't work out as expected, but here's what I learned.",
                  "The tool is not perfect, but it earned its place."):
            items = reviewer.check_banned_patterns(s)
            self.assertNotIn("no_not_x_but_y", _fails(items), s)

    def test_fragment_rhythm_caught(self):
        frag = ("AI removes bottlenecks. But not all bottlenecks. "
                "The judgment one? Still yours. This changes everything. "
                "After that stack, a normally sized sentence arrives to close.")
        items = reviewer.check_banned_patterns(frag)
        self.assertIn("no_fragmented_rhythm", _fails(items))
        self.assertNotIn("no_fragmented_rhythm",
                         _fails(reviewer.check_banned_patterns(GOOD_LINKEDIN)))

    def test_length_bounds(self):
        short = reviewer.check_length_bounds("too short", "linkedin_post")
        self.assertFalse(short.passed)
        ok = reviewer.check_length_bounds(GOOD_LINKEDIN, "linkedin_post")
        self.assertTrue(ok.passed, ok.note)
        social = reviewer.check_length_bounds("One thought. Maybe two.", "social_copy")
        self.assertTrue(social.passed)

    def test_aeo_gist_required_for_substack_only(self):
        no_gist = "Body starts here mid-argument and keeps going."
        self.assertFalse(reviewer.check_aeo_gist(no_gist, "substack_essay").passed)
        with_quote = "> Covered here: sunny, SQLite, judge loops.\n\nBody starts."
        self.assertTrue(reviewer.check_aeo_gist(with_quote, "substack_essay").passed)
        with_italic = "*Covered here: sunny, SQLite, judge loops.*\n\nBody starts."
        self.assertTrue(reviewer.check_aeo_gist(with_italic, "substack_essay").passed)
        self.assertTrue(reviewer.check_aeo_gist(no_gist, "linkedin_post").passed)

    def test_copyright_hygiene(self):
        long_quote = ('She said "' + " ".join(["word"] * 20) + '" and left.')
        self.assertFalse(reviewer.check_copyright_hygiene(long_quote).passed)
        short_quote = 'She said "done is a decision" and left.'
        self.assertTrue(reviewer.check_copyright_hygiene(short_quote).passed)

    def test_publish_claim_caught(self):
        item = reviewer.check_no_publish_claim("This was posted to substack today.")
        self.assertFalse(item.passed)


class _BadDraftClient(llm.LLMClient):
    """A writer that never learns: every draft contains an em dash."""

    def complete_text(self, kind, system, user, max_tokens=2048):
        return ("> Gist line for the essay, naming sunny and SQLite.\n\n"
                "A draft — with a stubborn em dash that survives feedback. "
                + "It keeps a reasonable sentence length going so only the dash fails. " * 30)

    def complete_json(self, kind, system, user, max_tokens=2048, schema=None):
        return llm._mock_json(kind, user)


class TestBoundedReviewLoop(unittest.TestCase):
    def _setup(self):
        conn = _conn()
        note = capture.capture_manual(conn, "built the bounded judge loop")
        angles = angle_engine.generate_angles(conn, note)
        essay = [a for a in angles if a.format == "substack_essay"][0]
        return conn, note, essay

    def test_good_draft_passes_first_try(self):
        conn, note, essay = self._setup()
        client = llm.LLMClient("t")
        verdict = orchestrator.run_review_loop(conn, essay, note, client, "run1")
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.revision_count, 0)

    def test_escalates_after_exactly_two_retries_with_reason(self):
        conn, note, essay = self._setup()
        client = _BadDraftClient("t")
        with self.assertRaises(orchestrator.EscalationRequired) as ctx:
            orchestrator.run_review_loop(conn, essay, note, client, "run2")
        self.assertIn("no_em_dashes", ctx.exception.fail_reason)
        # 3 reviews (initial + 2 retries), 3 writer calls, all logged
        rows = conn.execute(
            "SELECT step, pass_fail FROM pipeline_run_log WHERE run_id='run2'"
        ).fetchall()
        steps = [r["step"] for r in rows]
        self.assertEqual(steps.count("reviewer"), S.MAX_REVIEWER_RETRIES + 1)
        self.assertEqual(steps.count("writer"), S.MAX_REVIEWER_RETRIES + 1)
        verdicts = conn.execute("SELECT passed FROM reviewer_verdicts").fetchall()
        self.assertEqual([v["passed"] for v in verdicts], [0, 0, 0])


class TestEditStage(unittest.TestCase):
    def _reviewed_post(self):
        conn = _conn()
        note = capture.capture_manual(conn, "topic for editing")
        angles = angle_engine.generate_angles(conn, note)
        essay = [a for a in angles if a.format == "substack_essay"][0]
        client = llm.LLMClient("t")
        verdict = orchestrator.run_review_loop(conn, essay, note, client, "run3")
        return conn, verdict.post_id

    def test_edit_request_creates_new_revision(self):
        conn, post_id = self._reviewed_post()
        before = db.get_latest_draft(conn, post_id).draft_text
        session = orchestrator.edit_session_for(conn, post_id)
        revised = orchestrator.apply_edit_request(
            conn, post_id, "exclude the paragraph about the kitchen table", session)
        self.assertEqual(revised.post_id, post_id)
        self.assertNotEqual(revised.draft_text, before)
        self.assertEqual(db.next_revision(conn, post_id), 2)

    def test_edit_cap_forces_decision(self):
        conn, post_id = self._reviewed_post()
        session = orchestrator.edit_session_for(conn, post_id)
        for i in range(S.MAX_REFINEMENT_TURNS):
            orchestrator.apply_edit_request(conn, post_id, f"change {i}", session)
        with self.assertRaises(refinement.RefinementCapReached):
            orchestrator.apply_edit_request(conn, post_id, "one more", session)

    def test_approve_records_edited_post_and_manual_override_wins(self):
        conn, post_id = self._reviewed_post()
        edited = orchestrator.approve_post(conn, post_id,
                                           final_text="my hand-edited final")
        self.assertEqual(edited.final_text, "my hand-edited final")
        self.assertEqual(db.get_edited_post(conn, post_id).final_text,
                         "my hand-edited final")

    def test_full_run_pipeline_status(self):
        conn = _conn()
        note = capture.capture_manual(conn, "full pipeline smoke")
        angles = angle_engine.generate_angles(conn, note)
        essay = [a for a in angles if a.format == "substack_essay"][0]
        result = orchestrator.run_pipeline(conn, essay.angle_id)
        self.assertEqual(result["status"], "awaiting_edit")
        self.assertIn("edit", result["next"])


if __name__ == "__main__":
    unittest.main()
