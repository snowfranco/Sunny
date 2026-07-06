# CLAUDE.md — working on Snow's content pipeline

This repo is a single-user, local-first content pipeline that turns Snow
Abad's build/work notes into draft Substack/LinkedIn bundles. Read this
before changing anything.

## Commands

```bash
python3 -m pipeline init                 # create data/pipeline.db
python3 -m pipeline capture "text"       # capture a note
python3 -m pipeline watch-inbox          # poll inbox.md for new notes
python3 -m pipeline research             # project-doc scan + landscape scan
python3 -m pipeline angles <note_id>     # generate 3 angle options
python3 -m pipeline serve                # local UI (on-demand, not always-on)
python3 -m pipeline run <angle_id>       # writer -> reviewer -> edit -> repurpose -> export
python3 -m unittest discover -s tests -v # test suite (stdlib unittest, no pytest here)
tools/run_goldens.py                     # golden fixtures, run when voice/pillars/model change
tools/passrate.py                        # reviewer pass-rate from PipelineRunLog
```

No external dependencies are required to develop or test: `anthropic` is
lazy-imported and everything runs in deterministic mock mode when
`PIPELINE_MODEL` is unset or `PIPELINE_MOCK=1`.

## Architecture

- `pipeline/schemas.py` — every inter-step handoff type, validated on
  construction. **All new handoffs must be schemas here, never freeform text
  parsed by regex.**
- `pipeline/db.py` — SQLite (single file, `data/pipeline.db`), one table per
  schema, thin save/load helpers.
- `pipeline/llm.py` — the only place LLM calls happen. Model comes from
  `PIPELINE_MODEL`; mock mode returns canned schema-valid JSON keyed by call
  `kind`. Token ceiling enforced per run here.
- `pipeline/runlog.py` — PipelineRunLog; every step of every run is recorded.
- `pipeline/refinement.py` — the conversational loop used by BOTH the
  angle-pick stage and the edit stage. 5-turn cap lives here.
- `pipeline/reviewer.py` — LLM-as-judge with a literal 9-point checklist;
  mechanical checks run in code first, subjective ones go to the judge.
- `pipeline/orchestrator.py` — bounded writer->reviewer retry (max 2), then
  escalation with the fail reason.
- `pipeline/export.py` — draft bundles only; asserts `status == "draft"`.
- `context/*.md` — the editorial ground truth. `brand-voice-source.md` is
  Snow's original guide, verbatim; `brand-voice.md` is the operational
  derivation the writer/reviewer consume.

## Hard constraints — do not violate, do not "improve"

1. **Never add a publish code path.** No Substack API, no LinkedIn API, no
   webhook that posts content anywhere. Export produces local draft bundles,
   full stop. `ExportBundle` validates `status == "draft"`.
2. Reviewer retries are capped at 2 (`MAX_REVIEWER_RETRIES`), then escalate
   to Snow with the specific failure reason attached. Do not raise the cap.
3. Refinement conversations cap at 5 turns (`MAX_REFINEMENT_TURNS`), then the
   system prompts Snow to lock in or start over. Do not remove the cap.
4. Landscape-scan suggestions without a citable `source_url` are rejected at
   the schema layer.
5. Project-doc scanning is **read-only**. Never write to paths listed in
   `config.json: project_paths`.
6. Do not hard-code a model id anywhere. `PIPELINE_MODEL` stays an env var;
   the model decision is deliberately open.
7. Brand-voice hard rules (no em dashes, no "this is not X, it's Y", no
   signpost sentences, banned lingo list) are enforced mechanically in
   `pipeline/reviewer.py`. Keep the mechanical checks in sync with
   `context/brand-voice.md` if that file changes, and re-run the golden set.

## Conventions

- Python 3.11+, stdlib-first. New third-party deps need a hard justification.
- Schemas are dataclasses that raise `SchemaError` on invalid construction.
- Timestamps are ISO-8601 UTC strings via `schemas.now_iso()`.
- IDs are uuid4 strings via `schemas.new_id()`.
- Tests use `unittest`; keep them runnable offline with no API key.
- When `context/brand-voice.md`, `context/pillars.md`, or the model version
  changes: re-run `tools/run_goldens.py` and eyeball the diff against
  last-known-good (tier 2 guardrail).
