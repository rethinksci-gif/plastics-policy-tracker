"""Pydantic data structures shared by the pipeline, the tests and (via YAML) the website."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

STAGES: list[str] = [
    "planned",
    "consultation",
    "impact-assessment",
    "proposal",
    "parliament-council",
    "trilogue",
    "adopted",
    "published",
    "in-force",
    "implementing-acts",
    "in-application",
]
TERMINAL_STAGES = ["withdrawn", "stalled"]
Stage = Literal[
    "planned",
    "consultation",
    "impact-assessment",
    "proposal",
    "parliament-council",
    "trilogue",
    "adopted",
    "published",
    "in-force",
    "implementing-acts",
    "in-application",
    "withdrawn",
    "stalled",
]

Instrument = Literal[
    "regulation",
    "directive",
    "implementing-act",
    "delegated-act",
    "decision",
    "national-law",
    "standard",
    "treaty",
    "tax",
    "EPR-scheme",
    "policy",
]

Impact = Literal["high", "medium", "low"]
Trust = Literal["official", "trade-association", "media"]

# Month precision ("2026-11") or day precision ("2026-11-03").
FUZZY_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$")
JURISDICTION_RE = re.compile(r"^(GLOBAL|EU|UK|CN|US)(-[A-Z]{2,3})?$")
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def fuzzy_date_bounds(value: str) -> tuple[date, date]:
    """Earliest and latest calendar day a fuzzy date can refer to."""
    parts = [int(p) for p in value.split("-")]
    if len(parts) == 3:
        d = date(*parts)
        return d, d
    y, m = parts
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


class FuzzyDate(str):
    """String date that allows month precision."""

    @classmethod
    def __get_pydantic_core_schema__(cls, _source, handler):  # pragma: no cover - pydantic glue
        from pydantic_core import core_schema

        def validate(v):
            if isinstance(v, (date, datetime)):
                v = v.strftime("%Y-%m-%d")
            v = str(v)
            if not FUZZY_DATE_RE.match(v):
                raise ValueError(f"invalid date '{v}' (expected YYYY-MM or YYYY-MM-DD)")
            fuzzy_date_bounds(v)  # raises on impossible days such as 2026-02-30
            return v

        return core_schema.no_info_plain_validator_function(
            validate, serialization=core_schema.plain_serializer_function_ser_schema(str)
        )


# ---------------------------------------------------------------------------
# Dossier
# ---------------------------------------------------------------------------


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Update(Strict):
    date: FuzzyDate
    summary: str = Field(min_length=20)
    source_url: HttpUrl
    source_quote: str = Field(min_length=15)
    source_quote_en: str | None = None
    source_lang: str = "en"
    stage_change: Stage | None = None
    review_id: str

    @model_validator(mode="after")
    def _translation_required(self):
        if self.source_lang != "en" and not self.source_quote_en:
            raise ValueError("source_quote_en is required when the source is not in English")
        return self


class NextStep(Strict):
    date: FuzzyDate
    text: str = Field(min_length=5)
    source_url: HttpUrl
    status: Literal["expected", "to-be-confirmed"] = "expected"


class KeyDate(Strict):
    date: FuzzyDate
    text: str = Field(min_length=5)
    source_url: HttpUrl | None = None


class Dossier(Strict):
    id: str
    title: str
    short_title: str | None = None
    title_original: str | None = None
    jurisdiction: str
    instrument: Instrument
    topics: list[str] = Field(min_length=1)
    stage: Stage
    affected: list[str] = Field(min_length=1)
    impact: Impact
    official_links: list[HttpUrl] = Field(min_length=1)
    summary: str | None = None
    updates: list[Update] = Field(default_factory=list)
    next_steps: list[NextStep] = Field(default_factory=list)
    key_dates: list[KeyDate] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, v):
        if not ID_RE.match(v):
            raise ValueError("id must be kebab-case")
        return v

    @field_validator("jurisdiction")
    @classmethod
    def _jur(cls, v):
        if not JURISDICTION_RE.match(v):
            raise ValueError(f"invalid jurisdiction '{v}'")
        return v

    @model_validator(mode="after")
    def _updates_reverse_chronological(self):
        starts = [fuzzy_date_bounds(u.date)[0] for u in self.updates]
        if starts != sorted(starts, reverse=True):
            raise ValueError("updates must be in reverse chronological order (newest first)")
        return self


# ---------------------------------------------------------------------------
# Sources and snapshots
# ---------------------------------------------------------------------------


class Source(Strict):
    id: str
    name: str
    url: HttpUrl
    type: Literal["rss", "page-watch", "api", "email-alert"]
    frequency: Literal["daily", "weekly"] = "daily"
    jurisdiction: str
    trust: Trust
    enabled: bool = True
    notes: str | None = None
    keywords: list[str] = Field(default_factory=list)  # optional local pre-filter for broad feeds
    handler: str | None = None  # api sources: name of the handler in fetch.API_HANDLERS
    extract: Literal["main", "full"] = "main"  # "full" keeps all page text (legal texts)
    lang: str = "en"


class Snapshot(BaseModel):
    """One captured document in data/raw/."""

    id: str  # "<yyyy-mm-dd>/<source_id>-<sha8>"
    source_id: str
    url: str
    title: str | None = None
    fetched_at: datetime
    published: str | None = None
    sha256: str
    trust: Trust
    jurisdiction: str
    lang: str | None = None
    text: str


# ---------------------------------------------------------------------------
# Candidates, drafts and reviews
# ---------------------------------------------------------------------------


class TriageResult(BaseModel):
    relevance: float = Field(ge=0, le=1)
    dossier_id: str | None = None
    new_dossier_suggestion: str | None = None
    category: str
    reason: str


class DraftUpdate(BaseModel):
    """What the drafting model proposes; becomes an `Update` only after review."""

    dossier_id: str
    date: FuzzyDate
    summary: str
    source_url: str
    source_quote: str
    source_quote_en: str | None = None
    source_lang: str = "en"
    stage_change: Stage | None = None
    next_steps: list[NextStep] = Field(default_factory=list)
    key_dates: list[KeyDate] = Field(default_factory=list)
    interpretation: str | None = None  # analysis, kept apart from facts


class Candidate(BaseModel):
    id: str  # e.g. 2026-10-14-003
    created: date
    snapshot_id: str
    source_id: str
    source_url: str
    source_trust: Trust
    title: str | None = None
    triage: TriageResult
    draft: DraftUpdate | None = None
    status: Literal["triaged", "drafted", "passed", "quarantined", "discarded", "published"] = "triaged"
    review_id: str | None = None
    issue: str | None = None  # issue slug once the candidate has been considered for an issue


class CheckResult(BaseModel):
    layer: int
    name: str
    passed: bool
    severity: Literal["reject", "flag", "info"] = "reject"
    detail: str = ""


class LLMReview(BaseModel):
    verdict: Literal["supported", "partially_supported", "unsupported"]
    confidence: float = Field(ge=0, le=1)
    checks: dict[str, bool] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class ReviewRecord(BaseModel):
    review_id: str
    candidate_id: str
    dossier_id: str
    created: datetime
    impact: Impact
    checks: list[CheckResult]
    llm_review: LLMReview | None = None
    model: str | None = None  # model that ran the layer-3 review
    confirm_review: LLMReview | None = None  # second opinion for impact: high items
    confirm_model: str | None = None
    outcome: Literal["passed", "quarantined", "human-review"]
    reasons: list[str] = Field(default_factory=list)


class EditorialReview(BaseModel):
    passed: bool
    contradictions: list[str] = Field(default_factory=list)
    history_conflicts: list[str] = Field(default_factory=list)
    missing_high_impact: list[str] = Field(default_factory=list)
    terminology_issues: list[str] = Field(default_factory=list)
    translation_issues: list[str] = Field(default_factory=list)
    fact_vs_interpretation_issues: list[str] = Field(default_factory=list)
    item_flags: dict[str, list[str]] = Field(default_factory=dict)  # candidate id -> blocking (factual) problems
    style_notes: dict[str, list[str]] = Field(default_factory=dict)  # candidate id -> wording notes, never blocking
    notes: str = ""
