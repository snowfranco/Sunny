"""Repurpose + export: draft bundles only, no publish path anywhere."""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ["PIPELINE_MOCK"] = "1"

from pipeline import (angle_engine, capture, db, export, llm, orchestrator,
                      repurpose)
from pipeline import schemas as S
from pipeline.config import Config


def _approved_post():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    note = capture.capture_manual(conn, "export test topic")
    angles = angle_engine.generate_angles(conn, note)
    essay = [a for a in angles if a.format == "substack_essay"][0]
    client = llm.LLMClient("t")
    verdict = orchestrator.run_review_loop(conn, essay, note, client, "r")
    orchestrator.approve_post(conn, verdict.post_id)
    return conn, verdict.post_id


class TestRepurpose(unittest.TestCase):
    def test_requires_approval_first(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)
        with self.assertRaises(KeyError):
            repurpose.repurpose(conn, "nonexistent", llm.LLMClient("t"))

    def test_produces_validated_formats(self):
        conn, post_id = _approved_post()
        out = repurpose.repurpose(conn, post_id, llm.LLMClient("t"))
        paras = [p for p in out.linkedin_extract.split("\n\n") if p.strip()]
        self.assertTrue(1 <= len(paras) <= 6)
        self.assertTrue(out.notes_hook)
        self.assertEqual(db.get_repurposed(conn, post_id).post_id, post_id)


class TestExport(unittest.TestCase):
    def test_bundle_is_draft_only_and_files_land(self):
        conn, post_id = _approved_post()
        repurpose.repurpose(conn, post_id, llm.LLMClient("t"))
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(exports_dir=td, data_dir=td)
            with mock.patch.object(export, "load_config", return_value=cfg):
                bundle, out_dir = export.export_bundle(conn, post_id)
            self.assertEqual(bundle.status, "draft")
            for name in ("post.md", "linkedin.md", "notes-hook.txt", "bundle.json"):
                self.assertTrue((out_dir / name).exists(), name)
            data = json.loads((out_dir / "bundle.json").read_text())
            self.assertEqual(data["status"], "draft")

    def test_assertion_blocks_any_future_publish_flag(self):
        conn, post_id = _approved_post()
        b = S.ExportBundle(post_id=post_id, status="draft", post_text="t",
                           linkedin_extract="e", notes_hook="h",
                           image_path=None, caption=None,
                           pillar="build_in_public", exported_at=S.now_iso())
        export.assert_never_publishes(b)  # fine
        with mock.patch.object(export, "PUBLISHING_SUPPORTED", True):
            with self.assertRaises(AssertionError):
                export.assert_never_publishes(b)

    def test_no_publish_code_path_exists(self):
        """Static tripwire: no module in the package touches a publish API.
        Substack/LinkedIn appear only as words in prompts/docs, never as an
        HTTP call. We assert no module imports an HTTP client except the
        Anthropic-only llm module and the localhost-only serve module."""
        import pathlib
        pkg = pathlib.Path(export.__file__).parent
        allowed_http = {"llm.py", "serve.py"}
        for py in pkg.glob("*.py"):
            src = py.read_text(encoding="utf-8")
            if py.name in allowed_http:
                continue
            for needle in ("urllib.request", "requests.", "import requests",
                           "http.client", "httpx"):
                self.assertNotIn(needle, src,
                                 f"{py.name} must not make HTTP calls ({needle})")
            self.assertNotIn("api.linkedin.com", src.lower(), py.name)
            self.assertNotIn("substack.com/api", src.lower(), py.name)


if __name__ == "__main__":
    unittest.main()
