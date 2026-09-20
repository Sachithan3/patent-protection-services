"""Shared outbound HTTP layer for provider adapters (spec sections 7.3, 14.2).

One place owns timeouts, retries (429/5xx/timeouts only), per-provider rate
limiting, and circuit-breaker accounting. Adapters stay focused on mapping
responses into `PatentStub` / `PatentClaims`.

Retries use tenacity with random-exponential backoff; `backoff_base_seconds`
is constructor-injectable so tests shrink waits to sub-millisecond.
"""

from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.core.circuitbreaker import CircuitBreaker, CircuitOpenError
from app.core.ratelimit import TokenBucket
from app.providers.base import ProviderError

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 8.0


class _Retryable(Exception):
    """Internal marker for transient failures the retry loop should cover."""


class ProviderHttpClient:
    """Retrying, rate-limited, circuit-broken fetcher for a single provider."""

    def __init__(
        self,
        provider_name: str,
        *,
        rate_limiter: TokenBucket | None = None,
        breaker: CircuitBreaker | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base_seconds: float = 0.5,
    ) -> None:
        self.provider_name = provider_name
        self._rate_limiter = rate_limiter
        self._breaker = breaker
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds

    async def aclose(self) -> None:
        """Close the underlying client when this instance created it."""
        if self._owns_client:
            await self._client.aclose()

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """GET a URL and return the parsed JSON body."""
        response = await self._send(url, params=params, headers=headers, json_body=None)
        return response.json()

    async def post_json(
        self,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """POST a JSON body and return the parsed JSON response."""
        response = await self._send(url, params=params, headers=headers, json_body=json)
        return response.json()

    async def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """GET a URL and return the response body as text (page fetcher fallback)."""
        response = await self._send(url, params=params, headers=headers, json_body=None)
        return response.text

    async def _send(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        json_body: Any,
    ) -> httpx.Response:
        retryer = AsyncRetrying(
            retry=retry_if_exception_type(_Retryable),
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_random_exponential(multiplier=self._backoff_base, max=MAX_BACKOFF_SECONDS),
            reraise=True,
        )
        try:
            response: httpx.Response = await retryer(
                self._attempt_once, url, params=params, headers=headers, json_body=json_body
            )
        except CircuitOpenError as error:
            raise ProviderError(self.provider_name, "circuit open; call skipped") from error
        except _Retryable as error:
            raise ProviderError(
                self.provider_name,
                f"request failed after {self._max_attempts} attempts: {error}",
                retryable=True,
            ) from error
        if self._breaker is not None:
            self._breaker.record_success()
        return response

    async def _attempt_once(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        headers: dict[str, str] | None,
        json_body: Any,
    ) -> httpx.Response:
        if self._breaker is not None:
            self._breaker.check()
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire()
        method = "POST" if json_body is not None else "GET"
        try:
            response = await self._client.request(
                method, url, params=params, headers=headers, json=json_body
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            self._note_failure()
            raise _Retryable(f"{type(error).__name__}: {error}") from error
        if response.status_code in RETRYABLE_STATUS_CODES:
            self._note_failure()
            raise _Retryable(f"HTTP {response.status_code} from provider")
        if response.is_error:
            raise ProviderError(self.provider_name, f"HTTP {response.status_code}", retryable=False)
        return response

    def _note_failure(self) -> None:
        if self._breaker is not None:
            self._breaker.record_failure()
