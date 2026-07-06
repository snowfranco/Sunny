# Build status notes

One note per phase, newest at the top. Written during the initial build
session; future sessions should keep appending here.

## Phase 4 — Repurpose + Export (2026-07-06)

Repurpose derives the LinkedIn extract (paragraph-bounded, header-free,
schema-enforced) and Notes hook from the approved text; the Portal briefing
already lives in the Writer as a first-class format. Export writes a local
draft bundle directory and nothing else. The no-publish constraint now sits
at four layers: schema validation, SQL CHECK, a code-level assertion on
every export, and a static test that greps the package for HTTP clients and
publish endpoints (only llm.py and localhost-only serve.py may speak HTTP).
52 tests green; bundle smoke-tested end to end via CLI.

## Phase 3 — Artist scaffold (2026-07-06)

Valid image + caption, exactly the v1 bar. The image is a deterministic
locally-generated SVG card (1200x630, title + pillar) so there is no
image-API dependency to decide yet; the caption goes through the LLM layer.
artist.py is the single swap-in point when an image model gets chosen, and
the orchestrator already calls it behind one call site so the flow won't
change shape. No quality rubric, no retry loop, per the brief. 47 tests.

## Phase 2 — Orchestrator + Writer + Reviewer loop (2026-07-06)

The reliability core. Reviewer implements the 9-point checklist literally:
banned patterns, length bounds, AEO gist, copyright hygiene and publish
claims are mechanical code checks (run first, free); voice match, insight
arrival, unresolved observation, door-opening last line, throwaway line,
claim traceability and pillar/format fit go to the LLM judge only after
mechanicals pass. Bounded loop verified by test: exactly 3 reviews then
EscalationRequired carrying the specific reasons. Edit stage reuses the
Phase 1 refinement session (same 5-turn cap); manual hand-edit stays a
first-class approve path. One judgment call: leverage/unlock are banned as
verbs only, so the mechanical check uses a determiner heuristic rather than
flagging every noun use. 45 tests green.

## Phase 1 — Capture + Researcher + Angle engine (2026-07-06)

CLI capture, inbox.md watcher (polling, stdlib), read-only project-doc
scanner, landscape scanner that drops any suggestion lacking a citable
source_url, and the angle engine producing 3 schema-validated options with
strategic_rationale. The refinement loop is one shared module used by both
CLI and the local page, with turn accounting in SQLite: verified live that
turn 5 surfaces "want to just lock this in..." and turn 6 refuses to
iterate. LLM layer has deterministic mock mode plus the per-run token
ceiling. 29 tests green; server routes smoke-tested with curl.

## Phase 0 — Scaffold (2026-07-06)

Repo structure, config layer (env-driven model, deliberately unset), all 13
handoff schemas as validated dataclasses, SQLite DDL with a CHECK constraint
that makes non-draft export bundles unstorable even via raw SQL, and the
PipelineRunLog. Context docs authored: brand-voice.md (operational),
brand-voice-source.md (verbatim), pillars, strategy, platforms. One addition
beyond the brief's schema list: CaptureNote grew an optional `source_url`,
mandatory when source is landscape_scan, which is how the citable-source
guardrail is enforced at the schema layer. 19 tests green, stdlib only.
