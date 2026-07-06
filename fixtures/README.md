# Golden fixtures (tier 2 guardrail)

Real note-to-post examples: 3 per pillar, every format covered at least
once. Each file has three sections delimited by `--- meta ---`,
`--- note ---`, `--- golden ---`.

Re-run `tools/run_goldens.py` manually whenever any of these change:

- `context/brand-voice.md`
- `context/pillars.md`
- the model version (`PIPELINE_MODEL`)

The runner does two things:

1. Checks every golden post against the current mechanical reviewer rules.
   A failure here means the voice rules and the goldens have drifted apart;
   a human decides which one is right.
2. Regenerates a draft from each fixture's note through the full
   writer + reviewer loop and writes the results to `data/goldens/run-*/`.
   Diff that directory against the last-known-good run **by eye**; there is
   no automated similarity score, deliberately.
