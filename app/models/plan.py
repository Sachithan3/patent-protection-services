"""Planning data contracts (spec section 6, planning subset).

`QueryVariant` is part of the provider interface contract, so it lands with the
provider layer. `SearchPlan` is consumed by the planner in migration Phase 3.
"""

from typing import Literal

from pydantic import BaseModel, Field


class QueryVariant(BaseModel):
    """One executable search query produced by the planner."""

    text: str
    kind: Literal["keyword", "natural_language", "boolean"]
    rationale: str


class SearchPlan(BaseModel):
    """A structured search strategy for one user draft."""

    features: list[str] = Field(min_length=1, max_length=12)  # atomic technical elements
    queries: list[QueryVariant] = Field(min_length=1, max_length=8)
    cpc_hints: list[str] = []
