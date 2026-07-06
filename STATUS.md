# Build status notes

One note per phase, newest at the top. Written during the initial build
session; future sessions should keep appending here.

## Phase 0 — Scaffold (2026-07-06)

Repo structure, config layer (env-driven model, deliberately unset), all 13
handoff schemas as validated dataclasses, SQLite DDL with a CHECK constraint
that makes non-draft export bundles unstorable even via raw SQL, and the
PipelineRunLog. Context docs authored: brand-voice.md (operational),
brand-voice-source.md (verbatim), pillars, strategy, platforms. One addition
beyond the brief's schema list: CaptureNote grew an optional `source_url`,
mandatory when source is landscape_scan, which is how the citable-source
guardrail is enforced at the schema layer. 19 tests green, stdlib only.
