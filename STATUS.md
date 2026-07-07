# Build status notes

One note per phase, newest at the top. Written during the initial build
session; future sessions should keep appending here.

## Model routing + mock-mode visibility (2026-07-07)

The four handed-over fixes turned out to be three-quarters unapplied: the
tree was clean at 70c47e3, which had only the lexicon and the run/export
routes. Now landed: llm.py routes by model prefix (ollama/* to a local
Ollama at config.ollama_host(), gemini* via google-generativeai, everything
else Anthropic; unset still means mock, deliberately, with no default model
anywhere), /api/suggestions carries a mock_mode boolean, and the page shows
a loud banner when it's true. JSON calls request native JSON mode from
Ollama/Gemini, and list-shaped replies tolerate the single-key object
wrapping small local models love, so llama3.1:8b won't burn its retries on
formatting. Verified live against a stub Ollama on 11434: mock_mode flips
false and angles reflect the actual topic. 75 tests green, goldens clean.

## UI overhaul + checker lexicon (2026-07-07, from Snow's files)

Applied Snow's redesigned single-page UI (staged flow: Suggestions ->
Angle -> Draft -> Export, offline sample mode when the server is down) and
wired the two routes it needed, /api/run and /api/export, so the whole
pipeline now runs from the browser; the exports panel states plainly that
nothing is ever published. The banned-lingo and signpost lists moved into a
CHECKER-LEXICON block in context/brand-voice.md as the single source of
truth; reviewer.py parses it live with cached fallbacks. Three integration
fixes on top of the drop: the UI now threads the edit session id (cap
accounting starts on turn one), guards the cap-reached response (was
blanking the draft to "undefined"), and /api/run records PickedAngle since
the UI skips the separate pick step. 65 tests green, goldens re-run clean
after the voice-file change, full UI flow smoke-tested capture to bundle.

## Phase 6 — Golden fixtures + pass-rate script (2026-07-06)

Nine fixtures, 3 per pillar, all five formats covered, each with a real
note and a golden post that passes the mechanical rules today (also pinned
by a unit test, so drift shows up in the normal suite). run_goldens.py does
compliance plus a full writer-reviewer regeneration into data/goldens/ for
by-eye diffing; passrate.py reads PipelineRunLog for pass-rate, first-try
rate, escalations, and repeated failure reasons. Building the fixtures
caught two real bugs: the fragment check punished scripts for spoken rhythm
(now format-aware, threshold 6 for scripts) and the mock writer ignored
target format (now honors the angle's format line). 60 tests green.

## Phase 5 — Analytics + Growth researcher (2026-07-06)

Flag raised as the brief anticipated: neither platform has a usable public
analytics API for this case (Substack has none; LinkedIn's needs partner
access), so manual paste-in via `analytics add` is the designed v1 path,
documented in analytics.py where a future fetcher would slot in. Growth
report aggregates deterministically (top performers, per-pillar rollups,
reviewer pass-rate and repeated failure reasons from PipelineRunLog, all in
one sitting per tier 3), with the LLM adding only trend notes and
recommendations over those numbers. context-update records ContextUpdateLog;
running the CLI is Snow's approval. 57 tests green.

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
