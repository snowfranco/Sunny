"""Angle engine: note -> 3 schema-validated AngleOptions.

Snow can also hand the system a completely unrelated topic at any point
(capture_manual -> generate_angles); the suggested list is never the only
entry point.
"""

from __future__ import annotations

from pathlib import Path

from . import db, llm
from . import schemas as S
from .config import REPO_ROOT

ANGLE_SYSTEM = """You are the angle engine in Snow Abad's content pipeline.
Given one captured note plus Snow's pillars, strategy, and platform guide,
propose exactly 3 distinct angles. Each angle must:
- map to exactly one pillar: build_in_public | ai_for_shippers | transition_story
- target one format: substack_essay | linkedin_post | social_copy | script | portal_briefing
- carry a strategic_rationale: reactive_trend | long_term_bet | monetization_adjacent | immediate_credibility
- have a title (max 80 chars), a 1-2 sentence hook, and a one-sentence rationale.
Vary the pillars and formats across the 3 options when the note allows it.
Generic AI news roundups are not a pillar; news is fuel inside a pillar."""

MAX_SCHEMA_RETRIES = 2  # malformed LLM output gets this many re-asks


def _context_blob(context_dir: Path | None = None) -> str:
    d = context_dir or REPO_ROOT / "context"
    parts = []
    for name in ("pillars.md", "strategy.md", "platforms.md"):
        f = d / name
        if f.is_file():
            parts.append(f"--- {name} ---\n" + f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def _to_angle(note_id: str, item: dict) -> S.AngleOption:
    return S.AngleOption(
        note_id=note_id,
        angle_id=S.new_id(),
        pillar=str(item.get("pillar", "")),
        format=str(item.get("format", "")),
        title=str(item.get("title", "")),
        hook=str(item.get("hook", "")),
        strategic_rationale=str(item.get("strategic_rationale", "")),
        rationale=str(item.get("rationale", "")),
    )


def generate_angles(conn, note: S.CaptureNote,
                    client: llm.LLMClient | None = None) -> list[S.AngleOption]:
    """3 angle options for a note; invalid LLM output triggers a bounded
    re-ask, then raises."""
    client = client or llm.LLMClient(run_id=f"angles-{note.note_id[:8]}")
    ctx = _context_blob()
    user = (f"THE NOTE (source: {note.source}"
            + (f", cite: {note.source_url}" if note.source_url else "")
            + f"):\n{note.raw_text}\n\nCONTEXT:\n{ctx}\n\n"
            'Reply with a JSON array of exactly 3 angle objects with keys: '
            'pillar, format, title, hook, strategic_rationale, rationale.')

    last_err: Exception | None = None
    for attempt in range(1 + MAX_SCHEMA_RETRIES):
        try:
            items = client.complete_json("angles", ANGLE_SYSTEM, user)
            if not isinstance(items, list) or len(items) != 3:
                raise S.SchemaError(f"expected 3 angles, got {items!r:.200}")
            angles = [_to_angle(note.note_id, it) for it in items]
            for a in angles:
                db.save_angle(conn, a)
            return angles
        except (S.SchemaError, llm.LLMError) as e:
            last_err = e
            user += f"\n\nYour previous reply was invalid ({e}). Fix it."
    raise S.SchemaError(f"angle engine produced invalid output after "
                        f"{1 + MAX_SCHEMA_RETRIES} attempts: {last_err}")


def refine_angle(conn, base_angle: S.AngleOption, instruction: str,
                 client: llm.LLMClient | None = None) -> S.AngleOption:
    """One refinement step: Snow's plain-language instruction -> a revised,
    validated angle saved alongside the original."""
    client = client or llm.LLMClient(run_id=f"refine-{base_angle.angle_id[:8]}")
    user = (f"CURRENT ANGLE:\n{base_angle.to_dict()}\n\n"
            f"SNOW'S INSTRUCTION:\n{instruction}\n\n"
            "Reply with ONE revised angle object (same keys). Keep what she "
            "did not ask you to change. Explain nothing; the JSON is the reply.")
    item = client.complete_json("refine_angle", ANGLE_SYSTEM, user)
    if isinstance(item, list):  # tolerate a single-element array
        item = item[0] if item else {}
    angle = _to_angle(base_angle.note_id, item)
    db.save_angle(conn, angle)
    return angle


def pick_angle(conn, angle: S.AngleOption) -> S.PickedAngle:
    picked = S.PickedAngle(note_id=angle.note_id, angle_id=angle.angle_id,
                           picked_at=S.now_iso())
    db.save_picked_angle(conn, picked)
    return picked
