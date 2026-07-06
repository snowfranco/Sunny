"""Growth researcher: analytics + run log -> GrowthInsightReport.

Deterministic aggregation first (top performers, per-pillar rollups,
reviewer pass-rate from PipelineRunLog); the LLM contributes trend notes
and recommendations on top of those numbers, never instead of them.

This feeds the 2-4 week human review sitting: Snow reads the report, checks
reviewer pass-rate and repeated failure reasons (tier 3), updates context
files, and records the update via `context-update` (ContextUpdateLog).
"""

from __future__ import annotations

import datetime as _dt
import json
from collections import defaultdict

from . import analytics, db, llm
from . import schemas as S
from .config import load_config


def _pillar_of(conn, post_id: str) -> str | None:
    row = conn.execute(
        "SELECT pillar FROM writer_outputs WHERE post_id = ? LIMIT 1",
        (post_id,)).fetchone()
    return row["pillar"] if row else None


def reviewer_pass_stats(conn, start: str, end: str) -> dict:
    """Tier 3: pass-rate and repeated failure reasons for the period."""
    rows = conn.execute(
        "SELECT pass_fail, output_ref FROM pipeline_run_log "
        "WHERE step = 'reviewer' AND date(timestamp) BETWEEN ? AND ?",
        (start, end)).fetchall()
    total = len(rows)
    passed = sum(1 for r in rows if r["pass_fail"] == 1)
    reasons: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["pass_fail"] == 0 and r["output_ref"]:
            for part in str(r["output_ref"]).split(";"):
                crit = part.strip().split(":")[0]
                if crit:
                    reasons[crit] += 1
    return {
        "reviews": total,
        "pass_rate": round(passed / total, 3) if total else None,
        "repeated_failure_reasons": dict(
            sorted(reasons.items(), key=lambda kv: -kv[1])),
    }


def generate_report(conn, start: str | None = None, end: str | None = None,
                    client: llm.LLMClient | None = None) -> S.GrowthInsightReport:
    end_d = _dt.date.fromisoformat(end) if end else _dt.date.today()
    start_d = (_dt.date.fromisoformat(start) if start
               else end_d - _dt.timedelta(days=28))
    start_s, end_s = start_d.isoformat(), end_d.isoformat()

    snaps = analytics.snapshots_between(conn, start_s, end_s)

    # Aggregate per post (a post can have snapshots on both platforms).
    by_post: dict[str, float] = defaultdict(float)
    by_pillar: dict[str, list[float]] = defaultdict(list)
    for s in snaps:
        score = analytics.engagement_score(s)
        by_post[s.post_id] += score
        pillar = _pillar_of(conn, s.post_id)
        if pillar:
            by_pillar[pillar].append(score)

    top = [pid for pid, _ in
           sorted(by_post.items(), key=lambda kv: -kv[1])[:3]]

    pillar_performance = {}
    for p in S.PILLARS:
        scores = by_pillar.get(p, [])
        if scores:
            pillar_performance[p] = (
                f"{len(scores)} snapshot(s), total engagement "
                f"{round(sum(scores), 1)}, avg {round(sum(scores) / len(scores), 1)}")
        else:
            pillar_performance[p] = "no data this period"

    stats = reviewer_pass_stats(conn, start_s, end_s)

    client = client or llm.LLMClient(run_id="growth")
    llm_out = client.complete_json(
        "growth",
        "You are the growth researcher for Snow Abad's content pipeline. "
        "Given period aggregates, write short factual trend notes and 2-4 "
        "actionable recommendations. Ground every claim in the numbers "
        "provided; no invention. Reply as JSON: "
        '{"trend_notes": "...", "recommendations": ["..."]}',
        json.dumps({
            "period": [start_s, end_s],
            "post_scores": by_post,
            "pillar_performance": pillar_performance,
            "reviewer_stats": stats,
        }, indent=2))

    report = S.GrowthInsightReport(
        period_start=start_s,
        period_end=end_s,
        top_performers=top,
        pillar_performance=pillar_performance,
        trend_notes=str(llm_out.get("trend_notes", "")),
        recommendations=[str(r) for r in llm_out.get("recommendations", [])],
        generated_at=S.now_iso(),
    )
    db.save_growth_report(conn, report)
    _write_report_md(report, stats)
    return report


def _write_report_md(report: S.GrowthInsightReport, stats: dict) -> None:
    cfg = load_config()
    out_dir = cfg.data_path / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"growth-{report.period_end}.md"
    top_lines = [f"- {pid}" for pid in report.top_performers] or ["- none yet"]
    lines = [
        f"# Growth report, {report.period_start} to {report.period_end}",
        "",
        "## Top performers",
        *top_lines,
        "",
        "## Pillar performance",
        *(f"- **{p}**: {v}" for p, v in report.pillar_performance.items()),
        "",
        "## Reviewer health (tier 3, review in this same sitting)",
        f"- reviews: {stats['reviews']}, pass rate: {stats['pass_rate']}",
        f"- repeated failure reasons: {stats['repeated_failure_reasons'] or 'none'}",
        "",
        "## Trend notes",
        report.trend_notes,
        "",
        "## Recommendations",
        *(f"- {r}" for r in report.recommendations),
        "",
        "After reviewing: update context/*.md as needed and record it with",
        "`python3 -m pipeline context-update -f <file> -s \"<summary>\"`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def record_context_update(conn, changed_files: list[str],
                          summary: str) -> S.ContextUpdateLog:
    """Called from the CLI Snow runs herself; running it is the approval."""
    entry = S.ContextUpdateLog(
        updated_at=S.now_iso(),
        changed_files=changed_files,
        summary=summary,
        approved_by="snow",
    )
    db.save_context_update(conn, entry)
    return entry
