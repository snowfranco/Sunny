"""CLI entry point: python3 -m pipeline <command> [...].

Capture from any terminal, run research, drive the pipeline. The refinement
conversations also work here (the local page is nicer, but nothing requires
it).
"""

from __future__ import annotations

import argparse
import json
import sys

from . import angle_engine, capture, db, refinement, researcher
from . import schemas as S
from .config import load_config


def cmd_init(args) -> int:
    cfg = load_config()
    conn = db.connect(cfg.db_path)
    db.init_db(conn)
    conn.close()
    print(f"initialized {cfg.db_path}")
    return 0


def cmd_capture(args) -> int:
    conn = db.connect()
    db.init_db(conn)
    note = capture.capture_manual(conn, " ".join(args.text))
    print(f"captured {note.note_id}")
    print(f"next: python3 -m pipeline angles {note.note_id}")
    return 0


def cmd_ingest_inbox(args) -> int:
    conn = db.connect()
    db.init_db(conn)
    notes = capture.ingest_inbox(conn)
    for n in notes:
        print(f"captured {n.note_id}: {n.raw_text[:60]!r}")
    if not notes:
        print("inbox empty")
    return 0


def cmd_watch_inbox(args) -> int:
    capture.watch_inbox(interval=args.interval)
    return 0


def cmd_research(args) -> int:
    conn = db.connect()
    db.init_db(conn)
    payload = researcher.research(conn)
    np, nl = len(payload["project_suggestions"]), len(payload["landscape_suggestions"])
    print(f"research done: {np} project suggestion(s), {nl} landscape suggestion(s)")
    print(f"wrote {load_config().suggestions_file}")
    return 0


def cmd_notes(args) -> int:
    conn = db.connect()
    db.init_db(conn)
    for n in db.list_notes(conn)[:args.limit]:
        print(f"{n.note_id}  [{n.source}]  {n.raw_text[:70]!r}")
    return 0


def cmd_angles(args) -> int:
    conn = db.connect()
    db.init_db(conn)
    note = db.get_note(conn, args.note_id)
    if not note:
        print(f"no note {args.note_id}", file=sys.stderr)
        return 1
    angles = angle_engine.generate_angles(conn, note)
    _print_angles(angles)
    print("\nrefine conversationally: python3 -m pipeline refine "
          f"{angles[0].angle_id}   (or pick: python3 -m pipeline pick <angle_id>)")
    return 0


def _print_angles(angles: list[S.AngleOption]) -> None:
    for i, a in enumerate(angles, 1):
        print(f"\n{i}. {a.title}")
        print(f"   {a.hook}")
        print(f"   [{a.pillar} · {a.format} · {a.strategic_rationale}] {a.rationale}")
        print(f"   angle_id: {a.angle_id}")


def cmd_refine(args) -> int:
    """Interactive angle refinement; the same bounded loop the page uses."""
    conn = db.connect()
    db.init_db(conn)
    angle = db.get_angle(conn, args.angle_id)
    if not angle:
        print(f"no angle {args.angle_id}", file=sys.stderr)
        return 1
    session = refinement.start_session(conn, "angle")
    print(f"refining: {angle.title}\n(quit with 'proceed' to lock in, or Ctrl-C)")
    while True:
        try:
            msg = input(f"[{session.turns_remaining} turns left] you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not msg:
            continue
        if msg.lower() in ("proceed", "lock it in", "sounds good, proceed"):
            angle_engine.pick_angle(conn, angle)
            print(f"locked in, handing to orchestrator: "
                  f"python3 -m pipeline run {angle.angle_id}")
            return 0
        try:
            session.user_turn(msg)
        except refinement.RefinementCapReached:
            print(f"engine> {refinement.FORCE_DECISION_PROMPT}")
            return 0
        angle = angle_engine.refine_angle(conn, angle, msg)
        session.engine_turn(f"Revised: {angle.title}", resulting_id=angle.angle_id)
        _print_angles([angle])
        if session.cap_reached:
            print(f"\nengine> {refinement.FORCE_DECISION_PROMPT}")


def cmd_pick(args) -> int:
    conn = db.connect()
    db.init_db(conn)
    angle = db.get_angle(conn, args.angle_id)
    if not angle:
        print(f"no angle {args.angle_id}", file=sys.stderr)
        return 1
    angle_engine.pick_angle(conn, angle)
    print(f"picked. next: python3 -m pipeline run {angle.angle_id}")
    return 0


def cmd_serve(args) -> int:
    from .serve import serve
    serve(port=args.port)
    return 0


def cmd_run(args) -> int:
    """Picked angle -> writer -> bounded reviewer loop -> awaiting edit."""
    from . import orchestrator
    conn = db.connect()
    db.init_db(conn)
    result = orchestrator.run_pipeline(conn, args.angle_id)
    if result["status"] == "escalated":
        print("ESCALATED after the retry bound. The reviewer's specific reasons:")
        print(f"  {result['fail_reason']}")
        print(f"draft is saved as post {result['post_id']}; "
              "edit it yourself or start over with a different angle.")
        return 2
    draft = db.get_latest_draft(conn, result["post_id"])
    print(f"review passed (revisions used: {result['revisions_used']}). "
          f"post_id: {result['post_id']}")
    print("-" * 60)
    print(draft.draft_text)
    print("-" * 60)
    print(result["next"])
    return 0


def cmd_edit(args) -> int:
    """Edit-stage conversation: request changes in plain language, approve,
    or paste your own final text. Same bounded loop as angle refinement."""
    from . import orchestrator
    conn = db.connect()
    db.init_db(conn)
    current = db.get_latest_draft(conn, args.post_id)
    if not current:
        print(f"no draft for post {args.post_id}", file=sys.stderr)
        return 1
    session = orchestrator.edit_session_for(conn, args.post_id)
    print(current.draft_text)
    print("\n(request changes in plain language; 'approve' locks it in)")
    while True:
        try:
            msg = input(f"[{session.turns_remaining} turns left] you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not msg:
            continue
        if msg.lower() == "approve":
            orchestrator.approve_post(conn, args.post_id)
            print(f"approved. next: python3 -m pipeline export {args.post_id}")
            return 0
        try:
            revised = orchestrator.apply_edit_request(
                conn, args.post_id, msg, session)
        except refinement.RefinementCapReached:
            print(f"engine> {refinement.FORCE_DECISION_PROMPT}")
            continue
        print("-" * 60)
        print(revised.draft_text)
        print("-" * 60)
        if session.cap_reached:
            print(f"engine> {refinement.FORCE_DECISION_PROMPT}")


def cmd_approve(args) -> int:
    from . import orchestrator
    conn = db.connect()
    db.init_db(conn)
    final_text = None
    if args.from_file:
        from pathlib import Path
        final_text = Path(args.from_file).read_text(encoding="utf-8")
    orchestrator.approve_post(conn, args.post_id, final_text)
    print(f"approved. next: python3 -m pipeline export {args.post_id}")
    return 0


def cmd_export(args) -> int:
    """Repurpose (if needed) + assemble the draft bundle. Never publishes."""
    from . import export as export_mod
    from . import llm, repurpose
    from .runlog import log_step
    conn = db.connect()
    db.init_db(conn)
    run_id = S.new_id()
    if not db.get_repurposed(conn, args.post_id):
        rep = repurpose.repurpose(conn, args.post_id,
                                  llm.LLMClient(run_id=run_id))
        log_step(conn, run_id, "repurpose", args.post_id,
                 output_ref="linkedin_extract+notes_hook")
    bundle, out_dir = export_mod.export_bundle(conn, args.post_id)
    log_step(conn, run_id, "export", args.post_id, output_ref=str(out_dir),
             pass_fail=True)
    print(f"draft bundle written to {out_dir}")
    print("contents: post.md, linkedin.md, notes-hook.txt"
          + (", image + caption.txt" if bundle.image_path else "")
          + ", bundle.json")
    print("status: draft. Publishing is yours to do, manually, elsewhere.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipeline",
        description="sunny: Snow's content pipeline (drafts only, never publishes)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the SQLite db").set_defaults(fn=cmd_init)

    c = sub.add_parser("capture", help="capture a note from the terminal")
    c.add_argument("text", nargs="+")
    c.set_defaults(fn=cmd_capture)

    sub.add_parser("ingest-inbox", help="one-shot inbox.md ingestion") \
       .set_defaults(fn=cmd_ingest_inbox)

    w = sub.add_parser("watch-inbox", help="poll inbox.md for new notes")
    w.add_argument("--interval", type=float, default=2.0)
    w.set_defaults(fn=cmd_watch_inbox)

    sub.add_parser("research", help="project-doc scan + landscape scan") \
       .set_defaults(fn=cmd_research)

    n = sub.add_parser("notes", help="list captured notes")
    n.add_argument("--limit", type=int, default=20)
    n.set_defaults(fn=cmd_notes)

    a = sub.add_parser("angles", help="generate 3 angles for a note")
    a.add_argument("note_id")
    a.set_defaults(fn=cmd_angles)

    r = sub.add_parser("refine", help="conversational angle refinement")
    r.add_argument("angle_id")
    r.set_defaults(fn=cmd_refine)

    pk = sub.add_parser("pick", help="pick an angle")
    pk.add_argument("angle_id")
    pk.set_defaults(fn=cmd_pick)

    s = sub.add_parser("serve", help="local page (on-demand, Ctrl-C stops)")
    s.add_argument("--port", type=int, default=None)
    s.set_defaults(fn=cmd_serve)

    rn = sub.add_parser("run", help="picked angle -> draft -> bounded review")
    rn.add_argument("angle_id")
    rn.set_defaults(fn=cmd_run)

    e = sub.add_parser("edit", help="conversational edit stage for a post")
    e.add_argument("post_id")
    e.set_defaults(fn=cmd_edit)

    ap = sub.add_parser("approve", help="approve a draft (optionally hand-edited)")
    ap.add_argument("post_id")
    ap.add_argument("--from-file", help="use this file's contents as the final text")
    ap.set_defaults(fn=cmd_approve)

    ex = sub.add_parser("export", help="repurpose + write the draft bundle "
                                       "(never publishes)")
    ex.add_argument("post_id")
    ex.set_defaults(fn=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
