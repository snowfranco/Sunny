"""Length guidance: the writer prompt states the bound numerically, and a
length failure turns into an explicit expand instruction on retry, so an
under-writing model (the llama3.1:8b failure mode) recovers within the
existing 2-retry cap instead of escalating."""

import os
import sqlite3
import unittest

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import angle_engine, capture, db, llm, orchestrator, writer
from pipeline import schemas as S


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


class _CapturingClient(llm.LLMClient):
    """Records prompts; returns canned mock output."""

    def __init__(self):
        super().__init__("t")
        self.prompts = []

    def complete_text(self, kind, system, user, max_tokens=2048):
        self.prompts.append(user)
        return llm._mock_text("draft", user)


class _UnderWriter(llm.LLMClient):
    """Writes 268 words until the prompt carries the explicit expand
    instruction, then writes full length. Mimics a small local model."""

    SHORT = ("> Gist line naming sunny and the reviewer loop.\n\n"
             + ("A sentence with enough words to stay out of fragment "
                "territory while the total stays short. " * 24))

    def __init__(self):
        super().__init__("t")
        self.calls = 0

    def complete_text(self, kind, system, user, max_tokens=2048):
        self.calls += 1
        if "failed on LENGTH" in user:
            return llm._mock_draft(user, "expanded")  # full-length mock essay
        return self.SHORT

    def complete_json(self, kind, system, user, max_tokens=2048):
        return llm._mock_json(kind, user)


class TestLengthGuidanceInPrompts(unittest.TestCase):
    def _fixture(self):
        conn = _conn()
        note = capture.capture_manual(conn, "length guidance test")
        angles = angle_engine.generate_angles(conn, note)
        essay = [a for a in angles if a.format == "substack_essay"][0]
        return conn, note, essay

    def test_initial_prompt_states_numeric_bound(self):
        conn, note, essay = self._fixture()
        client = _CapturingClient()
        writer.write_draft(conn, essay, note, client)
        self.assertIn("between 400 and 900 words", client.prompts[0])
        self.assertIn("Aim for about", client.prompts[0])

    def test_length_failure_feedback_orders_expansion(self):
        conn, note, essay = self._fixture()
        client = _CapturingClient()
        writer.write_draft(conn, essay, note, client, post_id="p", revision=1,
                           feedback="length_bounds: 268 words (bound 400-900 "
                                    "for substack_essay)")
        self.assertIn("failed on LENGTH", client.prompts[0])
        self.assertIn("at least 400 words", client.prompts[0])

    def test_non_length_feedback_gets_no_length_order(self):
        conn, note, essay = self._fixture()
        client = _CapturingClient()
        writer.write_draft(conn, essay, note, client, post_id="p", revision=1,
                           feedback="no_em_dashes: em dash found")
        self.assertNotIn("failed on LENGTH", client.prompts[0])

    def test_sentence_bound_formats_state_the_cap(self):
        self.assertIn("1 to 3 sentences", writer._length_guidance("social_copy"))
        self.assertEqual(writer._length_guidance("script"), "")

    def test_edit_revision_keeps_length_requirement(self):
        conn, note, essay = self._fixture()
        real = llm.LLMClient("t")
        d = writer.write_draft(conn, essay, note, real)
        client = _CapturingClient()
        writer.revise_for_edit(conn, d, "cut the second paragraph", client, 1)
        self.assertIn("between 400 and 900 words", client.prompts[0])


class TestUnderWriterRecoversWithinCap(unittest.TestCase):
    def test_short_draft_passes_on_first_retry(self):
        conn = _conn()
        note = capture.capture_manual(conn, "underwriter recovery test")
        angles = angle_engine.generate_angles(conn, note)
        essay = [a for a in angles if a.format == "substack_essay"][0]
        client = _UnderWriter()
        verdict = orchestrator.run_review_loop(conn, essay, note, client, "r")
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.revision_count, 1)  # short, then expanded
        self.assertLessEqual(verdict.revision_count, S.MAX_REVIEWER_RETRIES)


if __name__ == "__main__":
    unittest.main()
