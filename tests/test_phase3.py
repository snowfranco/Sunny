"""Artist scaffold: the bar is a valid image + caption, nothing more."""

import os
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import angle_engine, artist, capture, db, llm, orchestrator
from pipeline.config import Config


class TestArtistScaffold(unittest.TestCase):
    def test_generates_valid_svg_and_caption(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        note = capture.capture_manual(conn, "artist scaffold test")
        angles = angle_engine.generate_angles(conn, note)
        essay = [a for a in angles if a.format == "substack_essay"][0]

        with tempfile.TemporaryDirectory() as td:
            cfg = Config(data_dir=td)
            with mock.patch.object(artist, "load_config", return_value=cfg):
                client = llm.LLMClient("t")
                verdict = orchestrator.run_review_loop(conn, essay, note, client, "r")
                out = artist.generate(conn, verdict.post_id, client)

                # valid image: file exists and parses as SVG
                self.assertTrue(os.path.exists(out.image_path))
                root = ET.parse(out.image_path).getroot()
                self.assertTrue(root.tag.endswith("svg"))

                # caption present, sane, no em dash
                self.assertTrue(out.caption)
                self.assertNotIn("—", out.caption)

                # persisted
                stored = db.get_artist_output(conn, verdict.post_id)
                self.assertEqual(stored.image_path, out.image_path)

    def test_title_wrapping_handles_long_titles(self):
        l1, l2 = artist._wrap_title(
            "A very long title that cannot possibly fit on two short lines "
            "of an social card without truncation somewhere")
        self.assertTrue(l1)
        self.assertTrue(l2.endswith("…"))


if __name__ == "__main__":
    unittest.main()
