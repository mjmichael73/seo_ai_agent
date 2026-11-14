"""Typed request, evidence, and report models shared by the API and agent."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

Severity = Literal["critical", "high", "medium", "low", "info"]


class AuditRequest(BaseModel):
    """User-supplied scope for a read-only website audit."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    max_pages: int = Field(default=5, ge=1, le=20)
    keyword: str | None = Field(default=None, max_length=160)

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str | None:
        """Normalize optional research terms and reject whitespace-only input."""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("keyword must contain non-whitespace characters")
        return normalized


class KeywordResearchRequest(BaseModel):
    """Request for unauthenticated, qualitative web-search research."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        """Trim the query and reject whitespace-only terms."""

        normalized = value.strip()
        if not normalized:
            raise ValueError("query must contain non-whitespace characters")
        return normalized


class SearchResult(BaseModel):
    """A public search result; it is contextual research, not a rank measurement."""

    title: str
    url: str
    snippet: str = ""


class PageSnapshot(BaseModel):
    """Facts collected from a single HTML page, without changing the site."""

    url: str
    final_url: str
    status_code: int
    content_type: str | None = None
    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    robots_meta: str | None = None
    headings: list[str] = Field(default_factory=list)
    h1_count: int = 0
    word_count: int = 0
    images_total: int = 0
    images_missing_alt: int = 0
    internal_links: int = 0
    external_links: int = 0
    discovered_links: list[str] = Field(default_factory=list)
    load_time_ms: int = 0


class Finding(BaseModel):
    """An evidence-backed, actionable SEO observation."""

    severity: Severity
    category: str
    issue: str
    evidence: str
    recommendation: str
    url: str | None = None


class SiteReport(BaseModel):
    """Read-only audit output. The score is a local heuristic, not a search ranking."""

    target_url: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    score: int = Field(ge=0, le=100)
    summary: str
    pages: list[PageSnapshot] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    priority_actions: list[str] = Field(default_factory=list)
    keyword: str | None = None
    keyword_results: list[SearchResult] = Field(default_factory=list)
    robots_status: str = "unknown"
    sitemap_urls: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReportNarrative(BaseModel):
    """Constrained optional LLM output layered over deterministic audit findings."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    priority_actions: list[str] = Field(default_factory=list, max_length=3)


class HealthResponse(BaseModel):
    """Liveness response that does not reveal credentials."""

    status: Literal["ok"] = "ok"
    llm_enabled: bool
    version: str
