"""SQLite storage. Single file, single user, no cloud.

One table per handoff schema. Save helpers accept the validated dataclass
(never a raw dict from an LLM); load helpers return dataclasses, so schema
validation runs on the way out too.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import schemas as S
from .config import load_config

DDL = """
CREATE TABLE IF NOT EXISTS capture_notes (
    note_id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('manual','project_scan','landscape_scan')),
    raw_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_url TEXT
);

CREATE TABLE IF NOT EXISTS angle_options (
    angle_id TEXT PRIMARY KEY,
    note_id TEXT NOT NULL REFERENCES capture_notes(note_id),
    pillar TEXT NOT NULL,
    format TEXT NOT NULL,
    title TEXT NOT NULL,
    hook TEXT NOT NULL,
    strategic_rationale TEXT NOT NULL,
    rationale TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refinement_turns (
    session_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    speaker TEXT NOT NULL CHECK (speaker IN ('you','engine')),
    message TEXT NOT NULL,
    resulting_angle_or_draft_id TEXT,
    timestamp TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'angle' CHECK (kind IN ('angle','edit')),
    PRIMARY KEY (session_id, turn_number, speaker)
);

CREATE TABLE IF NOT EXISTS picked_angles (
    angle_id TEXT PRIMARY KEY REFERENCES angle_options(angle_id),
    note_id TEXT NOT NULL,
    picked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS writer_outputs (
    post_id TEXT NOT NULL,
    angle_id TEXT NOT NULL,
    pillar TEXT NOT NULL,
    format TEXT NOT NULL,
    draft_text TEXT NOT NULL,
    voice_context_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (post_id, revision)
);

CREATE TABLE IF NOT EXISTS artist_outputs (
    post_id TEXT PRIMARY KEY,
    image_path TEXT NOT NULL,
    caption TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviewer_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    passed INTEGER NOT NULL,
    checklist_json TEXT NOT NULL,
    revision_count INTEGER NOT NULL,
    fail_reason TEXT,
    reviewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edited_posts (
    post_id TEXT PRIMARY KEY,
    final_text TEXT NOT NULL,
    edited_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repurposed_formats (
    post_id TEXT PRIMARY KEY,
    linkedin_extract TEXT NOT NULL,
    notes_hook TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_bundles (
    post_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status = 'draft'),  -- never anything else
    post_text TEXT NOT NULL,
    linkedin_extract TEXT NOT NULL,
    notes_hook TEXT NOT NULL,
    image_path TEXT,
    caption TEXT,
    pillar TEXT NOT NULL,
    exported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('substack','linkedin')),
    views INTEGER NOT NULL,
    likes INTEGER NOT NULL,
    comments INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    collected_at TEXT NOT NULL,
    days_since_publish INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS growth_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    top_performers_json TEXT NOT NULL,
    pillar_performance_json TEXT NOT NULL,
    trend_notes TEXT NOT NULL,
    recommendations_json TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_update_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    updated_at TEXT NOT NULL,
    changed_files_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    approved_by TEXT NOT NULL CHECK (approved_by = 'snow')
);

CREATE TABLE IF NOT EXISTS pipeline_run_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    input_ref TEXT NOT NULL,
    output_ref TEXT NOT NULL,
    pass_fail INTEGER,           -- NULL / 0 / 1
    human_override INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or load_config().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()


# --- save helpers -----------------------------------------------------------

def save_note(conn, note: S.CaptureNote) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO capture_notes VALUES (?,?,?,?,?)",
        (note.note_id, note.source, note.raw_text, note.created_at, note.source_url),
    )
    conn.commit()


def save_angle(conn, a: S.AngleOption) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO angle_options VALUES (?,?,?,?,?,?,?,?)",
        (a.angle_id, a.note_id, a.pillar, a.format, a.title, a.hook,
         a.strategic_rationale, a.rationale),
    )
    conn.commit()


def save_refinement_turn(conn, t: S.RefinementTurn, kind: str) -> None:
    assert kind in ("angle", "edit")
    conn.execute(
        "INSERT OR REPLACE INTO refinement_turns VALUES (?,?,?,?,?,?,?)",
        (t.session_id, t.turn_number, t.speaker, t.message,
         t.resulting_angle_or_draft_id, t.timestamp, kind),
    )
    conn.commit()


def save_picked_angle(conn, p: S.PickedAngle) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO picked_angles VALUES (?,?,?)",
        (p.angle_id, p.note_id, p.picked_at),
    )
    conn.commit()


def save_writer_output(conn, w: S.WriterOutput, revision: int = 0) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO writer_outputs VALUES (?,?,?,?,?,?,?,?)",
        (w.post_id, w.angle_id, w.pillar, w.format, w.draft_text,
         w.voice_context_version, w.generated_at, revision),
    )
    conn.commit()


def save_artist_output(conn, a: S.ArtistOutput) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO artist_outputs VALUES (?,?,?,?)",
        (a.post_id, a.image_path, a.caption, a.generated_at),
    )
    conn.commit()


def save_verdict(conn, v: S.ReviewerVerdict) -> None:
    conn.execute(
        "INSERT INTO reviewer_verdicts "
        "(post_id, passed, checklist_json, revision_count, fail_reason, reviewed_at) "
        "VALUES (?,?,?,?,?,?)",
        (v.post_id, int(v.passed), json.dumps([c.to_dict() for c in v.checklist]),
         v.revision_count, v.fail_reason, v.reviewed_at),
    )
    conn.commit()


def save_edited_post(conn, e: S.EditedPost) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO edited_posts VALUES (?,?,?)",
        (e.post_id, e.final_text, e.edited_at),
    )
    conn.commit()


def save_repurposed(conn, r: S.RepurposedFormats) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO repurposed_formats VALUES (?,?,?,?)",
        (r.post_id, r.linkedin_extract, r.notes_hook, r.generated_at),
    )
    conn.commit()


def save_export_bundle(conn, b: S.ExportBundle) -> None:
    # Belt and braces: the schema already guarantees this, the table CHECK
    # guarantees it again. There is no publish path.
    assert b.status == "draft"
    conn.execute(
        "INSERT OR REPLACE INTO export_bundles VALUES (?,?,?,?,?,?,?,?,?)",
        (b.post_id, b.status, b.post_text, b.linkedin_extract, b.notes_hook,
         b.image_path, b.caption, b.pillar, b.exported_at),
    )
    conn.commit()


def save_analytics(conn, a: S.AnalyticsSnapshot) -> None:
    conn.execute(
        "INSERT INTO analytics_snapshots "
        "(post_id, platform, views, likes, comments, shares, collected_at, days_since_publish) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (a.post_id, a.platform, a.views, a.likes, a.comments, a.shares,
         a.collected_at, a.days_since_publish),
    )
    conn.commit()


def save_growth_report(conn, g: S.GrowthInsightReport) -> None:
    conn.execute(
        "INSERT INTO growth_reports "
        "(period_start, period_end, top_performers_json, pillar_performance_json, "
        " trend_notes, recommendations_json, generated_at) VALUES (?,?,?,?,?,?,?)",
        (g.period_start, g.period_end, json.dumps(g.top_performers),
         json.dumps(g.pillar_performance), g.trend_notes,
         json.dumps(g.recommendations), g.generated_at),
    )
    conn.commit()


def save_context_update(conn, c: S.ContextUpdateLog) -> None:
    conn.execute(
        "INSERT INTO context_update_logs (updated_at, changed_files_json, summary, approved_by) "
        "VALUES (?,?,?,?)",
        (c.updated_at, json.dumps(c.changed_files), c.summary, c.approved_by),
    )
    conn.commit()


def save_run_log(conn, r: S.PipelineRunLog) -> None:
    conn.execute(
        "INSERT INTO pipeline_run_log "
        "(run_id, step, ref_id, input_ref, output_ref, pass_fail, human_override, timestamp) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (r.run_id, r.step, r.ref_id, r.input_ref, r.output_ref,
         None if r.pass_fail is None else int(r.pass_fail),
         int(r.human_override), r.timestamp),
    )
    conn.commit()


# --- load helpers -----------------------------------------------------------

def get_note(conn, note_id: str) -> S.CaptureNote | None:
    row = conn.execute(
        "SELECT * FROM capture_notes WHERE note_id = ?", (note_id,)
    ).fetchone()
    return S.CaptureNote.from_dict(dict(row)) if row else None


def list_notes(conn, source: str | None = None) -> list[S.CaptureNote]:
    if source:
        rows = conn.execute(
            "SELECT * FROM capture_notes WHERE source = ? ORDER BY created_at DESC",
            (source,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM capture_notes ORDER BY created_at DESC").fetchall()
    return [S.CaptureNote.from_dict(dict(r)) for r in rows]


def get_angle(conn, angle_id: str) -> S.AngleOption | None:
    row = conn.execute(
        "SELECT * FROM angle_options WHERE angle_id = ?", (angle_id,)
    ).fetchone()
    return S.AngleOption.from_dict(dict(row)) if row else None


def list_angles_for_note(conn, note_id: str) -> list[S.AngleOption]:
    rows = conn.execute(
        "SELECT * FROM angle_options WHERE note_id = ?", (note_id,)).fetchall()
    return [S.AngleOption.from_dict(dict(r)) for r in rows]


def get_latest_draft(conn, post_id: str) -> S.WriterOutput | None:
    row = conn.execute(
        "SELECT * FROM writer_outputs WHERE post_id = ? ORDER BY revision DESC LIMIT 1",
        (post_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d.pop("revision", None)
    return S.WriterOutput.from_dict(d)


def next_revision(conn, post_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(revision), -1) + 1 AS n FROM writer_outputs "
        "WHERE post_id = ?", (post_id,)).fetchone()
    return int(row["n"])


def get_edited_post(conn, post_id: str) -> S.EditedPost | None:
    row = conn.execute(
        "SELECT * FROM edited_posts WHERE post_id = ?", (post_id,)).fetchone()
    return S.EditedPost.from_dict(dict(row)) if row else None


def get_artist_output(conn, post_id: str) -> S.ArtistOutput | None:
    row = conn.execute(
        "SELECT * FROM artist_outputs WHERE post_id = ?", (post_id,)).fetchone()
    return S.ArtistOutput.from_dict(dict(row)) if row else None


def get_repurposed(conn, post_id: str) -> S.RepurposedFormats | None:
    row = conn.execute(
        "SELECT * FROM repurposed_formats WHERE post_id = ?", (post_id,)).fetchone()
    return S.RepurposedFormats.from_dict(dict(row)) if row else None


def refinement_turn_count(conn, session_id: str, speaker: str = "you") -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM refinement_turns WHERE session_id = ? AND speaker = ?",
        (session_id, speaker)).fetchone()
    return int(row["n"])
