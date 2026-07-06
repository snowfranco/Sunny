"""Writer: picked angle + context -> WriterOutput draft.

voice_context_version is a content hash of context/brand-voice.md, so every
draft records exactly which voice guide it was written against (tier 2
guardrail leans on this when the guide changes).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import db, llm
from . import schemas as S
from .config import REPO_ROOT

WRITER_SYSTEM = """You are writing as Snow Abad, a product manager building
in public. Follow the brand voice guide exactly; its hard rules are enforced
by a reviewer after you, so violations just cost a retry:
- Start mid-argument, no preamble. Two sentences in, the reader is inside
  the problem.
- Let the insight arrive through the writing; never announce it upfront.
- Include "I'm not sure if you'd agree, but..." or its spirit at least once.
- When something failed: "That didn't work out as expected, but here's what
  I learned."
- One throwaway line: a specific, slightly unnecessary detail.
- Leave one observation unresolved. The last line opens a door.
- No em dashes. No signpost sentences. No fragment-heavy rhythm. No
  "this is not X, it's Y" constructions.
- Never use: game-changer, unlock (verb), supercharge, leverage (verb),
  the future of X, paradigm shift, democratize, transformative.
- When contrasting old and new ways of working, frame it as evolution
  ("the old thing was ___, here's how that's evolving"), never a battle.
- For substack_essay format ONLY: put a single short blockquote line
  (starting "> ") above the opening, naming the actual tools, projects and
  concepts discussed. It is paratext, not the opening line. Then respect
  400-900 words. linkedin_post: 100-200 words, 3-6 paragraphs, no headers,
  ends open. social_copy: 1-3 sentences. script: written to be spoken,
  direct address. portal_briefing: editorial intro, category framing,
  tight factual linked items.
- Every specific number, project name, or fact must come from the source
  note or context provided. Do not invent."""


def voice_version(context_dir: Path | None = None) -> str:
    f = (context_dir or REPO_ROOT / "context") / "brand-voice.md"
    if not f.is_file():
        return "missing"
    return hashlib.sha256(f.read_bytes()).hexdigest()[:12]


def _writing_context(context_dir: Path | None = None) -> str:
    d = context_dir or REPO_ROOT / "context"
    parts = []
    for name in ("brand-voice.md", "pillars.md", "strategy.md", "platforms.md"):
        f = d / name
        if f.is_file():
            parts.append(f"--- {name} ---\n" + f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def write_draft(conn, angle: S.AngleOption, note: S.CaptureNote,
                client: llm.LLMClient, post_id: str | None = None,
                revision: int = 0,
                feedback: str | None = None) -> S.WriterOutput:
    """First draft (revision 0) or a reviewer-feedback revision."""
    user = (f"ANGLE:\n  title: {angle.title}\n  hook: {angle.hook}\n"
            f"  pillar: {angle.pillar}\n  format: {angle.format}\n"
            f"  why: {angle.rationale} ({angle.strategic_rationale})\n\n"
            f"SOURCE NOTE:\n{note.raw_text}\n"
            + (f"SOURCE URL: {note.source_url}\n" if note.source_url else "")
            + f"\nCONTEXT:\n{_writing_context()}\n\n"
            f"Write the {angle.format} piece. Reply with the piece only.")
    if feedback:
        user += ("\n\nA reviewer failed the previous draft for these specific "
                 f"reasons; fix them without losing the voice:\n{feedback}")
        text = client.complete_text("revise_draft", WRITER_SYSTEM, user,
                                    max_tokens=3000)
    else:
        text = client.complete_text("draft", WRITER_SYSTEM, user, max_tokens=3000)

    out = S.WriterOutput(
        post_id=post_id or S.new_id(),
        angle_id=angle.angle_id,
        pillar=angle.pillar,
        format=angle.format,
        draft_text=text.strip(),
        voice_context_version=voice_version(),
        generated_at=S.now_iso(),
    )
    db.save_writer_output(conn, out, revision=revision)
    return out


def revise_for_edit(conn, current: S.WriterOutput, instruction: str,
                    client: llm.LLMClient, revision: int) -> S.WriterOutput:
    """Edit-stage revision: Snow's plain-language change request, e.g.
    'exclude the paragraph about ___'. Regenerates just what's asked."""
    user = (f"CURRENT DRAFT ({current.format}):\n{current.draft_text}\n\n"
            f"SNOW'S EDIT REQUEST:\n{instruction}\n\n"
            "Apply exactly this change. Keep everything she did not ask you "
            "to change, keep the format rules, reply with the full revised "
            "piece only.")
    text = client.complete_text("revise_draft", WRITER_SYSTEM, user,
                                max_tokens=3000)
    out = S.WriterOutput(
        post_id=current.post_id,
        angle_id=current.angle_id,
        pillar=current.pillar,
        format=current.format,
        draft_text=text.strip(),
        voice_context_version=voice_version(),
        generated_at=S.now_iso(),
    )
    db.save_writer_output(conn, out, revision=revision)
    return out
