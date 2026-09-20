"""Pydantic v2 data contracts shared across modules (spec section 6, patents subset).

The remaining contract groups (plan, streaming, results) land in Phase 3+ as their
consumers are built.
"""

from pydantic import BaseModel, Field


class PatentStub(BaseModel):
    """A candidate patent as returned by a search provider."""

    patent_id: str  # normalized, e.g. "US10123456B2"
    title: str
    abstract: str | None = None
    assignee: str | None = None
    publication_date: str | None = None  # ISO date if known
    cpc: list[str] = []
    url: str | None = None
    source: str  # provider name
    provider_score: float | None = None  # provider relevance if given


class Claim(BaseModel):
    """A single patent claim with dependency classification."""

    number: int
    text: str
    is_independent: bool


class PatentClaims(BaseModel):
    """Full claim set for one patent, from a claims source."""

    patent_id: str
    claims: list[Claim] = Field(min_length=1)
    source: str
    fetched_at: str  # ISO timestamp
