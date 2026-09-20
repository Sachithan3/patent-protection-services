"""Unit tests for the provider registry: fan-out, dedupe merge, warnings, claims chain."""

from app.models.patents import PatentStub
from app.models.plan import QueryVariant
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry, ProviderWarning


def stub(pid: str, source: str) -> PatentStub:
    return PatentStub(patent_id=pid, title=f"title {pid}", source=source)


class FakeSearch:
    def __init__(self, name: str, results: list[PatentStub] | Exception) -> None:
        self.name = name
        self._results = results

    async def search(self, query: QueryVariant, limit: int) -> list[PatentStub]:
        if isinstance(self._results, Exception):
            raise self._results
        return self._results

    async def healthcheck(self) -> bool:
        return True


class FakeClaims:
    def __init__(self, name: str, result: object) -> None:
        self.name = name
        self._result = result

    async def get_claims(self, patent_id: str):  # noqa: ANN201 - test double
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def query() -> QueryVariant:
    return QueryVariant(text="q", kind="keyword", rationale="test")


async def test_parallel_fanout_merges_and_dedupes() -> None:
    registry = ProviderRegistry(
        [
            FakeSearch("a", [stub("US10123456B2", "a"), stub("US99999999B1", "a")]),
            FakeSearch("b", [stub("US 10,123,456 A1", "b"), stub("EP3456789B1", "b")]),
        ],
        [],
    )
    outcome = await registry.search([query(), query()], limit=10)

    # US10123456B2 (a) and US 10,123,456 A1 (b) collapse to one dedupe key; first wins.
    assert len(outcome.pool) == 3
    assert outcome.pool["US10123456"].source == "a"
    assert set(outcome.providers_used) == {"a", "b"}
    assert outcome.warnings == []


async def test_provider_failure_becomes_warning_not_job_failure() -> None:
    registry = ProviderRegistry(
        [
            FakeSearch("dead", ProviderError("dead", "HTTP 503", retryable=True)),
            FakeSearch("alive", [stub("US11111111B2", "alive")]),
        ],
        [],
    )
    outcome = await registry.search([query()], limit=10)

    assert len(outcome.pool) == 1
    assert outcome.warnings == [ProviderWarning("dead", "[dead] HTTP 503")]
    assert outcome.providers_used == ["dead", "alive"]


async def test_unparseable_id_is_skipped_with_warning() -> None:
    registry = ProviderRegistry([FakeSearch("a", [stub("garbage-id", "a")])], [])
    outcome = await registry.search([query()], limit=10)

    assert outcome.pool == {}
    assert len(outcome.warnings) == 1
    assert "unparseable id" in outcome.warnings[0].message


async def test_claims_chain_walks_sources_in_order() -> None:
    from app.models.patents import Claim, PatentClaims

    good = PatentClaims(
        patent_id="US10123456B2",
        claims=[Claim(number=1, text="A robot comprising: a lidar.", is_independent=True)],
        source="second",
        fetched_at="2026-09-20T00:00:00Z",
    )
    registry = ProviderRegistry(
        [],
        [
            FakeClaims("first", None),  # serves nothing: fall through
            FakeClaims("second", good),
        ],
    )
    claims, warnings = await registry.get_claims("US10123456B2")

    assert claims is good
    assert [w.provider for w in warnings] == ["first"]


async def test_claims_chain_provider_error_is_caught_and_fallthrough_continues() -> None:
    from app.models.patents import Claim, PatentClaims

    good = PatentClaims(
        patent_id="US10123456B2",
        claims=[Claim(number=1, text="A robot comprising: a lidar.", is_independent=True)],
        source="second",
        fetched_at="2026-09-20T00:00:00Z",
    )
    registry = ProviderRegistry(
        [],
        [
            FakeClaims("first", ProviderError("first", "HTTP 500", retryable=True)),
            FakeClaims("second", good),
        ],
    )
    claims, warnings = await registry.get_claims("US10123456B2")

    assert claims is good
    assert [w.provider for w in warnings] == ["first"]


async def test_claims_chain_exhausted_returns_none() -> None:
    registry = ProviderRegistry([], [FakeClaims("only", None)])
    claims, warnings = await registry.get_claims("US10123456B2")

    assert claims is None
    assert len(warnings) == 1


def test_build_registry_wires_three_search_providers() -> None:
    from app.providers.registry import build_registry

    registry = build_registry()
    assert len(registry._search_providers) == 3
    assert len(registry._claims_providers) == 2  # uspto_odp -> google_patents_page
    assert registry._closables  # all adapters own closable http clients
