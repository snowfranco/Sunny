"""The checker lexicon lives in context/brand-voice.md (CHECKER-LEXICON
block); reviewer.py reads it live with safe fallbacks."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import reviewer


class TestLexicon(unittest.TestCase):
    def tearDown(self):
        reviewer._reload_lexicon()

    def test_live_lists_come_from_brand_voice(self):
        lingo, signposts = reviewer._lexicon()
        self.assertIn("game-changer", lingo)
        self.assertIn("here's the thing", signposts)

    def test_parse_sections(self):
        text = ("<!-- CHECKER-LEXICON\n[banned_lingo]\nfoo bar\nBaz\n\n"
                "[signpost_sentences]\nso here we go\n-->\n")
        self.assertEqual(reviewer._parse_lexicon_section(text, "banned_lingo"),
                         ["foo bar", "baz"])
        self.assertEqual(
            reviewer._parse_lexicon_section(text, "signpost_sentences"),
            ["so here we go"])
        self.assertEqual(reviewer._parse_lexicon_section(text, "missing"), [])

    def test_missing_file_falls_back_to_defaults(self):
        lingo, signposts = reviewer._lexicon_for("/nonexistent/brand-voice.md")
        self.assertEqual(lingo, reviewer._DEFAULT_BANNED_LINGO)
        self.assertEqual(signposts, reviewer._DEFAULT_SIGNPOST_SENTENCES)

    def test_file_without_block_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "brand-voice.md"
            f.write_text("# A voice guide with no lexicon block\n")
            lingo, signposts = reviewer._lexicon_for(str(f))
            self.assertEqual(lingo, reviewer._DEFAULT_BANNED_LINGO)
            self.assertEqual(signposts, reviewer._DEFAULT_SIGNPOST_SENTENCES)

    def test_edited_lexicon_changes_checker_after_reload(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "brand-voice.md"
            f.write_text("<!-- CHECKER-LEXICON\n[banned_lingo]\nsynergy\n-->\n")
            lingo, _ = reviewer._lexicon_for(str(f))
            self.assertEqual(lingo, ("synergy",))
            # cache serves the old value until reload
            f.write_text("<!-- CHECKER-LEXICON\n[banned_lingo]\nignite\n-->\n")
            self.assertEqual(reviewer._lexicon_for(str(f)), (("synergy",),
                             reviewer._DEFAULT_SIGNPOST_SENTENCES))
            reviewer._reload_lexicon()
            lingo2, _ = reviewer._lexicon_for(str(f))
            self.assertEqual(lingo2, ("ignite",))


if __name__ == "__main__":
    unittest.main()
