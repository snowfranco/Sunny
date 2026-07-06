"""Repurpose: approved post -> LinkedIn extract + Notes hook.

Multi-format generation happens in two places by design: the Writer already
writes any of the five formats (including the Portal briefing) when that is
the picked angle's target; this module derives the companion formats from an
approved piece. Output is schema-validated (paragraph bounds, no headers)
with a bounded re-ask, like every other handoff.
"""

from __future__ import annotations

from . import db, llm
from . import schemas as S

REPURPOSE_SYSTEM = """You repurpose an approved piece by Snow Abad into two
companion formats, in her voice (conversational not fragmented, no em
dashes, no signpost sentences, no performed lingo, never "this is not X,
it's Y"):
1. linkedin_extract: 3-6 tight paragraphs, no headers, starts with the
   situation, ends on a genuine question or open thought. 100-200 words.
2. notes_hook: 1-2 sentences for Substack Notes, one real observation, can
   be mid-thought, wry over funny, specific over relatable.
Reply as JSON: {"linkedin_extract": "...", "notes_hook": "..."}"""

MAX_SCHEMA_RETRIES = 2


def repurpose(conn, post_id: str,
              client: llm.LLMClient | None = None) -> S.RepurposedFormats:
    edited = db.get_edited_post(conn, post_id)
    if not edited:
        raise KeyError(f"post {post_id} has no approved (edited) text yet; "
                       "approve it before repurposing")
    client = client or llm.LLMClient(run_id=f"repurpose-{post_id[:8]}")

    user = f"THE APPROVED PIECE:\n{edited.final_text}"
    last_err: Exception | None = None
    for _ in range(1 + MAX_SCHEMA_RETRIES):
        try:
            raw = client.complete_json("repurpose", REPURPOSE_SYSTEM, user)
            out = S.RepurposedFormats(
                post_id=post_id,
                linkedin_extract=str(raw.get("linkedin_extract", "")),
                notes_hook=str(raw.get("notes_hook", "")),
                generated_at=S.now_iso(),
            )
            db.save_repurposed(conn, out)
            return out
        except (S.SchemaError, llm.LLMError) as e:
            last_err = e
            user += f"\n\nYour previous reply was invalid ({e}). Fix it."
    raise S.SchemaError(
        f"repurpose produced invalid output after {1 + MAX_SCHEMA_RETRIES} "
        f"attempts: {last_err}")
