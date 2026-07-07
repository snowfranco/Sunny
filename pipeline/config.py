"""Configuration.

Two layers:
- config.json (repo root, gitignored; copy config.example.json) for paths
  and per-machine settings.
- Environment variables for the LLM runtime:
    PIPELINE_MODEL           model id for all LLM calls. Deliberately left
                             unset by default; the model decision is open
                             and made after real usage exists. Unset means
                             mock mode.
    PIPELINE_MOCK            "1" forces mock mode even if a model is set.
    ANTHROPIC_API_KEY        required for real (non-mock) runs.
    PIPELINE_MAX_TOKENS_PER_RUN   per-run token ceiling (tier 1 guardrail).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PROJECT_DOC_NAMES = [
    "PROJECT_OS.md",
    "ROADMAP.md",
    "DECISIONS.md",
    "decisions.md",
    "DECISION_LOG.md",
]


@dataclass
class Config:
    project_paths: list[str] = field(default_factory=list)
    project_doc_names: list[str] = field(default_factory=lambda: list(DEFAULT_PROJECT_DOC_NAMES))
    inbox_path: str = "inbox.md"
    data_dir: str = "data"
    exports_dir: str = "exports"
    serve_port: int = 8787

    # --- resolved paths ---------------------------------------------------
    def _resolve(self, p: str) -> Path:
        path = Path(os.path.expanduser(p))
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def data_path(self) -> Path:
        return self._resolve(self.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_path / "pipeline.db"

    @property
    def exports_path(self) -> Path:
        return self._resolve(self.exports_dir)

    @property
    def inbox_file(self) -> Path:
        return self._resolve(self.inbox_path)

    @property
    def suggestions_file(self) -> Path:
        """Researcher output the local page reads (also written by cron)."""
        return self.data_path / "suggestions.json"

    @property
    def images_path(self) -> Path:
        return self.data_path / "images"

    def resolved_project_paths(self) -> list[Path]:
        return [self._resolve(p) for p in self.project_paths]


def load_config(config_file: Path | None = None) -> Config:
    """Load config.json if present, else defaults. Unknown keys ignored."""
    path = config_file or REPO_ROOT / "config.json"
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    known = {f for f in Config.__dataclass_fields__}
    return Config(**{k: v for k, v in data.items() if k in known})


# --- LLM runtime settings (env-driven; model deliberately not hard-coded) --

def pipeline_model() -> str | None:
    """The runtime model id, or None when unset (mock mode).

    Routing is by prefix (see llm._real_call): "ollama/<name>" targets a
    local Ollama server, "gemini*" targets Google, anything else goes to
    the Anthropic API. Unset means mock mode; that default is deliberate."""
    return os.environ.get("PIPELINE_MODEL") or None


def ollama_host() -> str:
    """Base URL of the local Ollama server, for PIPELINE_MODEL=ollama/<name>.
    OLLAMA_HOST accepts host:port with or without a scheme."""
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    if "://" not in host:
        host = "http://" + host
    return host.rstrip("/")


def gemini_api_key() -> str | None:
    """API key for PIPELINE_MODEL=gemini*."""
    return (os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY") or None)


def mock_mode() -> bool:
    return os.environ.get("PIPELINE_MOCK") == "1" or pipeline_model() is None


def max_tokens_per_run() -> int:
    return int(os.environ.get("PIPELINE_MAX_TOKENS_PER_RUN", "150000"))
