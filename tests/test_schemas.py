"""Schema validation is the tier-1 guardrail; test the sharp edges."""

import unittest

from pipeline import schemas as S


def _note(**kw):
    d = dict(note_id=S.new_id(), source="manual", raw_text="shipped the thing",
             created_at=S.now_iso())
    d.update(kw)
    return S.CaptureNote(**d)


class TestCaptureNote(unittest.TestCase):
    def test_valid_manual_note(self):
        self.assertEqual(_note().source, "manual")

    def test_bad_source_rejected(self):
        with self.assertRaises(S.SchemaError):
            _note(source="twitter")

    def test_landscape_scan_requires_citable_source(self):
        with self.assertRaises(S.SchemaError):
            _note(source="landscape_scan")
        with self.assertRaises(S.SchemaError):
            _note(source="landscape_scan", source_url="somewhere I read")
        ok = _note(source="landscape_scan", source_url="https://example.com/post")
        self.assertTrue(ok.source_url.startswith("http"))


class TestAngleOption(unittest.TestCase):
    def _angle(self, **kw):
        d = dict(note_id="n", angle_id="a", pillar="build_in_public",
                 format="substack_essay", title="A title", hook="A hook.",
                 strategic_rationale="reactive_trend", rationale="because")
        d.update(kw)
        return S.AngleOption(**d)

    def test_valid(self):
        self.assertEqual(self._angle().pillar, "build_in_public")

    def test_title_length_cap(self):
        with self.assertRaises(S.SchemaError):
            self._angle(title="x" * 81)

    def test_bad_pillar_and_rationale(self):
        with self.assertRaises(S.SchemaError):
            self._angle(pillar="hot_takes")
        with self.assertRaises(S.SchemaError):
            self._angle(strategic_rationale="virality")


class TestRefinementTurn(unittest.TestCase):
    def test_turn_cap_is_five(self):
        for n in (1, 5):
            S.RefinementTurn(session_id="s", turn_number=n, speaker="you",
                             message="m", resulting_angle_or_draft_id=None,
                             timestamp=S.now_iso())
        with self.assertRaises(S.SchemaError):
            S.RefinementTurn(session_id="s", turn_number=6, speaker="you",
                             message="m", resulting_angle_or_draft_id=None,
                             timestamp=S.now_iso())


class TestReviewerVerdict(unittest.TestCase):
    def _verdict(self, **kw):
        d = dict(post_id="p", passed=True,
                 checklist=[{"criterion": "voice", "passed": True, "note": ""}],
                 revision_count=0, fail_reason=None, reviewed_at=S.now_iso())
        d.update(kw)
        return S.ReviewerVerdict(**d)

    def test_valid_pass(self):
        v = self._verdict()
        self.assertIsInstance(v.checklist[0], S.ChecklistItem)

    def test_fail_requires_reason(self):
        with self.assertRaises(S.SchemaError):
            self._verdict(passed=False, fail_reason=None)

    def test_revision_count_bounded(self):
        with self.assertRaises(S.SchemaError):
            self._verdict(revision_count=S.MAX_REVIEWER_RETRIES + 1)


class TestExportBundleNeverPublishes(unittest.TestCase):
    def _bundle(self, **kw):
        d = dict(post_id="p", status="draft", post_text="t",
                 linkedin_extract="e", notes_hook="h", image_path=None,
                 caption=None, pillar="ai_for_shippers", exported_at=S.now_iso())
        d.update(kw)
        return S.ExportBundle(**d)

    def test_draft_is_the_only_status(self):
        self.assertEqual(self._bundle().status, "draft")
        for status in ("published", "publishing", "scheduled", "live", ""):
            with self.assertRaises(S.SchemaError):
                self._bundle(status=status)


class TestRepurposedFormats(unittest.TestCase):
    def test_linkedin_extract_paragraph_bounds_and_no_headers(self):
        good = "\n\n".join(["para one.", "para two.", "para three?"])
        r = S.RepurposedFormats(post_id="p", linkedin_extract=good,
                                notes_hook="hook.", generated_at=S.now_iso())
        self.assertEqual(r.post_id, "p")
        too_many = "\n\n".join(f"para {i}" for i in range(7))
        with self.assertRaises(S.SchemaError):
            S.RepurposedFormats(post_id="p", linkedin_extract=too_many,
                                notes_hook="hook.", generated_at=S.now_iso())
        with self.assertRaises(S.SchemaError):
            S.RepurposedFormats(post_id="p", linkedin_extract="# Header\n\nbody",
                                notes_hook="hook.", generated_at=S.now_iso())


class TestGrowthReport(unittest.TestCase):
    def test_requires_all_pillars(self):
        with self.assertRaises(S.SchemaError):
            S.GrowthInsightReport(
                period_start="2026-06-01", period_end="2026-06-30",
                top_performers=[], pillar_performance={"build_in_public": "ok"},
                trend_notes="", recommendations=[], generated_at=S.now_iso())


class TestContextUpdateLog(unittest.TestCase):
    def test_only_snow_approves(self):
        with self.assertRaises(S.SchemaError):
            S.ContextUpdateLog(updated_at=S.now_iso(),
                               changed_files=["context/brand-voice.md"],
                               summary="s", approved_by="the_system")


class TestPipelineRunLog(unittest.TestCase):
    def test_step_enum(self):
        with self.assertRaises(S.SchemaError):
            S.PipelineRunLog(run_id="r", step="publisher", ref_id="x",
                             input_ref="", output_ref="", pass_fail=None,
                             human_override=False, timestamp=S.now_iso())


if __name__ == "__main__":
    unittest.main()
