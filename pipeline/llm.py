"""The only place LLM calls happen.

- Model comes from PIPELINE_MODEL (env). Deliberately unset by default; the
  model decision is open and gets made after real usage exists. Do not
  hard-code a model id anywhere.
- Mock mode (PIPELINE_MODEL unset, or PIPELINE_MOCK=1) returns deterministic,
  schema-valid outputs keyed by call `kind`, so the whole pipeline, the test
  suite, and the golden fixtures run offline with no API key.
- Tier 1 guardrail: a per-run token ceiling. Every call is attributed to a
  run_id; exceeding the ceiling raises TokenCeilingExceeded.

There is deliberately NO publish capability here or anywhere else: this
module talks to the Anthropic Messages API only, and only when a real model
is configured.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import config

# Call kinds. The mock dispatches on these; real calls just use the prompts.
KINDS = (
    "angles",          # note -> 3 AngleOption dicts
    "refine_angle",    # conversation -> revised AngleOption dict
    "landscape",       # context -> suggestion dicts with source URLs
    "draft",           # angle + context -> draft text
    "revise_draft",    # draft + instruction -> revised draft text
    "review",          # draft -> subjective checklist verdicts
    "caption",         # post -> image caption
    "repurpose",       # post -> linkedin extract + notes hook
    "growth",          # analytics -> trend notes + recommendations
)


class TokenCeilingExceeded(RuntimeError):
    """The per-run token budget was exhausted (tier 1 guardrail)."""


class LLMError(RuntimeError):
    pass


class _RunBudget:
    def __init__(self, ceiling: int):
        self.ceiling = ceiling
        self.used = 0

    def charge(self, tokens: int) -> None:
        self.used += tokens
        if self.used > self.ceiling:
            raise TokenCeilingExceeded(
                f"run exceeded token ceiling: {self.used} > {self.ceiling}. "
                "Raise PIPELINE_MAX_TOKENS_PER_RUN only if you mean it."
            )


class LLMClient:
    """complete_json(kind, ...) -> parsed JSON; complete_text(kind, ...) -> str."""

    def __init__(self, run_id: str = "adhoc"):
        self.run_id = run_id
        self.budget = _RunBudget(config.max_tokens_per_run())
        self.mock = config.mock_mode()
        self._client = None

    # -- public -------------------------------------------------------------

    def complete_text(self, kind: str, system: str, user: str,
                      max_tokens: int = 2048) -> str:
        assert kind in KINDS, f"unknown call kind {kind!r}"
        if self.mock:
            self.budget.charge(_approx_tokens(system + user))
            return _mock_text(kind, user)
        return self._real_call(system, user, max_tokens)

    def complete_json(self, kind: str, system: str, user: str,
                      max_tokens: int = 2048):
        assert kind in KINDS, f"unknown call kind {kind!r}"
        if self.mock:
            self.budget.charge(_approx_tokens(system + user))
            return _mock_json(kind, user)
        raw = self._real_call(
            system + "\n\nRespond with valid JSON only. No prose, no fences.",
            user, max_tokens)
        return _parse_json_reply(raw)

    # -- real API -----------------------------------------------------------

    def _real_call(self, system: str, user: str, max_tokens: int) -> str:
        if self._client is None:
            try:
                import anthropic  # lazy: not needed for mock mode / tests
            except ImportError as e:
                raise LLMError(
                    "anthropic package not installed; pip install anthropic, "
                    "or unset PIPELINE_MODEL to run in mock mode") from e
            self._client = anthropic.Anthropic()
        model = config.pipeline_model()
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self.budget.charge(int(usage.input_tokens) + int(usage.output_tokens))
        else:
            self.budget.charge(_approx_tokens(system + user) + max_tokens)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _parse_json_reply(raw: str):
    """Parse a JSON reply, tolerating a fenced block. This is parsing the
    LLM's own reply envelope, not an inter-step handoff; handoffs are always
    validated schemas built from this parsed data."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"model reply was not valid JSON: {e}\n---\n{raw[:500]}") from e


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# --- deterministic mock ------------------------------------------------------
# Canned outputs are seeded from the input so repeated runs are stable but
# different inputs differ. Everything returned here must pass the schemas.

def _seed(user: str) -> str:
    return hashlib.sha256(user.encode()).hexdigest()[:8]


def _mock_json(kind: str, user: str):
    s = _seed(user)
    if kind == "angles":
        return [
            {
                "pillar": "build_in_public",
                "format": "substack_essay",
                "title": f"The call I got wrong first ({s})",
                "hook": "I shipped the wrong version of this twice before the shape was obvious.",
                "strategic_rationale": "immediate_credibility",
                "rationale": "Real decision narrative from active work.",
            },
            {
                "pillar": "ai_for_shippers",
                "format": "linkedin_post",
                "title": f"A workflow change that stuck ({s})",
                "hook": "One small change to how I hand work to the model, and the redo rate dropped.",
                "strategic_rationale": "reactive_trend",
                "rationale": "Practical takeaway operators can use this week.",
            },
            {
                "pillar": "transition_story",
                "format": "social_copy",
                "title": f"Fifteen years in, still taking notes ({s})",
                "hook": "The habit that survived four countries is the one doing the work now.",
                "strategic_rationale": "long_term_bet",
                "rationale": "Career-arc thread differentiates the lane.",
            },
        ]
    if kind == "refine_angle":
        return {
            "pillar": "ai_for_shippers",
            "format": "substack_essay",
            "title": f"Revised angle ({s})",
            "hook": "Refined per your note, keeping the operator lens.",
            "strategic_rationale": "reactive_trend",
            "rationale": "Combined per refinement conversation.",
        }
    if kind == "landscape":
        return [
            {
                "raw_text": f"[mock landscape {s}] A framework release worth a "
                            "'how you'd actually use this' piece for small teams.",
                "source_url": "https://example.com/mock-release-notes",
            },
            {
                "raw_text": f"[mock landscape {s}] A slow shift in how teams "
                            "structure agent handoffs; long-term bet material.",
                "source_url": "https://example.com/mock-trend-report",
            },
        ]
    if kind == "review":
        # Subjective criteria only; mechanical ones are checked in code.
        return [
            {"criterion": "voice_match", "passed": True, "note": "mock: reads in voice"},
            {"criterion": "insight_arrives_not_announced", "passed": True, "note": "mock"},
            {"criterion": "one_unresolved_observation", "passed": True, "note": "mock"},
            {"criterion": "last_line_opens_a_door", "passed": True, "note": "mock"},
            {"criterion": "one_throwaway_line", "passed": True, "note": "mock"},
            {"criterion": "claim_traceability", "passed": True, "note": "mock"},
            {"criterion": "pillar_format_consistency", "passed": True, "note": "mock"},
        ]
    if kind == "repurpose":
        return {
            "linkedin_extract": (
                "I have been sitting with something after this build.\n\n"
                "The part I expected to be hard was fast, and the part I "
                "expected to be free took the week. That gap is where the "
                "actual work lives, and I keep underestimating it.\n\n"
                "I'm not sure if you'd agree, but the estimate being wrong "
                "in that specific direction feels like information."
            ),
            "notes_hook": "The hard part was free and the free part was hard. Sitting with that one.",
        }
    if kind == "growth":
        return {
            "trend_notes": f"[mock {s}] Build-in-public posts with a named wrong "
                           "turn outperform the median; posts without a specific "
                           "artifact lag.",
            "recommendations": [
                "Lead with the decision, not the feature.",
                "Keep one unresolved question per post; comments cluster there.",
            ],
        }
    raise LLMError(f"no mock JSON for kind {kind!r}")


def _mock_text(kind: str, user: str) -> str:
    s = _seed(user)
    if kind == "draft":
        return _mock_draft(user, s)
    if kind == "revise_draft":
        return _mock_draft(user, s, revised=True)
    if kind == "caption":
        return f"Working notes from the build, {s} edition. The diagram is the tidy version; the week was not."
    raise LLMError(f"no mock text for kind {kind!r}")


def _mock_draft(user: str, s: str, revised: bool = False) -> str:
    """A mock draft engineered to pass the mechanical reviewer checks for the
    substack_essay format (gist line, length bounds, no banned patterns)."""
    tag = "revised " if revised else ""
    gist = (f"> Covered here: the sunny pipeline build ({tag}{s}), SQLite "
            "handoffs, a bounded reviewer loop, and what the retry cap caught.")
    body_paras = [
        "So the reviewer loop failed the same draft twice on Tuesday, and "
        "honestly, the second failure was the useful one. The first was an em "
        "dash I already knew about. The second was a conclusion that resolved "
        "too cleanly, which I would have shipped without noticing.",
        "## What I actually built it with",
        "The pipeline is Python and SQLite, one file, no cloud anything. "
        "Every handoff between steps is a validated schema, and the writer "
        "never talks to the exporter directly. The orchestrator sits between "
        "them and logs every step, which sounded like ceremony until I needed "
        "to know why a draft had three revisions.",
        "That didn't work out as expected the first time, but here's what I "
        "learned: the bound on the retry loop matters more than the retry "
        "loop. Two tries, then it stops and tells me why. An unbounded loop "
        "would have burned the budget polishing a draft that needed a human "
        "decision, and I would not have found out until the invoice.",
        "## The loop I didn't plan for",
        "The judge caught my own writing tics faster than it caught the "
        "model's. I built the checklist to police generated text, and the "
        "first thing it flagged was a sentence I typed myself. I wrote the "
        "first version of this at the kitchen table because the desk chair "
        "was holding laundry, which is its own kind of process note.",
        "I'm not sure if you'd agree, but a reviewer that fails fast and "
        "names the reason feels more like a colleague than a gate. The old "
        "review pass was me rereading the draft the next morning; here's how "
        "that's evolving, the morning reread still happens, it just starts "
        "from a draft that already survived the checklist.",
        "What I don't know yet is whether the checklist stays honest as the "
        "voice drifts. I keep thinking about it.",
        "If you've bounded a judge loop differently, I want to hear how, and "
        "I'm genuinely asking.",
    ]
    words_needed = 400
    text = gist + "\n\n" + "\n\n".join(body_paras)
    # pad naturally if under the floor
    filler = ("The run log has a row for every step now, and reading it back "
              "is the closest thing this project has to a diary. ")
    while len(re.findall(r"[\w'-]+", text)) < words_needed:
        text += "\n\n" + filler
    return text
