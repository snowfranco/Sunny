# sunny — Snow's AI content pipeline

Turns real build/work notes into publish-ready Substack and LinkedIn draft
bundles, in Snow Abad's voice, with a human in the loop at every decision
point. Single-user, local-first, SQLite-backed. **It never publishes
anything, anywhere** — export always produces an unpublished draft bundle.

## The pipeline

```mermaid
flowchart TD
    A["You: drop a topic"] --> E
    B["Researcher: scans your project docs"] --> E
    C["Researcher: scans the external landscape\nreactive trends + long-term bets"] --> E
    E["Angle engine"] --> F{"Human: refine angle\n(conversational loop)"}
    F -->|revise request| E
    F -->|proceed| G["Orchestrator"]
    G --> H["Writer"]
    G --> I["Artist — scaffold only"]
    H --> J["Editorial reviewer\n(LLM-as-judge)"]
    I --> J
    J -->|fail, up to 2 tries| H
    J -->|pass| K{"Human: edit\n(conversational loop)"}
    K -->|revise request| H
    K -->|approve| L["Repurpose"]
    L --> M["Export — draft bundle only"]
    M -.time gap, you publish externally.-> N["Analytics"]
    N --> O["Growth researcher"]
    O --> P{"Human: review + update context\nevery 2-4 weeks"}
    P -.updates.-> B
    P -.updates.-> C
```

## Quickstart

```bash
# One-time setup
cp config.example.json config.json   # then edit project_paths
python3 -m pipeline init             # creates data/pipeline.db

# Capture a topic from anywhere
python3 -m pipeline capture "shipped the reviewer loop today, judge caught my em dashes"

# Or drop lines into inbox.md and let the watcher pick them up
python3 -m pipeline watch-inbox

# Research: scan project docs + external landscape, write suggestions
python3 -m pipeline research

# Generate angles for a note, then refine conversationally
python3 -m pipeline angles <note_id>
python3 -m pipeline serve            # local page for refinement conversations

# Run a picked angle through writer -> reviewer -> edit -> repurpose -> export
python3 -m pipeline run <angle_id>

# Analytics (manual paste-in) + growth report
python3 -m pipeline analytics add <post_id> --platform substack --views 1200 --likes 40 --comments 6 --shares 3 --days 7
python3 -m pipeline growth-report

# Tests
python3 -m unittest discover -s tests -v
```

## Model configuration

The runtime LLM is set via the `PIPELINE_MODEL` env var and is deliberately
left unset — the choice of model is an open decision, made after real usage
data exists. With `PIPELINE_MODEL` unset (or `PIPELINE_MOCK=1`), the pipeline
runs in deterministic mock mode: every step executes end-to-end with canned,
schema-valid outputs, which is also how the test suite and golden fixtures run
without an API key.

```bash
export ANTHROPIC_API_KEY=...      # required for real runs
export PIPELINE_MODEL=...         # decide later; any Anthropic model id
```

## Layout

| Path | What it is |
|---|---|
| `context/` | Brand voice, pillars, strategy, platform rules. The writer and reviewer read these. |
| `pipeline/` | The Python package: capture, researcher, angle engine, orchestrator, writer, reviewer, artist, repurpose, export, analytics, growth. |
| `web/` | Single-page local interface (no framework) for refinement conversations and researcher suggestions. |
| `fixtures/` | Golden note-to-post examples, re-run when voice/pillars/model change. |
| `tools/` | Pass-rate and golden-set scripts. |
| `data/` | SQLite db + generated files (gitignored). |
| `exports/` | Draft bundles (gitignored). |

## Hard constraints (enforced in code)

- **No auto-publish, ever.** There is no code path that calls a publish API.
  `ExportBundle.status` is hard-coded `"draft"` and validated.
- Reviewer failures loop back a **maximum of 2 times**, then escalate to Snow
  with the specific failure reason.
- Refinement conversations cap at **5 turns**, then force a decision prompt.
- Every inter-step handoff is a **validated schema** (`pipeline/schemas.py`).
- Landscape-scan claims **require a citable source** or they are rejected.
- Per-run **token ceiling** (`PIPELINE_MAX_TOKENS_PER_RUN`).
