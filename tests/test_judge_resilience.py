"""A malformed judge reply is a transport problem, not an editorial
verdict: one re-ask before the fallback fail, without touching the
writer retry cap."""

import os
import unittest

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import llm, reviewer


class _FlakyJudge(llm.LLMClient):
    """Returns garbage on the first review call, a valid checklist on the
    re-ask."""

    def __init__(self, garbage_replies: int):
        super().__init__("t")
        self.garbage_left = garbage_replies
        self.calls = 0

    def complete_json(self, kind, system, user, max_tokens=2048):
        self.calls += 1
        if self.garbage_left > 0:
            self.garbage_left -= 1
            return {"note": "not a checklist"}
        return [{"criterion": "voice_match", "passed": True, "note": "fine"}]


class TestJudgeReask(unittest.TestCase):
    def test_one_garbage_reply_recovers_via_reask(self):
        client = _FlakyJudge(garbage_replies=1)
        items = reviewer.judge_subjective("draft", "build_in_public",
                                          "linkedin_post", "note", client)
        self.assertEqual(client.calls, 2)
        self.assertTrue(items[0].passed)

    def test_persistent_garbage_fails_with_doctor_hint(self):
        client = _FlakyJudge(garbage_replies=2)
        items = reviewer.judge_subjective("draft", "build_in_public",
                                          "linkedin_post", "note", client)
        self.assertEqual(client.calls, 2)  # exactly one re-ask, bounded
        self.assertFalse(items[0].passed)
        self.assertIn("doctor", items[0].note)

    def test_non_dict_entries_skipped(self):
        self.assertEqual(reviewer._judge_items(["a string", 42]), [])
        items = reviewer._judge_items(
            [{"criterion": "x", "passed": True, "note": ""}, "junk"])
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
