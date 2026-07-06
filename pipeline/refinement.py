"""The refinement conversation, shared by the angle-pick and edit stages.

This is the pattern from the brief's sequence diagram: the engine proposes,
Snow replies in plain language ("combine options 2 and 3, angle it for solo
builders"), the engine revises, repeat. It is a conversation, not a
single-shot choice, and it is bounded: after MAX_REFINEMENT_TURNS
back-and-forth turns the system stops iterating and asks Snow to decide.
Endless bikeshedding with an infinitely patient partner is a real failure
mode; the cap is the guardrail.

A "turn" is one Snow message plus the engine's reply, sharing a
turn_number. Turn accounting lives in the DB, so the CLI and the local web
page share the same bounded session.
"""

from __future__ import annotations

from . import db
from . import schemas as S

FORCE_DECISION_PROMPT = ("want to just lock this in, or should we start over "
                         "with a different topic?")


class RefinementCapReached(RuntimeError):
    """The 5-turn cap was hit; the system must force a decision, not iterate."""

    def __init__(self):
        super().__init__(FORCE_DECISION_PROMPT)


class RefinementSession:
    def __init__(self, conn, session_id: str, kind: str):
        assert kind in ("angle", "edit")
        self.conn = conn
        self.session_id = session_id
        self.kind = kind

    # -- state ----------------------------------------------------------------

    @property
    def turns_used(self) -> int:
        return db.refinement_turn_count(self.conn, self.session_id, speaker="you")

    @property
    def turns_remaining(self) -> int:
        return max(0, S.MAX_REFINEMENT_TURNS - self.turns_used)

    @property
    def cap_reached(self) -> bool:
        return self.turns_used >= S.MAX_REFINEMENT_TURNS

    def history(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM refinement_turns WHERE session_id = ? "
            "ORDER BY turn_number, CASE speaker WHEN 'you' THEN 0 ELSE 1 END",
            (self.session_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- turns ----------------------------------------------------------------

    def user_turn(self, message: str) -> int:
        """Record Snow's message. Raises RefinementCapReached at the cap;
        the caller surfaces FORCE_DECISION_PROMPT instead of iterating."""
        if self.cap_reached:
            raise RefinementCapReached()
        n = self.turns_used + 1
        turn = S.RefinementTurn(
            session_id=self.session_id, turn_number=n, speaker="you",
            message=message, resulting_angle_or_draft_id=None,
            timestamp=S.now_iso())
        db.save_refinement_turn(self.conn, turn, kind=self.kind)
        return n

    def engine_turn(self, message: str, resulting_id: str | None = None) -> int:
        n = max(1, self.turns_used)
        turn = S.RefinementTurn(
            session_id=self.session_id, turn_number=n, speaker="engine",
            message=message, resulting_angle_or_draft_id=resulting_id,
            timestamp=S.now_iso())
        db.save_refinement_turn(self.conn, turn, kind=self.kind)
        return n


def start_session(conn, kind: str, session_id: str | None = None) -> RefinementSession:
    return RefinementSession(conn, session_id or S.new_id(), kind)
