"""Unit tests for the shared provider HTTP client using httpx.MockTransport.

Backoff base is shrunk to 0.001 s so retry tests stay sub-millisecond while
exercising the real tenacity wait policy.
"""

from collections.abc import Callable

import httpx
import pytest

from app.core.circuitbreaker import CircuitBreaker
from app.providers.base import ProviderError
from app.providers.http import ProviderHttpClient

BACKOFF_FOR_TESTS = 0.001


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> ProviderHttpClient:
    kwargs.setdefault("backoff_base_seconds", BACKOFF_FOR_TESTS)
    return ProviderHttpClient(
        "test-provider",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,  # type: ignore[arg-type]
    )


async def test_retries_retryable_status_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    payload = await client.get_json("https://api.example.com/search")

    assert payload == {"ok": True}
    assert len(calls) == 2
    await client.aclose()


async def test_exhausted_retries_raise_retryable_provider_error() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    client = make_client(handler, max_attempts=3)
    with pytest.raises(ProviderError) as excinfo:
        await client.get_json("https://api.example.com/search")

    assert excinfo.value.retryable is True
    assert len(calls) == 3
    await client.aclose()


async def test_non_retryable_status_fails_fast() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    client = make_client(handler)
    with pytest.raises(ProviderError) as excinfo:
        await client.get_json("https://api.example.com/patent/NOPE")

    assert excinfo.value.retryable is False
    assert len(calls) == 1
    await client.aclose()


async def test_transport_errors_are_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    payload = await client.get_json("https://api.example.com/search")

    assert payload == {"ok": True}
    assert len(calls) == 3
    await client.aclose()


async def test_circuit_opens_after_threshold_and_skips_calls() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500)

    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
    client = make_client(handler, breaker=breaker, max_attempts=2)

    with pytest.raises(ProviderError):
        await client.get_json("https://api.example.com/search")
    assert len(calls) == 2  # two attempts, breaker now open

    with pytest.raises(ProviderError) as excinfo:
        await client.get_json("https://api.example.com/search")
    assert "circuit open" in str(excinfo.value)
    assert len(calls) == 2  # no new transport call while open
    assert breaker.state == "open"
    await client.aclose()


async def test_circuit_half_opens_after_cooldown_and_closes_on_success() -> None:
    calls: list[int] = []
    now = {"t": 0.0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"ok": True})

    def clock() -> float:
        return now["t"]

    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0, clock=clock)
    client = make_client(handler, breaker=breaker)

    breaker.record_failure()
    assert breaker.state == "open"
    now["t"] += 61.0
    assert breaker.state == "half_open"

    payload = await client.get_json("https://api.example.com/search")
    assert payload == {"ok": True}
    assert breaker.state == "closed"
    await client.aclose()


async def test_rate_limiter_is_applied_before_requests() -> None:
    acquisitions: list[int] = []

    class CountingBucket:
        async def acquire(self) -> None:
            acquisitions.append(1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)  # no rate limiter configured
    client._rate_limiter = CountingBucket()  # type: ignore[assignment]
    await client.get_json("https://api.example.com/search")

    assert len(acquisitions) == 1
    await client.aclose()
