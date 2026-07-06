#!/usr/bin/env python3
"""Reviewer pass-rate from PipelineRunLog (tier 3 guardrail).

    python3 tools/passrate.py [--days 28]

Read during the same 2-4 week sitting as the growth report: overall
pass-rate, first-try pass-rate, escalation count, and which checklist
criteria keep failing. Repeated failure reasons are the actionable part;
they say whether to fix the writer prompt, the checklist, or the voice doc.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import db  # noqa: E402
from pipeline import schemas as S  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28,
                    help="window in days (default 28)")
    args = ap.parse_args()

    conn = db.connect()
    db.init_db(conn)
    since = (_dt.date.today() - _dt.timedelta(days=args.days)).isoformat()
    rows = conn.execute(
        "SELECT run_id, pass_fail, output_ref, timestamp FROM pipeline_run_log "
        "WHERE step = 'reviewer' AND date(timestamp) >= ? ORDER BY timestamp",
        (since,)).fetchall()

    if not rows:
        print(f"no reviewer entries in the last {args.days} days")
        return 0

    total = len(rows)
    passed = sum(1 for r in rows if r["pass_fail"] == 1)

    # Per run: did the first review pass? Did the run end escalated
    # (all reviews failed, i.e. the retry bound was exhausted)?
    by_run: dict[str, list] = defaultdict(list)
    for r in rows:
        by_run[r["run_id"]].append(r)
    first_try = sum(1 for revs in by_run.values() if revs[0]["pass_fail"] == 1)
    escalated = sum(
        1 for revs in by_run.values()
        if len(revs) == S.MAX_REVIEWER_RETRIES + 1
        and all(rv["pass_fail"] == 0 for rv in revs))

    reasons: Counter = Counter()
    for r in rows:
        if r["pass_fail"] == 0 and r["output_ref"]:
            for part in str(r["output_ref"]).split(";"):
                crit = part.strip().split(":")[0]
                if crit:
                    reasons[crit] += 1

    print(f"reviewer pass-rate, last {args.days} days")
    print(f"  reviews:            {total}")
    print(f"  passed:             {passed}  ({passed / total:.0%})")
    print(f"  runs:               {len(by_run)}")
    print(f"  first-try pass:     {first_try}  ({first_try / len(by_run):.0%})")
    print(f"  escalated runs:     {escalated}")
    if reasons:
        print("  repeated failure reasons:")
        for crit, n in reasons.most_common():
            print(f"    {n:>3}  {crit}")
    else:
        print("  repeated failure reasons: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
