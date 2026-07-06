#!/usr/bin/env python3
"""Golden-set runner (tier 2 guardrail).

Run manually whenever context/brand-voice.md, context/pillars.md, or the
model version changes:

    python3 tools/run_goldens.py

Two passes:
1. Compliance: every golden post must pass the CURRENT mechanical reviewer
   rules. A failure means the voice rules and the goldens drifted apart;
   a human decides which side is right. Nonzero exit.
2. Regeneration: each fixture's note goes through the real writer+reviewer
   loop (mock mode when PIPELINE_MODEL is unset) and lands in
   data/goldens/run-<UTC timestamp>/ next to the golden, for diffing
   against the last-known-good run BY EYE. No similarity score, on purpose.
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import db, llm, orchestrator, reviewer  # noqa: E402
from pipeline import schemas as S  # noqa: E402
from pipeline.config import load_config  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "fixtures"
SECTION_RE = re.compile(r"^--- (meta|note|golden) ---$", re.MULTILINE)


def load_fixtures() -> list[dict]:
    fixtures = []
    for path in sorted(FIXTURES_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        parts = SECTION_RE.split(path.read_text(encoding="utf-8"))
        # parts: ['', 'meta', <meta>, 'note', <note>, 'golden', <golden>]
        sections = dict(zip(parts[1::2], (p.strip() for p in parts[2::2])))
        meta = {}
        for line in sections.get("meta", "").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        fixtures.append({
            "path": path,
            "fixture_id": meta.get("fixture_id", path.stem),
            "pillar": meta["pillar"],
            "format": meta["format"],
            "source": meta.get("source", "manual"),
            "source_url": meta.get("source_url") or None,
            "note": sections["note"],
            "golden": sections["golden"],
        })
    return fixtures


def check_coverage(fixtures: list[dict]) -> list[str]:
    problems = []
    if not 8 <= len(fixtures) <= 10:
        problems.append(f"expected 8-10 fixtures, found {len(fixtures)}")
    per_pillar: dict[str, int] = {}
    formats = set()
    for f in fixtures:
        per_pillar[f["pillar"]] = per_pillar.get(f["pillar"], 0) + 1
        formats.add(f["format"])
    for p in S.PILLARS:
        if not 2 <= per_pillar.get(p, 0) <= 3:
            problems.append(f"pillar {p}: {per_pillar.get(p, 0)} fixtures (want 2-3)")
    missing = set(S.FORMATS) - formats
    if missing:
        problems.append(f"formats with no fixture: {sorted(missing)}")
    return problems


def compliance_pass(fixtures: list[dict]) -> bool:
    ok = True
    print("== pass 1: goldens vs current mechanical rules ==")
    for f in fixtures:
        items = reviewer.mechanical_checklist(f["golden"], f["format"])
        fails = [c for c in items if not c.passed]
        status = "PASS" if not fails else "FAIL"
        print(f"  {status}  {f['fixture_id']}  ({f['pillar']}/{f['format']})")
        for c in fails:
            print(f"        - {c.criterion}: {c.note}")
            ok = False
    return ok


def regeneration_pass(fixtures: list[dict]) -> Path:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = load_config().data_path / "goldens" / f"run-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = "mock" if llm.LLMClient("goldens").mock else "real model"
    print(f"\n== pass 2: regeneration through writer+reviewer ({mode}) ==")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)

    for f in fixtures:
        note = S.CaptureNote(note_id=S.new_id(), source=f["source"],
                            raw_text=f["note"], created_at=S.now_iso(),
                            source_url=f["source_url"])
        db.save_note(conn, note)
        angle = S.AngleOption(
            note_id=note.note_id, angle_id=S.new_id(), pillar=f["pillar"],
            format=f["format"], title=f["fixture_id"][:80],
            hook=f["note"][:150], strategic_rationale="immediate_credibility",
            rationale="golden fixture regeneration")
        db.save_angle(conn, angle)

        client = llm.LLMClient(run_id=f"golden-{f['fixture_id']}")
        try:
            verdict = orchestrator.run_review_loop(
                conn, angle, note, client, run_id=f"golden-{f['fixture_id']}")
            draft = db.get_latest_draft(conn, verdict.post_id)
            outcome = f"reviewer PASS after {verdict.revision_count} revision(s)"
            body = draft.draft_text
        except orchestrator.EscalationRequired as e:
            outcome = f"ESCALATED: {e.fail_reason}"
            draft = db.get_latest_draft(conn, e.post_id)
            body = draft.draft_text if draft else "(no draft)"

        report = (f"# {f['fixture_id']}  ({f['pillar']}/{f['format']})\n\n"
                  f"outcome: {outcome}\n\n"
                  f"--- regenerated ---\n\n{body}\n\n"
                  f"--- golden (last-known-good) ---\n\n{f['golden']}\n")
        (out_dir / f"{f['fixture_id']}.md").write_text(report, encoding="utf-8")
        print(f"  {f['fixture_id']}: {outcome}")

    print(f"\nwrote {out_dir}")
    print("diff against the previous run-* directory by eye; that judgment "
          "call is the guardrail.")
    return out_dir


def main() -> int:
    fixtures = load_fixtures()
    problems = check_coverage(fixtures)
    if problems:
        print("coverage problems:")
        for pr in problems:
            print(f"  - {pr}")
        return 1
    print(f"{len(fixtures)} fixtures, coverage OK "
          f"(3 pillars, all {len(S.FORMATS)} formats)\n")
    ok = compliance_pass(fixtures)
    regeneration_pass(fixtures)
    if not ok:
        print("\nRESULT: goldens and voice rules have drifted apart; "
              "reconcile before trusting new generations.")
        return 1
    print("\nRESULT: all goldens comply with current rules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
