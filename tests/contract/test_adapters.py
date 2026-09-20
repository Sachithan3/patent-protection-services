"""Contract tests: raw provider responses (fixtures) map into PatentStub models.

Fixtures are synthetic-but-realistic per docs/PROVIDERS.md; re-record from live
responses once credentials exist (see tests/fixtures/README.md).
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.models.plan import QueryVariant
from app.providers.base import ProviderError
from app.providers.google_patents_page import GooglePatentsPageProvider
from app.providers.http import ProviderHttpClient
from app.providers.patentsview import PatentsViewEnrichmentProvider
from app.providers.pqai import PqaiSearchProvider
from app.providers.uspto_odp import UsptoOdpProvider

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def query() -> QueryVariant:
    return QueryVariant(text="fire fighting drone", kind="natural_language", rationale="test")


def client() -> ProviderHttpClient:
    return ProviderHttpClient("test", backoff_base_seconds=0.001)


@respx.mock
async def test_pqai_maps_fixture_to_normalized_stubs() -> None:
    respx.get("https://api.projectpq.ai/search/102/").respond(
        json=load_fixture("pqai_search.json")
    )
    provider = PqaiSearchProvider(
        http=client(), base_url="https://api.projectpq.ai", token="test-token"
    )
    try:
        stubs = await provider.search(query(), limit=10)
    finally:
        await provider.aclose()

    assert [s.patent_id for s in stubs] == ["US10123456B2", "US10123457B2"]
    assert stubs[0].abstract is not None
    assert stubs[0].provider_score == pytest.approx(0.873)
    assert stubs[1].abstract is None  # abstract-less stubs are kept, flagged downstream
    assert all(s.source == "pqai" for s in stubs)


@respx.mock
async def test_pqai_requires_token() -> None:
    provider = PqaiSearchProvider(http=client(), base_url="https://api.projectpq.ai", token=None)
    try:
        with pytest.raises(Exception, match="token"):
            await provider.search(query(), limit=10)
    finally:
        await provider.aclose()


@respx.mock
async def test_uspto_maps_fixture_to_normalized_stubs() -> None:
    respx.get("https://api.uspto.gov/api/v1/patent/applications/search").respond(
        json=load_fixture("uspto_search.json")
    )
    provider = UsptoOdpProvider(http=client(), base_url="https://api.uspto.gov", api_key="test-key")
    try:
        stubs = await provider.search(query(), limit=10)
    finally:
        await provider.aclose()

    assert [s.patent_id for s in stubs] == ["US10123456"]
    assert stubs[0].title == "Autonomous warehouse inventory robot"
    assert stubs[0].abstract is None  # ODP carries no abstracts
    assert stubs[0].assignee == "Acme Robotics Inc"


@respx.mock
async def test_uspto_get_claims_returns_none_for_fallthrough() -> None:
    provider = UsptoOdpProvider(http=client(), base_url="https://api.uspto.gov", api_key="test-key")
    try:
        claims = await provider.get_claims("US10123456B2")
    finally:
        await provider.aclose()

    assert claims is None


@respx.mock
async def test_patentsview_maps_fixture_to_normalized_stubs() -> None:
    respx.post("https://search.patentsview.org/api/v1/patent/").respond(
        json=load_fixture("patentsview_query.json")
    )
    provider = PatentsViewEnrichmentProvider(
        http=client(), base_url="https://search.patentsview.org", api_key="test-key"
    )
    try:
        stubs = await provider.search(query(), limit=10)
    finally:
        await provider.aclose()

    assert [s.patent_id for s in stubs] == ["US10123456"]
    assert stubs[0].title == "Warehouse inventory robot with lidar mapping"


def google_provider(page_html: str) -> GooglePatentsPageProvider:
    async def public_resolver(host: str) -> list[str]:
        return ["8.8.8.8"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page_html)

    http = ProviderHttpClient(
        "test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        backoff_base_seconds=0.001,
    )
    return GooglePatentsPageProvider(
        http,
        base_url="https://patents.google.com",
        user_agent="ClaimGuardAI/1.0 (test)",
        resolver=public_resolver,
    )


def google_page_html() -> str:
    return (FIXTURES / "google_patent_page.html").read_text(encoding="utf-8")


async def test_google_page_maps_fixture_to_claims() -> None:
    provider = google_provider(google_page_html())
    try:
        claims = await provider.get_claims("US10123456B2")
    finally:
        await provider.aclose()

    assert claims is not None
    assert claims.patent_id == "US10123456B2"
    assert claims.source == "google_patents_page"
    assert [c.number for c in claims.claims] == [1, 2]
    assert claims.claims[0].is_independent is True
    assert claims.claims[1].is_independent is False  # references "claim 1"
    assert "lidar sensor" in claims.claims[0].text


async def test_google_page_without_claims_section_returns_none() -> None:
    provider = google_provider("<html><body><p>No claims here.</p></body></html>")
    try:
        assert await provider.get_claims("US10123456B2") is None
    finally:
        await provider.aclose()


async def test_google_page_unparseable_id_returns_none() -> None:
    provider = google_provider(google_page_html())
    try:
        assert await provider.get_claims("not-a-patent") is None
    finally:
        await provider.aclose()


async def test_google_page_blocked_resolved_ip_raises() -> None:
    async def metadata_resolver(host: str) -> list[str]:
        return ["169.254.169.254"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="x")

    http = ProviderHttpClient(
        "test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        backoff_base_seconds=0.001,
    )
    provider = GooglePatentsPageProvider(
        http,
        base_url="https://patents.google.com",
        user_agent="ClaimGuardAI/1.0 (test)",
        resolver=metadata_resolver,
    )
    try:
        with pytest.raises(ProviderError, match="not allowed"):
            await provider.get_claims("US10123456B2")
    finally:
        await provider.aclose()
