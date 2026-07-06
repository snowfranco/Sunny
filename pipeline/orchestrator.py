"""Orchestrator: the core reliability piece.

writer -> reviewer, bounded: a failing review loops back to the writer with
the specific fail reasons at most MAX_REVIEWER_RETRIES (2) times. A third
failure escalates to Snow with the reason attached; the system never spins.

After a pass, the draft enters the edit stage: the same conversational
refinement pattern as angle-picking (5-turn cap, then a decision prompt).
Snow can request changes in plain language, hand-edit externally, or approve.
Approval records the EditedPost; repurpose + export continue from there.

Every step is logged to PipelineRunLog (tier 3 guardrail).
"""

from __future__ import annotations

from . import db, llm, refinement, reviewer, writer
from . import schemas as S
from .runlog import log_step


class EscalationRequired(RuntimeError):
    """Reviewer failed MAX_REVIEWER_RETRIES+1 times; a human decides now."""

    def __init__(self, post_id: str, fail_reason: str):
        self.post_id = post_id
        self.fail_reason = fail_reason
        super().__init__(
            f"draft {post_id} failed review {S.MAX_REVIEWER_RETRIES + 1} times; "
            f"escalating to Snow. Last reasons: {fail_reason}")


def run_review_loop(conn, angle: S.AngleOption, note: S.CaptureNote,
                    client: llm.LLMClient, run_id: str) -> S.ReviewerVerdict:
    """Write, review, retry on fail (bounded), return the passing verdict.
    Raises EscalationRequired after the bound; the last draft and verdict
    stay in the db for Snow to inspect."""
    draft = writer.write_draft(conn, angle, note, client)
    log_step(conn, run_id, "writer", draft.post_id,
             input_ref=angle.angle_id, output_ref=f"rev0")

    for attempt in range(S.MAX_REVIEWER_RETRIES + 1):
        verdict = reviewer.review(
            post_id=draft.post_id, draft_text=draft.draft_text,
            pillar=draft.pillar, fmt=draft.format,
            source_note=note.raw_text, revision_count=attempt, client=client)
        db.save_verdict(conn, verdict)
        log_step(conn, run_id, "reviewer", draft.post_id,
                 input_ref=f"rev{attempt}", output_ref=verdict.fail_reason or "pass",
                 pass_fail=verdict.passed)
        if verdict.passed:
            return verdict
        if attempt < S.MAX_REVIEWER_RETRIES:
            draft = writer.write_draft(
                conn, angle, note, client, post_id=draft.post_id,
                revision=attempt + 1, feedback=verdict.fail_reason)
            log_step(conn, run_id, "writer", draft.post_id,
                     input_ref=verdict.fail_reason or "", output_ref=f"rev{attempt + 1}")

    raise EscalationRequired(draft.post_id, verdict.fail_reason or "unknown")


def run_pipeline(conn, angle_id: str) -> dict:
    """Picked angle -> reviewed draft (bounded loop) -> awaiting Snow's edit.
    Returns a status dict; never publishes anything anywhere."""
    angle = db.get_angle(conn, angle_id)
    if not angle:
        raise KeyError(f"no angle {angle_id}")
    note = db.get_note(conn, angle.note_id)
    if not note:
        raise KeyError(f"no note {angle.note_id} for angle {angle_id}")

    run_id = S.new_id()
    client = llm.LLMClient(run_id=run_id)
    try:
        verdict = run_review_loop(conn, angle, note, client, run_id)
    except EscalationRequired as e:
        return {"status": "escalated", "run_id": run_id, "post_id": e.post_id,
                "fail_reason": e.fail_reason,
                "next": "review the draft yourself; the specific failures are attached"}

    # Artist scaffold runs alongside the passing draft (Phase 3).
    image = _run_artist(conn, verdict.post_id, client, run_id)

    return {"status": "awaiting_edit", "run_id": run_id,
            "post_id": verdict.post_id,
            "revisions_used": verdict.revision_count,
            "image_path": image.image_path if image else None,
            "next": f"edit conversationally: python3 -m pipeline edit {verdict.post_id}, "
                    f"or open http://127.0.0.1:8787/?post={verdict.post_id}"}


def _run_artist(conn, post_id: str, client: llm.LLMClient, run_id: str):
    """Wired in Phase 3; kept behind one call site so the orchestrator flow
    doesn't change shape later."""
    try:
        from . import artist
    except ImportError:
        return None
    out = artist.generate(conn, post_id, client)
    log_step(conn, run_id, "artist", post_id, output_ref=out.image_path,
             pass_fail=None)
    return out


# --- edit stage (reuses the refinement conversation pattern) -----------------

def edit_session_for(conn, post_id: str,
                     session_id: str | None = None) -> refinement.RefinementSession:
    return refinement.start_session(conn, "edit", session_id)


def apply_edit_request(conn, post_id: str, message: str,
                       session: refinement.RefinementSession,
                       client: llm.LLMClient | None = None) -> S.WriterOutput:
    """One edit-stage turn: plain-language change -> revised draft.
    Raises RefinementCapReached at the cap (caller surfaces the prompt)."""
    current = db.get_latest_draft(conn, post_id)
    if not current:
        raise KeyError(f"no draft for post {post_id}")
    client = client or llm.LLMClient(run_id=f"edit-{post_id[:8]}")
    session.user_turn(message)
    revision = db.next_revision(conn, post_id)
    revised = writer.revise_for_edit(conn, current, message, client, revision)
    session.engine_turn("revised per your note", resulting_id=revised.post_id)
    return revised


def approve_post(conn, post_id: str, final_text: str | None = None) -> S.EditedPost:
    """Snow approves. final_text overrides when she hand-edited elsewhere
    (direct manual editing stays a first-class path)."""
    if final_text is None:
        current = db.get_latest_draft(conn, post_id)
        if not current:
            raise KeyError(f"no draft for post {post_id}")
        final_text = current.draft_text
    edited = S.EditedPost(post_id=post_id, final_text=final_text,
                          edited_at=S.now_iso())
    db.save_edited_post(conn, edited)
    return edited


# --- API adapters used by serve.py -------------------------------------------

def edit_refine_api(conn, body: dict) -> dict:
    post_id = str(body["post_id"])
    session = edit_session_for(conn, post_id, body.get("session_id"))
    message = body.get("message")
    if message:  # None/empty means "open the panel, show current state"
        revised = apply_edit_request(conn, post_id, str(message), session)
        draft_text = revised.draft_text
    else:
        current = db.get_latest_draft(conn, post_id)
        if not current:
            raise KeyError(f"no draft for post {post_id}")
        draft_text = current.draft_text
    out = {"post_id": post_id, "session_id": session.session_id,
           "draft_text": draft_text, "turns_remaining": session.turns_remaining}
    if session.cap_reached:
        out["prompt"] = refinement.FORCE_DECISION_PROMPT
    return out


def approve_api(conn, body: dict) -> dict:
    post_id = str(body["post_id"])
    edited = approve_post(conn, post_id, body.get("final_text"))
    return {"post_id": edited.post_id, "approved_at": edited.edited_at,
            "next": f"python3 -m pipeline export {post_id}"}
