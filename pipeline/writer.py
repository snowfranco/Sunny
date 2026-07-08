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
- Conversational, not fragmented. Casually confident. The reader is a smart
  colleague you trust, not an audience to impress.
- Start on the thing, no preamble. Let the insight arrive through the
  writing; never announce it upfront.
- When something failed: "That didn't work out as expected, but here's what
  I learned."
- No em dashes. No signpost sentences. No fragment-heavy rhythm. No
  "this is not X, it's Y" constructions.
- Never use: game-changer, unlock (verb), supercharge, leverage (verb),
  the future of X, paradigm shift, democratize, transformative.
- When contrasting old and new ways of working, frame it as evolution
  ("the old thing was ___, here's how that's evolving"), never a battle.
- Every specific number, project name, or fact must come from the source
  note or context provided. Do not invent.
- The FORMAT BRIEF in the user message defines this piece's structure and
  length. It overrides any general instinct to write more or add structural
  elements the brief does not ask for."""

# Structure requirements differ sharply by format. Sending the essay
# checklist (signature phrase, throwaway line, unresolved observation, open
# last line) to a 1-3 sentence format guarantees an overshoot: the model
# cannot satisfy the checklist inside the cap, and the length loses.
FORMAT_BRIEFS = {
    "substack_essay": """Long-form Substack essay.
- First line: a single blockquote gist line (starting "> ") naming the
  actual tools, projects and concepts discussed. Paratext, not the opening.
- Then open mid-argument. Functional section headers as navigation
  ("What I actually built it with"), each section flowing as prose.
- Include "I'm not sure if you'd agree, but..." or its spirit once.
- One throwaway line: a small, specific, slightly unnecessary true detail.
- Leave one observation unresolved. The last line opens a door.""",
    "linkedin_post": """LinkedIn post.
- 3 to 6 tight paragraphs. No headers, no hashtags, no "hot take:" framing.
- Start with the situation, let the insight arrive.
- Include "I'm not sure if you'd agree, but..." or its spirit once.
- End on a genuine question or an observation left open, never a CTA.""",
    "social_copy": """Social post (X/Threads).
- ONE real observation. Wry over funny, specific over relatable.
- It may be mid-thought, or a question with no answer yet.
- THE ENTIRE REPLY IS 1 TO 3 SENTENCES AND NOTHING ELSE. No headers, no
  hashtags, no emoji, no setup line, no signature phrase, no unresolved-
  observation requirement, no throwaway-line requirement. Those are essay
  rules; here the whole piece is the observation. A fourth sentence is a
  failure.""",
    "script": """Video/audio script.
- Written to be spoken, not read: short sentences, natural pauses, direct
  address ("you"), explaining to one smart person, not presenting to a room.
- Include the wrong turns; the experiment framing works well spoken.
- No bullet points and no headers; write it out as you'd actually say it.""",
    "portal_briefing": """Portal Technologies / Frameshift briefing.
- Curated signal report: short editorial intro in Snow's voice, category
  framing, tight factual items, each item carrying its source link.
- Structured rundown, not a listicle. No bullet-heavy item descriptions.""",
}


def voice_version(context_dir: Path | None = None) -> str:
    f = (context_dir or REPO_ROOT / "context") / "brand-voice.md"
    if not f.is_file():
        return "missing"
    return hashlib.sha256(f.read_bytes()).hexdigest()[:12]


def _length_guidance(fmt: str) -> str:
    """A loud, numeric length requirement for the user prompt. Models
    (small local ones especially) undershoot length targets, so the stated
    aim sits well above the floor: an undershoot still clears the bound."""
    bounds = S.LENGTH_BOUNDS.get(fmt)
    if not bounds:
        return ""
    unit, lo, hi = bounds
    if unit == "words":
        target = lo + (hi - lo) // 3
        return (f"\nLENGTH REQUIREMENT, not negotiable: the piece must be "
                f"between {lo} and {hi} words. Aim for about {target} words. "
                f"Anything under {lo} words will be rejected by the reviewer, "
                "so develop each section fully with concrete specifics from "
                "the source note rather than summarizing.")
    return (f"\nLENGTH REQUIREMENT, not negotiable: {lo} to {hi} {unit}, "
            f"no more.")


def _feedback_addendum(feedback: str, fmt: str) -> str:
    """Turn reviewer fail reasons into direct instructions. Length failures
    get an explicit expand/trim order; small models don't infer it from the
    raw bound."""
    text = ("\n\nA reviewer failed the previous draft for these specific "
            f"reasons; fix them without losing the voice:\n{feedback}")
    if "length_bounds" in feedback:
        bounds = S.LENGTH_BOUNDS.get(fmt)
        if bounds and bounds[0] == "words":
            _, lo, hi = bounds
            target = lo + (hi - lo) // 3
            text += (f"\n\nThe previous draft failed on LENGTH. This time "
                     f"write the full length: at least {lo} words, aiming "
                     f"for about {target}. Expand every section with "
                     "concrete detail from the source note (what happened, "
                     "what it cost, what changed). Do not pad with filler; "
                     "add substance.")
        elif bounds:
            _, lo, hi = bounds
            text += (f"\n\nThe previous draft failed on LENGTH: this format "
                     f"is {lo} to {hi} sentences TOTAL. Reply with only the "
                     f"observation itself, at most {hi} sentences, nothing "
                     "before or after it.")
        else:
            text += ("\n\nThe previous draft failed on LENGTH. Respect the "
                     "stated bound exactly this time.")
    return text


def _ensure_gist_line(client: llm.LLMClient, angle: S.AngleOption,
                      note: S.CaptureNote, text: str) -> str:
    """Substack essays open with an AEO gist line. It is paratext (a subject
    line, not the piece), so the writer owns producing it as a separate
    focused step instead of hoping the model remembers it while also fixing
    length and lingo. If the draft already opens with one, keep it."""
    stripped = text.strip()
    first = stripped.splitlines()[0].strip() if stripped else ""
    if first.startswith("> "):
        return stripped
    try:
        line = client.complete_text(
            "gist",
            "Write exactly one line for the top of a Substack essay: a "
            "blockquote starting '> Covered here:' that names the actual "
            "tools, projects and concepts the essay discusses. Direct, not "
            "teasing, under 35 words, no em dashes. Reply with that one "
            "line only.",
            f"ESSAY:\n{stripped[:1500]}\n\nSOURCE NOTE:\n{note.raw_text[:500]}",
            max_tokens=80).strip().splitlines()[0].strip()
        if not line.startswith(">"):
            line = "> " + line.lstrip("> ").strip()
        line = line.replace("—", ",")  # paratext obeys the em dash ban too
    except llm.LLMError:
        line = f"> Covered here: {angle.title}."
    return line + "\n\n" + stripped


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
                feedback: str | None = None,
                previous_draft: str | None = None) -> S.WriterOutput:
    """First draft (revision 0) or a reviewer-feedback revision.

    Retries carry the failed draft: revising a concrete text ("expand these
    sections", "remove that em dash") is a far easier task than cold-writing
    the piece again, especially for small local models, and cold rewrites
    risk introducing new violations in place of the fixed ones."""
    user = (f"ANGLE:\n  title: {angle.title}\n  hook: {angle.hook}\n"
            f"  pillar: {angle.pillar}\n  format: {angle.format}\n"
            f"  why: {angle.rationale} ({angle.strategic_rationale})\n\n"
            f"SOURCE NOTE:\n{note.raw_text}\n"
            + (f"SOURCE URL: {note.source_url}\n" if note.source_url else "")
            + f"\nCONTEXT:\n{_writing_context()}\n\n"
            f"FORMAT BRIEF:\n{FORMAT_BRIEFS[angle.format]}\n\n"
            f"Write the {angle.format} piece. Reply with the piece only."
            + _length_guidance(angle.format))
    if feedback:
        if previous_draft:
            user += ("\n\nPREVIOUS DRAFT (failed review):\n" + previous_draft
                     + "\n\nRevise THIS draft rather than starting over: fix "
                       "the listed problems and keep everything that was not "
                       "flagged.")
        user += _feedback_addendum(feedback, angle.format)
        text = client.complete_text("revise_draft", WRITER_SYSTEM, user,
                                    max_tokens=3000)
    else:
        text = client.complete_text("draft", WRITER_SYSTEM, user, max_tokens=3000)

    if angle.format == "substack_essay":
        text = _ensure_gist_line(client, angle, note, text)

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
            f"FORMAT BRIEF:\n{FORMAT_BRIEFS[current.format]}\n\n"
            "Apply exactly this change. Keep everything she did not ask you "
            "to change, keep the format rules, reply with the full revised "
            "piece only." + _length_guidance(current.format))
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
