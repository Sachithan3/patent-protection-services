"""Provider registry: parallel search fan-out, dedupe merge, claims fallback chain.

Spec section 7.3. A provider failing is a warning, never a job failure. The pool is
keyed by `dedupe_key` so kind-code variants of one patent collapse; the first provider
in the configured order wins a key (PQAI's semantic ranking is the strongest signal).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.core.circuitbreaker import CircuitBreaker
from app.core.config import Settings, get_settings
from app.core.ratelimit import TokenBucket
from app.models.patents import PatentClaims, PatentStub
from app.models.plan import QueryVariant
from app.providers.base import ClaimsProvider, PatentSearchProvider, ProviderError
from app.providers.google_patents_page import GooglePatentsPageProvider
from app.providers.http import ProviderHttpClient
from app.providers.ids import dedupe_key
from app.providers.patentsview import PatentsViewEnrichmentProvider
from app.providers.pqai import PqaiSearchProvider
from app.providers.uspto_odp import UsptoOdpProvider

logger = logging.getLogger(__name__)


@dataclass
class ProviderWarning:
    provider: str
    message: str


@dataclass
class SearchOutcome:
    pool: dict[str, PatentStub] = field(default_factory=dict)
    warnings: list[ProviderWarning] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)


@runtime_checkable
class _Closable(Protocol):
    async def aclose(self) -> None: ...


class ProviderRegistry:
    """Owns the configured providers and orchestrates fan-out and fallback."""

    def __init__(
        self,
        search_providers: list[PatentSearchProvider],
        claims_providers: list[ClaimsProvider],
        *,
        concurrency: int = 4,
    ) -> None:
        self._search_providers = search_providers
        self._claims_providers = claims_providers
        self._concurrency = max(1, concurrency)
        self._closables: list[_Closable] = [
            p for p in (*search_providers, *claims_providers) if isinstance(p, _Closable)
        ]

    async def search(self, queries: list[QueryVariant], limit: int) -> SearchOutcome:
        """Fan queries out to all providers in parallel, merge results by dedupe key."""
        semaphore = asyncio.Semaphore(self._concurrency)

        async def run_one(provider: PatentSearchProvider, query: QueryVariant
                          ) -> tuple[PatentSearchProvider, list[PatentStub], ProviderError | None]:
            async with semaphore:
                try:
                    return provider, await provider.search(query, limit), None
                except ProviderError as error:
                    return provider, [], error

        pairs = [(provider, query) for provider in self._search_providers for query in queries]
        outcomes = await asyncio.gather(*(run_one(provider, query) for provider, query in pairs))

        outcome = SearchOutcome()
        for provider, stubs, error in outcomes:
            if provider.name not in outcome.providers_used:
                outcome.providers_used.append(provider.name)
            if error is not None:
                outcome.warnings.append(ProviderWarning(provider.name, str(error)))
                continue
            for stub in stubs:
                try:
                    key = dedupe_key(stub.patent_id)
                except ValueError:
                    outcome.warnings.append(
                        ProviderWarning(provider.name, f"unparseable id {stub.patent_id!r}")
                    )
                    continue
                outcome.pool.setdefault(key, stub)
        logger.info(
            "registry: %d unique candidates from %d providers, %d warnings",
            len(outcome.pool),
            len(outcome.providers_used),
            len(outcome.warnings),
        )
        return outcome

    async def get_claims(self, patent_id: str) -> tuple[PatentClaims | None, list[ProviderWarning]]:
        """Walk the claims chain in order; None means no source could serve the id."""
        warnings: list[ProviderWarning] = []
        for provider in self._claims_providers:
            try:
                claims = await provider.get_claims(patent_id)
            except ProviderError as error:
                warnings.append(ProviderWarning(provider.name, str(error)))
                continue
            if claims is not None:
                return claims, warnings
            warnings.append(ProviderWarning(provider.name, f"no claims available for {patent_id}"))
        return None, warnings

    async def aclose(self) -> None:
        for closable in self._closables:
            await closable.aclose()


def build_registry(settings: Settings | None = None) -> ProviderRegistry:
    """Wire providers from settings; unconfigured providers still join so their
    'not configured' errors surface as visible warnings in demos and health checks."""
    settings = settings or get_settings()
    search_providers: list[PatentSearchProvider] = [
        PqaiSearchProvider(
            _http_client("pqai", settings),
            base_url=settings.pqai_base_url,
            token=settings.pqai_token,
        ),
        UsptoOdpProvider(
            _http_client("uspto_odp", settings),
            base_url=settings.uspto_base_url,
            api_key=settings.uspto_api_key,
        ),
        PatentsViewEnrichmentProvider(
            _http_client("patentsview", settings),
            base_url=settings.patentsview_base_url,
            api_key=settings.patentsview_api_key,
        ),
    ]
    claims_providers: list[ClaimsProvider] = [
        UsptoOdpProvider(
            _http_client("uspto_odp_claims", settings),
            base_url=settings.uspto_base_url,
            api_key=settings.uspto_api_key,
        ),
        GooglePatentsPageProvider(
            _http_client("google_patents_page", settings),
            base_url=settings.google_patents_base_url,
            user_agent=settings.provider_user_agent,
        ),
    ]
    return ProviderRegistry(
        search_providers,
        claims_providers,
        concurrency=settings.provider_concurrency,
    )


def _http_client(provider: str, settings: Settings) -> ProviderHttpClient:
    return ProviderHttpClient(
        provider,
        rate_limiter=TokenBucket(rate_per_second=1.0, capacity=5.0),
        breaker=CircuitBreaker(),
        timeout_seconds=settings.provider_timeout_seconds,
        max_attempts=settings.provider_max_attempts,
    )
