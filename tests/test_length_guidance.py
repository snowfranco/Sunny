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
        # Recovery requires BOTH the expand order and the previous draft in
        # the prompt: this pins the orchestrator passing the failed text
        # back so retries edit instead of cold-regenerating. (Stored drafts
        # are stripped, so compare against the stripped text.)
        if "failed on LENGTH" in user and self.SHORT.strip() in user:
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

    def test_word_overshoot_orders_a_cut_not_an_expand(self):
        conn, note, essay = self._fixture()
        angles = angle_engine.generate_angles(conn, note)
        linkedin = [a for a in angles if a.format == "linkedin_post"][0]
        client = _CapturingClient()
        writer.write_draft(conn, linkedin, note, client, post_id="p",
                           revision=1,
                           feedback="length_bounds: 256 words (bound 100-200 "
                                    "for linkedin_post)")
        self.assertIn("CUT it to about 133 words", client.prompts[0])
        self.assertNotIn("Expand every section", client.prompts[0])

    def test_word_undershoot_still_orders_expansion(self):
        conn, note, essay = self._fixture()
        client = _CapturingClient()
        writer.write_draft(conn, essay, note, client, post_id="p", revision=1,
                           feedback="length_bounds: 256 words (bound 400-900 "
                                    "for substack_essay)")
        self.assertIn("Expand every section", client.prompts[0])
        self.assertNotIn("CUT it", client.prompts[0])

    def test_lingo_failure_orders_plain_language_rewrite(self):
        conn, note, essay = self._fixture()
        client = _CapturingClient()
        writer.write_draft(conn, essay, note, client, post_id="p", revision=1,
                           feedback="no_performed_lingo: banned lingo: "
                                    "['the future of', \"'leverages' used as a verb\"]")
        self.assertIn("banned words named above must go", client.prompts[0])
        self.assertIn("Do not swap in different buzzwords", client.prompts[0])

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


class TestFormatBriefs(unittest.TestCase):
    def test_every_format_has_a_brief(self):
        self.assertEqual(set(writer.FORMAT_BRIEFS), set(S.FORMATS))

    def test_brief_lands_in_prompt_and_social_forbids_essay_furniture(self):
        conn = _conn()
        note = capture.capture_manual(conn, "format brief test")
        angles = angle_engine.generate_angles(conn, note)
        social = [a for a in angles if a.format == "social_copy"][0]
        client = _CapturingClient()
        writer.write_draft(conn, social, note, client)
        self.assertIn("FORMAT BRIEF:", client.prompts[0])
        self.assertIn("1 TO 3 SENTENCES", client.prompts[0])
        self.assertNotIn("throwaway line:", client.prompts[0].split("FORMAT BRIEF:")[1][:600].lower())

    def test_sentence_overshoot_feedback_orders_the_cap(self):
        conn = _conn()
        note = capture.capture_manual(conn, "overshoot test")
        angles = angle_engine.generate_angles(conn, note)
        social = [a for a in angles if a.format == "social_copy"][0]
        client = _CapturingClient()
        writer.write_draft(conn, social, note, client, post_id="p", revision=1,
                           feedback="length_bounds: 7 sentences (bound 1-3 "
                                    "for social_copy)")
        self.assertIn("1 to 3 sentences TOTAL", client.prompts[0])
        self.assertIn("at most 3 sentences", client.prompts[0])


class _OverWriter(llm.LLMClient):
    """Writes 7 sentences for social copy until the retry prompt carries the
    explicit sentence cap, then complies. The llama3.1:8b overshoot mode."""

    LONG = ("I built the thing. It worked. Then it broke. I fixed it again. "
            "The lesson was clear. I keep thinking about it. What a week.")

    def __init__(self):
        super().__init__("t")

    def complete_text(self, kind, system, user, max_tokens=2048):
        if "sentences TOTAL" in user:
            return ("The hard part was free and the free part was hard. "
                    "Not sure yet which estimate to stop trusting.")
        return self.LONG

    def complete_json(self, kind, system, user, max_tokens=2048):
        return llm._mock_json(kind, user)


class TestOverWriterRecoversWithinCap(unittest.TestCase):
    def test_seven_sentence_social_passes_on_first_retry(self):
        conn = _conn()
        note = capture.capture_manual(conn, "overwriter recovery test")
        angles = angle_engine.generate_angles(conn, note)
        social = [a for a in angles if a.format == "social_copy"][0]
        client = _OverWriter()
        verdict = orchestrator.run_review_loop(conn, social, note, client, "r")
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.revision_count, 1)


class _NoGistWriter(llm.LLMClient):
    """Writes a fine essay but forgets the gist line, like an 8B model
    juggling too many instructions. The gist call itself succeeds."""

    def __init__(self):
        super().__init__("t")
        self.gist_calls = 0

    def complete_text(self, kind, system, user, max_tokens=2048):
        if kind == "gist":
            self.gist_calls += 1
            return "> Covered here: the test build and its reviewer loop."
        full = llm._mock_draft(user, "nogist")
        return full.split("\n\n", 1)[1]  # body without the gist line

    def complete_json(self, kind, system, user, max_tokens=2048):
        return llm._mock_json(kind, user)


class TestGistLineOwnership(unittest.TestCase):
    def _fixture(self):
        conn = _conn()
        note = capture.capture_manual(conn, "gist ownership test")
        angles = angle_engine.generate_angles(conn, note)
        return conn, note, angles

    def test_missing_gist_is_added_by_dedicated_step(self):
        conn, note, angles = self._fixture()
        essay = [a for a in angles if a.format == "substack_essay"][0]
        client = _NoGistWriter()
        draft = writer.write_draft(conn, essay, note, client)
        self.assertTrue(draft.draft_text.startswith("> Covered here:"))
        self.assertEqual(client.gist_calls, 1)
        # and the whole review now passes despite the forgetful writer
        verdict = orchestrator.run_review_loop(conn, essay, note, client, "r")
        self.assertTrue(verdict.passed)

    def test_existing_gist_is_kept_no_extra_call(self):
        conn, note, angles = self._fixture()
        essay = [a for a in angles if a.format == "substack_essay"][0]
        client = _NoGistWriter()
        text = writer._ensure_gist_line(
            client, essay, note, "> My own gist line.\n\nBody starts here.")
        self.assertTrue(text.startswith("> My own gist line."))
        self.assertEqual(client.gist_calls, 0)

    def test_non_substack_formats_untouched(self):
        conn, note, angles = self._fixture()
        social = [a for a in angles if a.format == "social_copy"][0]
        client = llm.LLMClient("t")
        draft = writer.write_draft(conn, social, note, client)
        self.assertFalse(draft.draft_text.startswith(">"))

    def test_gist_llm_failure_falls_back_to_title(self):
        conn, note, angles = self._fixture()
        essay = [a for a in angles if a.format == "substack_essay"][0]

        class _Broken(llm.LLMClient):
            def complete_text(self, kind, system, user, max_tokens=2048):
                raise llm.LLMError("gist model down")

        text = writer._ensure_gist_line(_Broken("t"), essay, note, "Body only.")
        self.assertTrue(text.startswith(f"> Covered here: {essay.title}."))


class TestVerbHitsNameTheWord(unittest.TestCase):
    def test_fail_note_names_the_matched_word_not_the_regex(self):
        from pipeline import reviewer
        items = reviewer.check_banned_patterns("We can leverage this properly.")
        note = [c for c in items if c.criterion == "no_performed_lingo"][0].note
        self.assertIn("'leverage", note)
        self.assertIn("used as a verb", note)
        self.assertNotIn("\\b", note)


class _VerboseLinkedInWriter(llm.LLMClient):
    """Writes a 256-word LinkedIn post until told to CUT, then complies.
    The overshoot mode from Snow's live run."""

    LONG = ("I have been sitting with something after this build. " * 2
            + ("The part I expected to be hard was done in an afternoon and "
               "the part I expected to be free took the rest of the week, "
               "which keeps happening in the same direction every time. " * 8)
            + "What does your error keep telling you?")

    def complete_text(self, kind, system, user, max_tokens=2048):
        if "CUT it to about" in user:
            return llm._mock_draft(user, "trimmed")  # in-bounds linkedin mock
        return self.LONG

    def complete_json(self, kind, system, user, max_tokens=2048):
        return llm._mock_json(kind, user)


class TestOverWriterLinkedInRecovers(unittest.TestCase):
    def test_overlong_post_passes_after_cut_order(self):
        conn = _conn()
        note = capture.capture_manual(conn, "linkedin overshoot recovery")
        angles = angle_engine.generate_angles(conn, note)
        linkedin = [a for a in angles if a.format == "linkedin_post"][0]
        client = _VerboseLinkedInWriter("t")
        verdict = orchestrator.run_review_loop(conn, linkedin, note, client, "r")
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.revision_count, 1)


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
