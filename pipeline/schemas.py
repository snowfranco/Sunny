"""Validated schemas for every inter-step handoff.

Hard rule from the build brief: every handoff between pipeline steps is a
validated schema, never freeform text parsed by regex. Every dataclass here
validates on construction (SchemaError on violation) and round-trips through
plain dicts for SQLite/JSON storage.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import uuid
from dataclasses import dataclass, field


class SchemaError(ValueError):
    """A handoff payload violated its schema."""


# --- enums / bounds ---------------------------------------------------------

PILLARS = ("build_in_public", "ai_for_shippers", "transition_story")
FORMATS = ("substack_essay", "linkedin_post", "social_copy", "script", "portal_briefing")
NOTE_SOURCES = ("manual", "project_scan", "landscape_scan")
STRATEGIC_RATIONALES = (
    "reactive_trend",
    "long_term_bet",
    "monetization_adjacent",
    "immediate_credibility",
)
SPEAKERS = ("you", "engine")
PIPELINE_STEPS = (
    "researcher",
    "angle_engine",
    "writer",
    "artist",
    "reviewer",
    "repurpose",
    "export",
)
ANALYTICS_PLATFORMS = ("substack", "linkedin")

MAX_TITLE_LEN = 80
MAX_REFINEMENT_TURNS = 5   # then the system forces a decision prompt
MAX_REVIEWER_RETRIES = 2   # then escalate to Snow with the fail reason

# Length bounds per format (reviewer criterion 6). Words for prose formats,
# sentences for social. None means no mechanical bound.
LENGTH_BOUNDS = {
    "substack_essay": ("words", 400, 900),
    "linkedin_post": ("words", 100, 200),
    "social_copy": ("sentences", 1, 3),
    "script": None,
    "portal_briefing": None,
}


# --- helpers ----------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise SchemaError(msg)


def _require_str(value, name: str, allow_empty: bool = False) -> None:
    _require(isinstance(value, str), f"{name} must be a string, got {type(value).__name__}")
    if not allow_empty:
        _require(value.strip() != "", f"{name} must not be empty")


def _require_enum(value, name: str, allowed: tuple) -> None:
    _require(value in allowed, f"{name} must be one of {allowed}, got {value!r}")


def _require_int(value, name: str, lo: int | None = None) -> None:
    _require(isinstance(value, int) and not isinstance(value, bool),
             f"{name} must be an int, got {type(value).__name__}")
    if lo is not None:
        _require(value >= lo, f"{name} must be >= {lo}, got {value}")


class _Base:
    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


# --- schemas ------------------------------------------------------------------

@dataclass
class CaptureNote(_Base):
    note_id: str
    source: str
    raw_text: str
    created_at: str
    # Tier 1 guardrail: landscape-scan claims require a citable source.
    # Optional for manual/project_scan, mandatory for landscape_scan.
    source_url: str | None = None

    def __post_init__(self):
        _require_str(self.note_id, "note_id")
        _require_enum(self.source, "source", NOTE_SOURCES)
        _require_str(self.raw_text, "raw_text")
        _require_str(self.created_at, "created_at")
        if self.source == "landscape_scan":
            _require(bool(self.source_url and str(self.source_url).startswith("http")),
                     "landscape_scan notes require a citable source_url (http...)")


@dataclass
class AngleOption(_Base):
    note_id: str
    angle_id: str
    pillar: str
    format: str
    title: str
    hook: str
    strategic_rationale: str
    rationale: str

    def __post_init__(self):
        _require_str(self.note_id, "note_id")
        _require_str(self.angle_id, "angle_id")
        _require_enum(self.pillar, "pillar", PILLARS)
        _require_enum(self.format, "format", FORMATS)
        _require_str(self.title, "title")
        _require(len(self.title) <= MAX_TITLE_LEN,
                 f"title must be <= {MAX_TITLE_LEN} chars, got {len(self.title)}")
        _require_str(self.hook, "hook")
        _require_enum(self.strategic_rationale, "strategic_rationale", STRATEGIC_RATIONALES)
        _require_str(self.rationale, "rationale")


@dataclass
class RefinementTurn(_Base):
    """One turn in a refinement conversation (angle-pick or edit stage)."""
    session_id: str
    turn_number: int
    speaker: str
    message: str
    resulting_angle_or_draft_id: str | None
    timestamp: str

    def __post_init__(self):
        _require_str(self.session_id, "session_id")
        _require_int(self.turn_number, "turn_number", lo=1)
        _require(self.turn_number <= MAX_REFINEMENT_TURNS,
                 f"turn_number exceeds the {MAX_REFINEMENT_TURNS}-turn refinement cap")
        _require_enum(self.speaker, "speaker", SPEAKERS)
        _require_str(self.message, "message")
        _require_str(self.timestamp, "timestamp")


@dataclass
class PickedAngle(_Base):
    note_id: str
    angle_id: str
    picked_at: str

    def __post_init__(self):
        _require_str(self.note_id, "note_id")
        _require_str(self.angle_id, "angle_id")
        _require_str(self.picked_at, "picked_at")


@dataclass
class WriterOutput(_Base):
    post_id: str
    angle_id: str
    pillar: str
    format: str
    draft_text: str
    voice_context_version: str
    generated_at: str

    def __post_init__(self):
        _require_str(self.post_id, "post_id")
        _require_str(self.angle_id, "angle_id")
        _require_enum(self.pillar, "pillar", PILLARS)
        _require_enum(self.format, "format", FORMATS)
        _require_str(self.draft_text, "draft_text")
        _require_str(self.voice_context_version, "voice_context_version")
        _require_str(self.generated_at, "generated_at")


@dataclass
class ArtistOutput(_Base):
    """v1 scaffold: valid image + caption is the bar. No quality rubric."""
    post_id: str
    image_path: str
    caption: str
    generated_at: str

    def __post_init__(self):
        _require_str(self.post_id, "post_id")
        _require_str(self.image_path, "image_path")
        _require_str(self.caption, "caption")
        _require_str(self.generated_at, "generated_at")


@dataclass
class ChecklistItem(_Base):
    criterion: str
    passed: bool
    note: str

    def __post_init__(self):
        _require_str(self.criterion, "criterion")
        _require(isinstance(self.passed, bool), "passed must be a bool")
        _require(isinstance(self.note, str), "note must be a string")


@dataclass
class ReviewerVerdict(_Base):
    """The LLM-as-judge output."""
    post_id: str
    passed: bool
    checklist: list  # list[ChecklistItem] or list[dict]
    revision_count: int
    fail_reason: str | None
    reviewed_at: str

    def __post_init__(self):
        _require_str(self.post_id, "post_id")
        _require(isinstance(self.passed, bool), "passed must be a bool")
        _require(isinstance(self.checklist, list) and len(self.checklist) > 0,
                 "checklist must be a non-empty list")
        self.checklist = [
            c if isinstance(c, ChecklistItem) else ChecklistItem.from_dict(c)
            for c in self.checklist
        ]
        _require_int(self.revision_count, "revision_count", lo=0)
        _require(self.revision_count <= MAX_REVIEWER_RETRIES,
                 f"revision_count exceeds MAX_REVIEWER_RETRIES={MAX_REVIEWER_RETRIES}")
        if not self.passed:
            _require(bool(self.fail_reason),
                     "a failing verdict must carry a specific fail_reason")
        _require_str(self.reviewed_at, "reviewed_at")

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["checklist"] = [dataclasses.asdict(c) for c in self.checklist]
        return d


@dataclass
class EditedPost(_Base):
    post_id: str
    final_text: str
    edited_at: str

    def __post_init__(self):
        _require_str(self.post_id, "post_id")
        _require_str(self.final_text, "final_text")
        _require_str(self.edited_at, "edited_at")


@dataclass
class RepurposedFormats(_Base):
    post_id: str
    linkedin_extract: str  # 3-6 paragraphs, no headers, ends open
    notes_hook: str        # 1-2 sentences
    generated_at: str

    def __post_init__(self):
        _require_str(self.post_id, "post_id")
        _require_str(self.linkedin_extract, "linkedin_extract")
        n_paras = len([p for p in self.linkedin_extract.split("\n\n") if p.strip()])
        _require(1 <= n_paras <= 6,
                 f"linkedin_extract must be 1-6 paragraphs, got {n_paras}")
        _require(not any(line.lstrip().startswith("#")
                         for line in self.linkedin_extract.splitlines()),
                 "linkedin_extract must not contain headers")
        _require_str(self.notes_hook, "notes_hook")
        _require_str(self.generated_at, "generated_at")


@dataclass
class ExportBundle(_Base):
    """The final artifact. Always an unpublished draft.

    HARD CONSTRAINT: status is 'draft' and nothing else, ever. There is no
    publish code path anywhere in this system. Do not add one.
    """
    post_id: str
    status: str
    post_text: str
    linkedin_extract: str
    notes_hook: str
    image_path: str | None
    caption: str | None
    pillar: str
    exported_at: str

    def __post_init__(self):
        _require_str(self.post_id, "post_id")
        _require(self.status == "draft",
                 "ExportBundle.status must be 'draft'; this system never publishes")
        _require_str(self.post_text, "post_text")
        _require_str(self.linkedin_extract, "linkedin_extract")
        _require_str(self.notes_hook, "notes_hook")
        _require_enum(self.pillar, "pillar", PILLARS)
        _require_str(self.exported_at, "exported_at")


@dataclass
class AnalyticsSnapshot(_Base):
    post_id: str
    platform: str
    views: int
    likes: int
    comments: int
    shares: int
    collected_at: str
    days_since_publish: int

    def __post_init__(self):
        _require_str(self.post_id, "post_id")
        _require_enum(self.platform, "platform", ANALYTICS_PLATFORMS)
        for name in ("views", "likes", "comments", "shares", "days_since_publish"):
            _require_int(getattr(self, name), name, lo=0)
        _require_str(self.collected_at, "collected_at")


@dataclass
class GrowthInsightReport(_Base):
    period_start: str
    period_end: str
    top_performers: list
    pillar_performance: dict
    trend_notes: str
    recommendations: list
    generated_at: str

    def __post_init__(self):
        _require_str(self.period_start, "period_start")
        _require_str(self.period_end, "period_end")
        _require(isinstance(self.top_performers, list), "top_performers must be a list")
        _require(isinstance(self.pillar_performance, dict), "pillar_performance must be a dict")
        for p in PILLARS:
            _require(p in self.pillar_performance,
                     f"pillar_performance missing pillar {p!r}")
        _require(isinstance(self.trend_notes, str), "trend_notes must be a string")
        _require(isinstance(self.recommendations, list), "recommendations must be a list")
        _require_str(self.generated_at, "generated_at")


@dataclass
class ContextUpdateLog(_Base):
    updated_at: str
    changed_files: list
    summary: str
    approved_by: str

    def __post_init__(self):
        _require_str(self.updated_at, "updated_at")
        _require(isinstance(self.changed_files, list) and self.changed_files,
                 "changed_files must be a non-empty list")
        _require_str(self.summary, "summary")
        _require(self.approved_by == "snow", "context updates must be approved by snow")


@dataclass
class PipelineRunLog(_Base):
    """Observability, tier 3 guardrail. One row per step per run."""
    run_id: str
    step: str
    ref_id: str
    input_ref: str
    output_ref: str
    pass_fail: bool | None
    human_override: bool
    timestamp: str

    def __post_init__(self):
        _require_str(self.run_id, "run_id")
        _require_enum(self.step, "step", PIPELINE_STEPS)
        _require_str(self.ref_id, "ref_id")
        _require(isinstance(self.input_ref, str), "input_ref must be a string")
        _require(isinstance(self.output_ref, str), "output_ref must be a string")
        _require(self.pass_fail is None or isinstance(self.pass_fail, bool),
                 "pass_fail must be bool or None")
        _require(isinstance(self.human_override, bool), "human_override must be a bool")
        _require_str(self.timestamp, "timestamp")
