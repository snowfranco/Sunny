# Build status notes

One note per phase, newest at the top. Written during the initial build
session; future sessions should keep appending here.

## Escalation escape hatch + false-positive fix (2026-07-08)

Two things behind the endless escalations. First, a real checker bug: the
no_not_x_but_y pattern flagged plain contrastive "not X, but Y" (which is
on-voice, mirrors "that didn't work out, but here's what I learned"); only
the "not X, it's Y" / "not only X but Y" pivots are banned, so the bare
comma-but branch is removed. Second, the deeper product gap: on escalation
the UI discarded the near-miss draft and only offered "try a different
angle", trapping the user. The brief says escalate WITH the draft and keep
manual editing available. Now the escalation response carries the draft
text, the draft view is a real editable textarea, and approve/export sends
Snow's edited text verbatim, so she can delete one flagged line and ship in
seconds instead of regenerating. Verified: forced escalation to hand-fix to
exported draft bundle carrying her exact text. 108 tests green, goldens
clean.

## Schema-constrained judge + self-diagnosing failure (2026-07-08)

Root-cause fix for the recurring "judge returned no usable checklist": stop
parsing around the model and constrain it at decode time. The judge call
now passes a JSON Schema as Ollama's `format` (structured outputs; Gemini
gets response_schema too), so the model is grammar-forced to emit the exact
array-of-{criterion,passed,note}. The tolerant parser and one re-ask stay
as backstops. Two diagnostics so this can never again be undiagnosable from
a distance: the fallback fail note now embeds the raw model reply
(truncated), and `pipeline doctor --judge` runs a real judge call and
prints exactly what the model emitted plus how many items parsed. LLMClient
records last_raw_reply on every call. 107 tests green, goldens clean.

## Judge shape tolerance (2026-07-08)

"Judge returned no usable checklist twice" turned out to be parser
strictness, not model failure: llama3.1:8b in JSON mode reliably emits an
object keyed by criterion (or a single flat item, boolean maps, alias keys
like pass/name/reason) rather than the requested top-level array. The
parser now coerces every shape that carries the verdict information, and
the judge prompt shows an explicit array example. True garbage still fails
with the doctor hint after one re-ask. 104 tests green, goldens clean.

## Direction-aware length retries + lingo removal orders (2026-07-08)

Snow's stack is confirmed current (fail reasons name real words now), and
the live escalation exposed a genuine retry bug: a 256-word LinkedIn post
(cap 200) got told to "write the full length... expand every section",
because the length addendum only knew the expand direction. The retry now
parses the measured count from the fail reason and orders a CUT (with
target and "remove the weakest paragraph") when over the cap, expansion
only when under the floor. Lingo failures additionally get an explicit
"delete or rewrite these exact words, no substitute buzzwords" order.
Simulated 256-word over-writer passes on revision 1. 98 tests green,
goldens clean.

## pipeline doctor, boot banner, judge re-ask (2026-07-07)

Snow's Ollama log showed requests hitting /v1/chat/completions with
n_ctx_slot 4096 and a 13k-token judge prompt truncated to 2050: the
hand-copied llm.py from before the pulls was back in her working tree
(stash pop over the pulled version), shadowing every fix. The code was
fine; the tree was lying. Three additions so this diagnoses itself:
`pipeline doctor` checks git drift in pipeline/ and web/, whether THIS
process sees PIPELINE_MODEL, whether Ollama is reachable and has the model
pulled, and does one live round trip; `pipeline serve` now prints a boot
banner naming the model, endpoint and num_ctx it will actually use; and a
malformed judge reply gets one bounded re-ask before failing (transport
problems shouldn't burn writer retries; the fallback note points at
doctor). 94 tests green.

## Gist line as a writer-owned step; readable lingo failures (2026-07-07)

The 383-word escalation showed the num_ctx fix working (up from 226) and
the model losing a three-front battle: expand, de-lingo, and remember the
gist line at once. Two changes. The AEO gist line is paratext, so the
writer now produces it as its own focused step after the body (skipped when
the draft already opens with one; deterministic title fallback if the call
fails), which removes one front entirely. And verb-lingo failures now name
the matched word ("'leverage' used as a verb") instead of leaking the raw
regex into the feedback and the UI. Retry cap unchanged. 90 tests green,
goldens clean.

## Ollama context window + retries that edit (2026-07-07)

Root cause of the persistent short essays found by arithmetic, not
prompting: the writer prompt is ~4k tokens and Ollama's default num_ctx for
the model is 4096, so the window was full before generation started; Ollama
silently truncates and the draft caps out around 220-270 words no matter
what the instructions say. Every Ollama call now sets num_ctx explicitly
(default 8192, PIPELINE_OLLAMA_NUM_CTX to override). Second fix while in
there: reviewer retries now include the failed draft in the prompt, so the
model expands or repairs a concrete text instead of cold-writing the piece
again, which also stops rewrites from introducing brand-new violations.
Retry cap unchanged. 85 tests green, goldens clean.

## Per-format writer briefs (2026-07-07)

The social_copy overshoot (7 sentences against a 1-3 cap) was
self-inflicted: the writer system prompt demanded essay furniture
(signature phrase, throwaway line, unresolved observation, open last line)
for every format, and no 1-3 sentence piece can satisfy that checklist, so
the model sacrificed the length cap. The essay checklist now lives in
per-format FORMAT_BRIEFS; social copy explicitly waives the essay rules and
states that a fourth sentence is a failure. Sentence-cap failures turn into
an explicit "at most N sentences, nothing before or after" order on retry,
the judge is told to scale structural criteria to the format so it doesn't
fail short pieces for missing essay elements, and edit-stage revisions
carry the brief too. Retry cap still 2. Simulated 7-sentence over-writer
now passes on revision 1. 85 tests green, goldens clean.

## Writer length guidance (2026-07-07)

llama3.1:8b was under-writing substack essays (~268 words against the 400
floor) and the retry loop was replaying the raw fail string, which a small
model doesn't translate into "add 150 words," so runs escalated on length
alone. The writer prompt now states the numeric bound loudly and aims well
above the floor (about 565 words for the 400-900 band, since models
undershoot their targets), and a length_bounds failure turns into an
explicit expand order with the floor and target restated. Edit-stage
revisions carry the same requirement so post-review edits can't shrink a
draft below the bound. The retry cap stays at 2; a simulated under-writer
now passes on revision 1. 81 tests green, goldens clean.

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
