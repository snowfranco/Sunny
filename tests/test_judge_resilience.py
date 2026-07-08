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

    def complete_json(self, kind, system, user, max_tokens=2048, schema=None):
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

    def test_fail_note_carries_the_raw_model_reply(self):
        class _ProseJudge(llm.LLMClient):
            def complete_json(self, kind, system, user, max_tokens=2048,
                              schema=None):
                self.last_raw_reply = "Sure! The draft looks great overall."
                return {"summary": "looks great"}  # no verdicts

        items = reviewer.judge_subjective("draft", "build_in_public",
                                          "linkedin_post", "note", _ProseJudge("t"))
        self.assertFalse(items[0].passed)
        self.assertIn("looks great", items[0].note)
        self.assertIn("--judge", items[0].note)

    def test_non_dict_entries_skipped(self):
        self.assertEqual(reviewer._judge_items(["a string", 42]), [])
        items = reviewer._judge_items(
            [{"criterion": "x", "passed": True, "note": ""}, "junk"])
        self.assertEqual(len(items), 1)


class TestJudgeShapeTolerance(unittest.TestCase):
    """llama3.1:8b in JSON mode emits objects, not arrays. Every shape that
    carries the verdict information must parse."""

    def test_dict_keyed_by_criterion_with_dict_values(self):
        raw = {"voice_match": {"passed": True, "note": "fine"},
               "claim_traceability": {"passed": False, "reason": "invented"}}
        items = reviewer._judge_items(raw)
        self.assertEqual(len(items), 2)
        by_crit = {i.criterion: i for i in items}
        self.assertTrue(by_crit["voice_match"].passed)
        self.assertFalse(by_crit["claim_traceability"].passed)
        self.assertEqual(by_crit["claim_traceability"].note, "invented")

    def test_dict_of_bools(self):
        items = reviewer._judge_items({"voice_match": True,
                                       "one_throwaway_line": False})
        self.assertEqual(len(items), 2)
        self.assertFalse([i for i in items
                          if i.criterion == "one_throwaway_line"][0].passed)

    def test_single_flat_item(self):
        items = reviewer._judge_items(
            {"criterion": "voice_match", "passed": True, "note": "ok"})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].criterion, "voice_match")

    def test_alias_keys_and_string_booleans(self):
        items = reviewer._judge_items(
            [{"name": "voice_match", "pass": "true", "comment": "reads well"},
             {"check": "last_line_opens_a_door", "result": "fail",
              "reason": "restates thesis"}])
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0].passed)
        self.assertEqual(items[0].note, "reads well")
        self.assertFalse(items[1].passed)

    def test_wrapped_array_still_works(self):
        items = reviewer._judge_items(
            {"checklist": [{"criterion": "voice_match", "passed": True,
                            "note": ""}]})
        self.assertEqual(len(items), 1)

    def test_true_garbage_still_yields_nothing(self):
        self.assertEqual(reviewer._judge_items({"note": "not a checklist"}), [])
        self.assertEqual(reviewer._judge_items("prose reply"), [])


if __name__ == "__main__":
    unittest.main()
