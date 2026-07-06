"""Researcher: two scans, both producing CaptureNotes plus a suggestions
file the local page reads.

1. Project-doc scan (internal): reads a configurable list of local project
   paths, looking for PROJECT_OS.md / ROADMAP.md / decisions logs (Snow's
   existing convention). STRICTLY READ-ONLY: this module never writes to
   those paths. Recently-modified docs are summarized into note candidates
   grounded in real work.

2. Landscape scan (external): reactive trends AND long-term bets, per the
   strategy doc. Every landscape suggestion must carry a citable source_url
   or it is rejected at the schema layer (tier 1 guardrail).

Cadence: on-demand via `python3 -m pipeline research`, plus an optional
daily cron/launchd entry calling the same command (see scripts/). No
always-on server.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import db, llm
from . import schemas as S
from .config import Config, load_config

# How much of each doc to read, and how recent "recent" is.
DOC_EXCERPT_CHARS = 4000
RECENT_DAYS = 21


def scan_project_docs(conn, cfg: Config | None = None) -> list[S.CaptureNote]:
    """Read-only scan of configured project paths; returns saved notes."""
    import time
    cfg = cfg or load_config()
    cutoff = time.time() - RECENT_DAYS * 86400
    notes: list[S.CaptureNote] = []
    for project in cfg.resolved_project_paths():
        if not project.is_dir():
            continue
        for name in cfg.project_doc_names:
            doc = project / name
            if not doc.is_file():
                continue
            try:
                if doc.stat().st_mtime < cutoff:
                    continue
                excerpt = doc.read_text(encoding="utf-8", errors="replace")[:DOC_EXCERPT_CHARS]
            except OSError:
                continue
            if not excerpt.strip():
                continue
            note = S.CaptureNote(
                note_id=S.new_id(),
                source="project_scan",
                raw_text=f"[{project.name}/{name}] {excerpt.strip()}",
                created_at=S.now_iso(),
            )
            db.save_note(conn, note)
            notes.append(note)
    return notes


LANDSCAPE_SYSTEM = """You are the landscape researcher for Snow Abad's content
pipeline. Snow is an AI-focused PM with 15 years of SaaS delivery, building in
public. Propose external topics worth writing about, two kinds, both wanted:
reactive trends (a framework or model shipping now that deserves a "how you'd
actually use this" piece) and long-term bets (a shift worth getting ahead of,
not just what's hot). Never propose generic news roundups; news is fuel inside
a pillar. Every item MUST have a citable source URL you are confident exists.
If you cannot cite it, do not propose it."""


def scan_landscape(conn, client: llm.LLMClient | None = None,
                   context_dir: Path | None = None) -> list[S.CaptureNote]:
    """External scan. Suggestions without a citable source are dropped
    (schema enforces it); we report how many were rejected."""
    client = client or llm.LLMClient(run_id="research")
    ctx = _strategy_context(context_dir)
    items = client.complete_json(
        "landscape",
        LANDSCAPE_SYSTEM,
        "Context about Snow's pillars and strategy:\n" + ctx +
        "\n\nPropose 2-4 items as a JSON array of "
        '{"raw_text": "...", "source_url": "https://..."}.',
    )
    notes: list[S.CaptureNote] = []
    rejected = 0
    for item in items if isinstance(items, list) else []:
        try:
            note = S.CaptureNote(
                note_id=S.new_id(),
                source="landscape_scan",
                raw_text=str(item.get("raw_text", "")),
                created_at=S.now_iso(),
                source_url=item.get("source_url"),
            )
        except S.SchemaError:
            rejected += 1
            continue
        db.save_note(conn, note)
        notes.append(note)
    if rejected:
        print(f"landscape scan: rejected {rejected} suggestion(s) without a citable source")
    return notes


def _strategy_context(context_dir: Path | None = None) -> str:
    from .config import REPO_ROOT
    d = context_dir or REPO_ROOT / "context"
    parts = []
    for name in ("pillars.md", "strategy.md"):
        f = d / name
        if f.is_file():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def research(conn, cfg: Config | None = None,
             client: llm.LLMClient | None = None) -> dict:
    """Full research pass: both scans, then write suggestions.json for the
    local page (and for the optional daily cron to refresh)."""
    cfg = cfg or load_config()
    project_notes = scan_project_docs(conn, cfg)
    landscape_notes = scan_landscape(conn, client)
    payload = {
        "generated_at": S.now_iso(),
        "project_suggestions": [n.to_dict() for n in project_notes],
        "landscape_suggestions": [n.to_dict() for n in landscape_notes],
    }
    cfg.suggestions_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.suggestions_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
