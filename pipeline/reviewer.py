"""Editorial reviewer: LLM-as-judge with a literal 9-point checklist.

Split by nature, not by vibe:
- Mechanical criteria (banned patterns, length bounds, AEO gist line,
  quote length, publish claims) are checked in code. Deterministic, free,
  and they catch most failures before a judge token is spent.
- Subjective criteria (voice match, insight arrives, unresolved observation,
  door-opening last line, throwaway line, claim traceability, pillar/format
  consistency) go to the LLM judge.

A failing verdict always carries the specific fail_reason; the orchestrator
enforces the max-2-retries bound and escalates with that reason attached.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from . import llm
from . import schemas as S
from .config import REPO_ROOT

# --- banned patterns (context/brand-voice.md, hard rules) -------------------

EM_DASH = "—"

# Fallback defaults only. The live lists are parsed from the CHECKER-LEXICON
# block in context/brand-voice.md by _lexicon(); these apply solely when that
# file or block is unreachable, so the checker degrades safely rather than
# silently letting everything through.
_DEFAULT_BANNED_LINGO = (
    "game-changer",
    "game changer",
    "supercharge",
    "paradigm shift",
    "democratize",
    "democratise",
    "transformative",
    "the future of",
)
# 'unlock' and 'leverage' are banned as verbs only. Without a POS tagger the
# heuristic is: inflected forms are (nearly) always verbs; the bare form and
# 'unlocked' count as verbs when a determiner-ish object follows.
_DET = r"(?:the|a|an|this|that|these|those|our|your|my|their|its|it|them|new|real)"
BANNED_VERB_PATTERNS = (
    r"\bunlock(?:s|ing)?\b",
    rf"\bunlocked\s+{_DET}\b",
    r"\bleverag(?:es|ed|ing)\b",
    rf"\bleverage\s+{_DET}\b",
)

_DEFAULT_SIGNPOST_SENTENCES = (
    "here's where it gets interesting",
    "here is where it gets interesting",
    "here's where it got interesting",
    "this is the part worth pausing on",
    "and here's the real kicker",
    "here's the real kicker",
    "here's the thing",
    "let that sink in",
)


def _parse_lexicon_section(text: str, name: str) -> list[str]:
    """Pull one [section] out of the CHECKER-LEXICON block in brand-voice.md.
    Returns lowercased entries, one per line, or [] if the section is absent."""
    m = re.search(rf"\[{re.escape(name)}\]\s*\n(.*?)(?=\n\[|\n?-->|\Z)",
                  text, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        s = line.strip()
        if s and not s.startswith(("[", "#", "<!--", "-->")):
            out.append(s.lower())
    return out


@functools.lru_cache(maxsize=8)
def _lexicon_for(voice_path: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        text = Path(voice_path).read_text(encoding="utf-8")
    except OSError:
        return _DEFAULT_BANNED_LINGO, _DEFAULT_SIGNPOST_SENTENCES
    lingo = _parse_lexicon_section(text, "banned_lingo")
    signposts = _parse_lexicon_section(text, "signpost_sentences")
    return (tuple(lingo) or _DEFAULT_BANNED_LINGO,
            tuple(signposts) or _DEFAULT_SIGNPOST_SENTENCES)


def _lexicon() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Live banned-lingo and signpost lists, read from context/brand-voice.md.
    Cached per path; call _lexicon.cache_clear via _reload_lexicon() after
    editing the file in a long-running process."""
    return _lexicon_for(str(REPO_ROOT / "context" / "brand-voice.md"))


def _reload_lexicon() -> None:
    """Drop the cache so a running server picks up brand-voice.md edits."""
    _lexicon_for.cache_clear()

NOT_X_BUT_Y = (
    r"\bthis is not (?:just |only |merely )?(?:about )?\w[^.?!]*,\s*(?:it'?s|but)\b",
    r"\bthis isn'?t (?:just |only |merely )?(?:about )?\w[^.?!]*[;,]\s*it'?s\b",
    r"\bnot only\b[^.?!]*\bbut (?:also )?\b",
    r"\bisn'?t (?:just|only|merely)\b[^.?!]*[;,]\s*it'?s\b",
)

PUBLISH_CLAIMS = (
    "has been published",
    "publishing this now",
    "auto-published",
    "scheduled for publication",
    "posted to substack",
    "posted to linkedin",
)


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'-]+", text)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _body_without_gist(text: str, fmt: str) -> str:
    """For substack essays the first line is AEO paratext, not the piece."""
    if fmt != "substack_essay":
        return text
    lines = text.lstrip().splitlines()
    if lines and (lines[0].startswith(">") or
                  (lines[0].startswith(("*", "_")) and lines[0].rstrip().endswith(("*", "_")))):
        return "\n".join(lines[1:]).strip()
    return text


# --- mechanical checks -------------------------------------------------------

def check_banned_patterns(text: str, fmt: str = "") -> list[S.ChecklistItem]:
    items = []
    lower = text.lower()

    found = EM_DASH in text
    items.append(S.ChecklistItem(
        "no_em_dashes", not found,
        "em dash found" if found else "clean"))

    banned_lingo, signpost_sentences = _lexicon()
    hits = [w for w in banned_lingo if w in lower]
    # Report the matched word, not the regex: the fail reason goes back to
    # the writer model (and to Snow), and '\\bleverag(?:es|ed|ing)\\b' tells
    # neither of them what to remove.
    for p in BANNED_VERB_PATTERNS:
        m = re.search(p, lower)
        if m:
            hits.append(f"'{m.group(0).strip()}' used as a verb")
    items.append(S.ChecklistItem(
        "no_performed_lingo", not hits,
        f"banned lingo: {hits}" if hits else "clean"))

    sp = [s for s in signpost_sentences if s in lower]
    items.append(S.ChecklistItem(
        "no_signpost_sentences", not sp,
        f"signposts: {sp}" if sp else "clean"))

    nx = [p for p in NOT_X_BUT_Y if re.search(p, lower)]
    items.append(S.ChecklistItem(
        "no_not_x_but_y", not nx,
        "'this is not X, it's Y' construction found" if nx else "clean"))

    # Scripts are written to be spoken: short sentences and natural pauses
    # are the format working as intended (platforms.md), so the stacked-
    # fragment threshold is higher there. The ban targets influencer rhythm,
    # not speech rhythm.
    threshold = 6 if fmt == "script" else 4
    frag = _fragment_rhythm_score(text, threshold)
    items.append(S.ChecklistItem(
        "no_fragmented_rhythm", not frag,
        f"fragment-heavy rhythm ({threshold}+ consecutive sentences under 8 words)"
        if frag else "clean"))
    return items


def _fragment_rhythm_score(text: str, threshold: int = 4) -> bool:
    """Flag `threshold`+ consecutive sentences of under 8 words: the stacked
    punchy rhythm the voice guide bans. Asides happen; stacks don't."""
    run = 0
    for s in _sentences(text):
        if len(_words(s)) < 8:
            run += 1
            if run >= threshold:
                return True
        else:
            run = 0
    return False


def check_length_bounds(text: str, fmt: str) -> S.ChecklistItem:
    bounds = S.LENGTH_BOUNDS.get(fmt)
    body = _body_without_gist(text, fmt)
    if bounds is None:
        return S.ChecklistItem("length_bounds", True, f"no bound for {fmt}")
    unit, lo, hi = bounds
    n = len(_words(body)) if unit == "words" else len(_sentences(body))
    ok = lo <= n <= hi
    return S.ChecklistItem(
        "length_bounds", ok,
        f"{n} {unit} (bound {lo}-{hi} for {fmt})")


def check_aeo_gist(text: str, fmt: str) -> S.ChecklistItem:
    """Substack only: a single distinctly-formatted line above the opening
    (blockquote or italic aside), naming entities. Paratext, not preamble."""
    if fmt != "substack_essay":
        return S.ChecklistItem("aeo_gist_line", True, f"not required for {fmt}")
    lines = text.lstrip().splitlines()
    first = lines[0].strip() if lines else ""
    is_quote = first.startswith("> ") and len(first) > 4
    is_italic = ((first.startswith("*") and first.endswith("*") and not first.startswith("**"))
                 or (first.startswith("_") and first.endswith("_")))
    ok = is_quote or is_italic
    return S.ChecklistItem(
        "aeo_gist_line", ok,
        "present as paratext" if ok else
        "missing: substack pieces need a blockquote/italic gist line above the opening")


def check_copyright_hygiene(text: str) -> S.ChecklistItem:
    """No quotes over ~15 words from any source (and no lyric/poem blocks,
    which this length rule also catches)."""
    long_quotes = []
    for m in re.finditer(r'"([^"]{40,})"', text):
        if len(_words(m.group(1))) > 15:
            long_quotes.append(m.group(1)[:50] + "...")
    ok = not long_quotes
    return S.ChecklistItem(
        "copyright_hygiene", ok,
        f"quote(s) over 15 words: {long_quotes}" if long_quotes else "clean")


def check_no_publish_claim(text: str) -> S.ChecklistItem:
    lower = text.lower()
    hits = [p for p in PUBLISH_CLAIMS if p in lower]
    return S.ChecklistItem(
        "no_publish_action_or_claim", not hits,
        f"publish claim in output: {hits}" if hits else
        "clean (and there is no publish code path, by construction)")


def mechanical_checklist(text: str, fmt: str) -> list[S.ChecklistItem]:
    body = _body_without_gist(text, fmt)
    items = check_banned_patterns(body, fmt)
    items.append(check_length_bounds(text, fmt))
    items.append(check_aeo_gist(text, fmt))
    items.append(check_copyright_hygiene(text))
    items.append(check_no_publish_claim(text))
    return items


# --- the judge ---------------------------------------------------------------

JUDGE_SYSTEM = """You are the editorial reviewer in Snow Abad's content
pipeline, judging one draft against her brand voice guide. Judge each
criterion independently and honestly; a wrong pass is worse than a wrong
fail. Reply with a JSON array of objects:
{"criterion": "<name>", "passed": true|false, "note": "<specific, one line>"}
covering exactly these criteria:
- voice_match: conversational not fragmented, casually confident, direct,
  short sentences, no filler openers; reads like Snow's guide.
- insight_arrives_not_announced: evidence first, pattern named after; the
  thesis is not delivered upfront.
- one_unresolved_observation: at least one observation is honestly left open.
- last_line_opens_a_door: the final line opens rather than restating the
  thesis cleanly.
- one_throwaway_line: one small, specific, slightly unnecessary human detail.
- claim_traceability: every specific number, project name, or fact traces to
  the provided note/context; nothing invented.
- pillar_format_consistency: content matches the tagged pillar and the
  target platform's rules.
Scale the structural criteria to the format. For social_copy (1-3
sentences) and other very short formats, a single wry, specific observation
satisfies insight/throwaway/unresolved/door at once; do not fail a short
piece for lacking essay furniture the format has no room for.
Your reply MUST be a JSON array at the top level, not an object. Shape
example (values illustrative):
[{"criterion": "voice_match", "passed": true, "note": "direct, in voice"},
 {"criterion": "claim_traceability", "passed": false, "note": "invented a number"}]"""


# Small local models in JSON mode rarely emit the exact requested shape (a
# top-level array of {criterion, passed, note}). They produce objects keyed
# by criterion, single flat items, boolean maps, and alias keys. All of
# those carry the same information; parse them instead of failing them.
_CRIT_KEYS = ("criterion", "criteria", "name", "check", "rule")
_PASS_KEYS = ("passed", "pass", "ok", "result", "verdict", "value")
_NOTE_KEYS = ("note", "notes", "reason", "comment", "explanation")


# "voice_match: pass, reads well" / "claim_traceability - fail" etc.
_STRING_ITEM_RE = re.compile(
    r"^\s*(?P<crit>[\w][\w /_-]*?)\s*[:\-]\s*"
    r"(?P<verdict>pass(?:ed)?|fail(?:ed)?|true|false|yes|no)\b[\s.:,-]*(?P<note>.*)$",
    re.IGNORECASE)
_VERDICT_WORDS = ("pass", "passed", "true", "yes", "fail", "failed", "false", "no")
_PASS_WORDS = ("pass", "passed", "true", "yes")


def _coerce_item(crit_hint, obj) -> S.ChecklistItem | None:
    if isinstance(obj, bool):
        return S.ChecklistItem(str(crit_hint or "unknown"), obj, "")
    if isinstance(obj, str):
        m = _STRING_ITEM_RE.match(obj)
        if m:
            return S.ChecklistItem(
                m.group("crit").strip(),
                m.group("verdict").lower() in _PASS_WORDS,
                m.group("note").strip())
        if crit_hint and obj.strip().lower() in _VERDICT_WORDS:
            return S.ChecklistItem(str(crit_hint),
                                   obj.strip().lower() in _PASS_WORDS, "")
        return None
    if not isinstance(obj, dict):
        return None
    crit = crit_hint
    for k in _CRIT_KEYS:
        if isinstance(obj.get(k), str):
            crit = obj[k]
            break
    passed = None
    for k in _PASS_KEYS:
        v = obj.get(k)
        if isinstance(v, bool):
            passed = v
            break
        if isinstance(v, str) and v.strip().lower() in ("true", "false",
                                                        "pass", "fail",
                                                        "yes", "no"):
            passed = v.strip().lower() in ("true", "pass", "yes")
            break
    if crit is None or passed is None:
        return None
    note = ""
    for k in _NOTE_KEYS:
        if isinstance(obj.get(k), str):
            note = obj[k]
            break
    return S.ChecklistItem(str(crit), passed, note)


def _judge_items(raw) -> list[S.ChecklistItem]:
    items: list[S.ChecklistItem] = []
    if isinstance(raw, dict):
        single = _coerce_item(None, raw)
        if single:
            return [single]
        for k, v in raw.items():
            if isinstance(v, list):
                continue  # {"checklist": [...]} handled by unwrap below
            it = _coerce_item(k, v)
            if it:
                items.append(it)
        if items:
            return items
    for it in llm.unwrap_list(raw):
        coerced = _coerce_item(None, it)
        if coerced:
            items.append(coerced)
    return items


# Hard grammar constraint for backends that support structured outputs
# (Ollama, Gemini). This is the real fix for small models emitting the wrong
# JSON shape: the model is constrained to this array-of-objects at decode
# time, not asked nicely for it.
JUDGE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "criterion": {"type": "string"},
            "passed": {"type": "boolean"},
            "note": {"type": "string"},
        },
        "required": ["criterion", "passed", "note"],
    },
}


def judge_subjective(draft_text: str, pillar: str, fmt: str,
                     source_note: str, client: llm.LLMClient,
                     context_dir: Path | None = None) -> list[S.ChecklistItem]:
    voice = _voice_context(context_dir)
    user = (f"PILLAR: {pillar}\nFORMAT: {fmt}\n\n"
            f"SOURCE NOTE (ground truth for claims):\n{source_note}\n\n"
            f"BRAND VOICE GUIDE:\n{voice}\n\nDRAFT:\n{draft_text}")
    raw = client.complete_json("review", JUDGE_SYSTEM, user, schema=JUDGE_SCHEMA)
    items = _judge_items(raw)
    if not items:
        # One re-ask: a malformed judge reply is a transport problem, not an
        # editorial verdict, and shouldn't burn a writer retry. This does
        # not touch the reviewer retry cap.
        raw = client.complete_json(
            "review", JUDGE_SYSTEM,
            user + "\n\nYour previous reply was not a usable JSON array of "
                   "checklist objects. Reply with ONLY the JSON array, no "
                   "prose.",
            schema=JUDGE_SCHEMA)
        items = _judge_items(raw)
    if not items:
        # Surface what the model actually said, truncated. Discarding it is
        # what kept this undiagnosable; now the failure carries its evidence.
        snippet = " ".join(str(getattr(client, "last_raw_reply", "")).split())[:220]
        items.append(S.ChecklistItem(
            "voice_match", False,
            "judge returned no usable checklist twice. Model reply was: "
            f"{snippet!r}. Run `python3 -m pipeline doctor --judge` to probe "
            "the judge directly."))
    return items


def _voice_context(context_dir: Path | None = None) -> str:
    d = context_dir or REPO_ROOT / "context"
    parts = []
    for name in ("brand-voice.md", "platforms.md"):
        f = d / name
        if f.is_file():
            parts.append(f.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


# --- verdict -----------------------------------------------------------------

def review(post_id: str, draft_text: str, pillar: str, fmt: str,
           source_note: str, revision_count: int,
           client: llm.LLMClient) -> S.ReviewerVerdict:
    """Full review: mechanical first, judge second (skipped if mechanical
    already failed, to save budget). Verdict carries the specific reason."""
    checklist = mechanical_checklist(draft_text, fmt)
    mech_fails = [c for c in checklist if not c.passed]
    if not mech_fails:
        checklist += judge_subjective(draft_text, pillar, fmt, source_note, client)
    fails = [c for c in checklist if not c.passed]
    passed = not fails
    fail_reason = None if passed else "; ".join(
        f"{c.criterion}: {c.note}" for c in fails)
    return S.ReviewerVerdict(
        post_id=post_id,
        passed=passed,
        checklist=checklist,
        revision_count=revision_count,
        fail_reason=fail_reason,
        reviewed_at=S.now_iso(),
    )
