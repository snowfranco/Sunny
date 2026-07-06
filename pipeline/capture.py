"""Capture: manual notes from the CLI, and a watched inbox.md.

The inbox watcher polls mtime (stdlib only, no watchdog). Each non-empty
paragraph or top-level bullet in inbox.md becomes one CaptureNote; the file
is then rewritten with an ingestion marker so nothing is captured twice.
inbox.md belongs to this tool. Project docs are never touched (read-only,
and only by the researcher).
"""

from __future__ import annotations

import time
from pathlib import Path

from . import db
from . import schemas as S
from .config import Config, load_config

INGESTED_HEADER = "<!-- sunny: ingested {ts}; drop new notes below -->"


def capture_manual(conn, raw_text: str) -> S.CaptureNote:
    note = S.CaptureNote(
        note_id=S.new_id(),
        source="manual",
        raw_text=raw_text.strip(),
        created_at=S.now_iso(),
    )
    db.save_note(conn, note)
    return note


def _split_inbox(text: str) -> list[str]:
    """Paragraphs separated by blank lines; a run of top-level bullets is
    split into one note per bullet. Comment lines are ignored."""
    notes: list[str] = []
    for block in text.split("\n\n"):
        lines = [l for l in block.splitlines() if not l.strip().startswith("<!--")]
        block = "\n".join(lines).strip()
        if not block:
            continue
        if all(l.lstrip().startswith(("- ", "* ")) for l in block.splitlines()):
            for l in block.splitlines():
                item = l.lstrip()[2:].strip()
                if item:
                    notes.append(item)
        else:
            notes.append(block)
    return notes


def ingest_inbox(conn, cfg: Config | None = None) -> list[S.CaptureNote]:
    """One pass: read inbox.md, capture every note, rewrite the file."""
    cfg = cfg or load_config()
    inbox = cfg.inbox_file
    if not inbox.exists():
        return []
    text = inbox.read_text(encoding="utf-8")
    chunks = _split_inbox(text)
    if not chunks:
        return []
    notes = [capture_manual(conn, c) for c in chunks]
    inbox.write_text(INGESTED_HEADER.format(ts=S.now_iso()) + "\n", encoding="utf-8")
    return notes


def watch_inbox(cfg: Config | None = None, interval: float = 2.0,
                max_iterations: int | None = None) -> None:
    """Poll inbox.md for changes; ingest on every change. Ctrl-C to stop.
    max_iterations exists for tests."""
    cfg = cfg or load_config()
    inbox = cfg.inbox_file
    if not inbox.exists():
        inbox.write_text(INGESTED_HEADER.format(ts=S.now_iso()) + "\n", encoding="utf-8")
        print(f"created {inbox}")
    print(f"watching {inbox} (every {interval:g}s, Ctrl-C to stop)")
    last_mtime = 0.0
    i = 0
    conn = db.connect(cfg.db_path)
    try:
        while max_iterations is None or i < max_iterations:
            i += 1
            try:
                mtime = inbox.stat().st_mtime
            except FileNotFoundError:
                mtime = 0.0
            if mtime > last_mtime:
                last_mtime = mtime
                notes = ingest_inbox(conn, cfg)
                for n in notes:
                    print(f"captured {n.note_id}: {n.raw_text[:60]!r}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        conn.close()
