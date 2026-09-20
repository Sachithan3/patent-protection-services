"""Provider interfaces and shared errors for patent data sources (spec section 7.1).

Every external patent source is hidden behind one of these protocols so adapters can
be swapped, circuit-broken, and contract-tested without touching agent code.
"""

from typing import Protocol

from app.models.patents import PatentClaims, PatentStub
from app.models.plan import QueryVariant


class ProviderError(Exception):
    """Raised by provider adapters; `retryable` drives the shared retry policy."""

    def __init__(self, provider: str, message: str, retryable: bool = False) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.retryable = retryable


class PatentSearchProvider(Protocol):
    """A source of candidate patent stubs for a query variant."""

    name: str

    async def search(self, query: QueryVariant, limit: int) -> list[PatentStub]:
        """Return up to `limit` candidate stubs for the query."""
        ...

    async def healthcheck(self) -> bool:
        """Return True when the provider is reachable and answering."""
        ...


class ClaimsProvider(Protocol):
    """A source of full claim text for a normalized patent id."""

    name: str

    async def get_claims(self, patent_id: str) -> PatentClaims | None:
        """Return parsed claims, or None when this source cannot serve the id."""
        ...
