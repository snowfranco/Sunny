"""PipelineRunLog helpers (tier 3 guardrail).

Every step of every run gets a row. tools/passrate.py and the 2-4 week
review read from here.
"""

from __future__ import annotations

from . import db
from . import schemas as S


def log_step(
    conn,
    run_id: str,
    step: str,
    ref_id: str,
    input_ref: str = "",
    output_ref: str = "",
    pass_fail: bool | None = None,
    human_override: bool = False,
) -> S.PipelineRunLog:
    entry = S.PipelineRunLog(
        run_id=run_id,
        step=step,
        ref_id=ref_id,
        input_ref=input_ref,
        output_ref=output_ref,
        pass_fail=pass_fail,
        human_override=human_override,
        timestamp=S.now_iso(),
    )
    db.save_run_log(conn, entry)
    return entry
