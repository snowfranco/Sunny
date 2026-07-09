"""Model routing: ollama/* -> local Ollama, gemini* -> Google, else
Anthropic. Plus mock-mode semantics and the list-unwrap tolerance."""

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from pipeline import config, llm


class _StubOllama(BaseHTTPRequestHandler):
    """Minimal /api/chat + /api/tags that echoes proof it was reached."""

    def do_GET(self):
        if self.path == "/api/tags":
            out = json.dumps({"models": [{"name": "test-model:latest"},
                                         {"name": "other:8b"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    def do_POST(self):
        body = json.loads(self.rfile.read(
            int(self.headers.get("Content-Length") or 0)))
        fmt = body.get("format")
        reply = {
            "message": {"content": json.dumps({
                "reached": "ollama-stub",
                "model": body.get("model"),
                "json_mode": fmt == "json",
                "schema_type": fmt.get("type") if isinstance(fmt, dict) else None,
                "num_ctx": body.get("options", {}).get("num_ctx"),
            })},
            "prompt_eval_count": 10,
            "eval_count": 5,
        }
        out = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class _EnvPatch:
    def __init__(self, **kv):
        self.kv = kv
        self.saved = {}

    def __enter__(self):
        for k, v in self.kv.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, *a):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


class TestMockModeSemantics(unittest.TestCase):
    def test_unset_model_means_mock(self):
        with _EnvPatch(PIPELINE_MODEL=None, PIPELINE_MOCK=None):
            self.assertTrue(config.mock_mode())

    def test_set_model_means_real(self):
        with _EnvPatch(PIPELINE_MODEL="ollama/anything", PIPELINE_MOCK=None):
            self.assertFalse(config.mock_mode())

    def test_pipeline_mock_overrides_even_with_model(self):
        with _EnvPatch(PIPELINE_MODEL="ollama/anything", PIPELINE_MOCK="1"):
            self.assertTrue(config.mock_mode())


class TestConfigHelpers(unittest.TestCase):
    def test_ollama_host_default_and_normalization(self):
        with _EnvPatch(OLLAMA_HOST=None):
            self.assertEqual(config.ollama_host(), "http://localhost:11434")
        with _EnvPatch(OLLAMA_HOST="0.0.0.0:9999"):
            self.assertEqual(config.ollama_host(), "http://0.0.0.0:9999")
        with _EnvPatch(OLLAMA_HOST="http://gpu-box:11434/"):
            self.assertEqual(config.ollama_host(), "http://gpu-box:11434")

    def test_gemini_key_fallback_chain(self):
        with _EnvPatch(GEMINI_API_KEY=None, GOOGLE_API_KEY=None):
            self.assertIsNone(config.gemini_api_key())
        with _EnvPatch(GEMINI_API_KEY=None, GOOGLE_API_KEY="g2"):
            self.assertEqual(config.gemini_api_key(), "g2")


class TestOllamaRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), _StubOllama)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def _env(self):
        return _EnvPatch(
            PIPELINE_MODEL="ollama/test-model", PIPELINE_MOCK=None,
            OLLAMA_HOST=f"http://127.0.0.1:{self.httpd.server_port}")

    def test_ollama_model_routes_to_local_server(self):
        with self._env():
            client = llm.LLMClient("t")
            self.assertFalse(client.mock)
            raw = client.complete_text("draft", "sys", "user prompt")
            data = json.loads(raw)
            self.assertEqual(data["reached"], "ollama-stub")
            self.assertEqual(data["model"], "test-model")  # prefix stripped
            self.assertFalse(data["json_mode"])
            self.assertEqual(client.budget.used, 15)  # counts from the stub
            # num_ctx must be sent explicitly: the model default (~4096) is
            # smaller than the writer prompt and silently truncates output.
            self.assertEqual(data["num_ctx"], 8192)

    def test_json_calls_request_json_format(self):
        with self._env():
            client = llm.LLMClient("t")
            data = client.complete_json("growth", "sys", "user prompt")
            self.assertTrue(data["json_mode"])

    def test_schema_is_sent_as_format_when_provided(self):
        with self._env():
            client = llm.LLMClient("t")
            data = client.complete_json(
                "review", "sys", "user prompt",
                schema={"type": "array", "items": {"type": "object"}})
            # schema overrides the plain "json" format
            self.assertFalse(data["json_mode"])
            self.assertEqual(data["schema_type"], "array")

    def test_last_raw_reply_is_captured(self):
        with self._env():
            client = llm.LLMClient("t")
            client.complete_text("draft", "sys", "user prompt")
            self.assertIn("ollama-stub", client.last_raw_reply)

    def test_list_models_reads_tags(self):
        with self._env():
            names = llm.ollama_list_models()
            self.assertIn("test-model:latest", names)

    def test_unreachable_ollama_raises_actionable_error(self):
        with _EnvPatch(PIPELINE_MODEL="ollama/x", PIPELINE_MOCK=None,
                       OLLAMA_HOST="http://127.0.0.1:1"):
            client = llm.LLMClient("t")
            with self.assertRaises(llm.LLMError) as ctx:
                client.complete_text("draft", "s", "u")
            self.assertIn("ollama serve", str(ctx.exception))


class _NotFoundOllama(BaseHTTPRequestHandler):
    """Ollama with the server up but the model not pulled: 404 + error body,
    exactly what /api/chat returns for an unpulled model."""

    def do_POST(self):
        out = json.dumps({"error": "model 'mistral-nemo:12b' not found, "
                          "try pulling it first"}).encode()
        self.send_response(404)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class TestOllamaModelNotPulled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), _NotFoundOllama)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_404_says_model_not_pulled_not_server_down(self):
        with _EnvPatch(PIPELINE_MODEL="ollama/mistral-nemo:12b",
                       PIPELINE_MOCK=None,
                       OLLAMA_HOST=f"http://127.0.0.1:{self.httpd.server_port}"):
            client = llm.LLMClient("t")
            with self.assertRaises(llm.LLMError) as ctx:
                client.complete_text("draft", "s", "u")
            msg = str(ctx.exception)
            self.assertIn("not available", msg)
            self.assertIn("ollama pull mistral-nemo:12b", msg)
            self.assertNotIn("ollama serve", msg)  # server IS up

    def test_angle_engine_does_not_retry_a_model_error(self):
        # A missing model won't fix itself on re-ask; the clear error should
        # surface immediately, not after 3 attempts.
        import sqlite3
        from pipeline import angle_engine, capture, db
        conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
        db.init_db(conn)
        with _EnvPatch(PIPELINE_MODEL="ollama/mistral-nemo:12b",
                       PIPELINE_MOCK=None,
                       OLLAMA_HOST=f"http://127.0.0.1:{self.httpd.server_port}"):
            note = capture.capture_manual(conn, "a topic")
            with self.assertRaises(llm.LLMError) as ctx:
                angle_engine.generate_angles(conn, note, llm.LLMClient("t"))
            self.assertIn("ollama pull", str(ctx.exception))
            self.assertNotIn("after 3 attempts", str(ctx.exception))


class TestGeminiRouting(unittest.TestCase):
    def test_gemini_without_key_or_package_raises(self):
        with _EnvPatch(PIPELINE_MODEL="gemini-something", PIPELINE_MOCK=None,
                       GEMINI_API_KEY=None, GOOGLE_API_KEY=None):
            client = llm.LLMClient("t")
            with self.assertRaises(llm.LLMError):
                client.complete_text("draft", "s", "u")


class TestUnwrapList(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(llm.unwrap_list([1, 2]), [1, 2])
        self.assertEqual(llm.unwrap_list({"angles": [1, 2]}), [1, 2])
        self.assertEqual(llm.unwrap_list({"a": [1], "b": [2]}), [])  # ambiguous
        self.assertEqual(llm.unwrap_list("nope"), [])
        self.assertEqual(llm.unwrap_list({"note": "x"}), [])


if __name__ == "__main__":
    unittest.main()
