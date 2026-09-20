"""PatentsView adapter: metadata enrichment only; never a claims source (spec 7.2).

PatentsView is migrating into the USPTO Open Data Portal, so keep this adapter thin
and expect endpoint churn. Requires its own free API key. Endpoint and auth facts:
docs/PROVIDERS.md.
"""

import logging
from typing import Any

from app.models.patents import PatentStub
from app.models.plan import QueryVariant
from app.providers.base import ProviderError
from app.providers.http import ProviderHttpClient
from app.providers.ids import normalize_patent_id

logger = logging.getLogger(__name__)

_REQUEST_FIELDS = ["patent_id", "patent_title", "patent_abstract", "patent_date"]


class PatentsViewEnrichmentProvider:
    """Search adapter for search.patentsview.org (enrichment role)."""

    name = "patentsview"

    def __init__(self, http: ProviderHttpClient, *, base_url: str, api_key: str | None) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def search(self, query: QueryVariant, limit: int) -> list[PatentStub]:
        """Title/abstract text search; enriches the pool with assignee-grade metadata."""
        if not self._api_key:
            raise ProviderError(
                self.name,
                "PatentsView API key is not configured (PATENTSVIEW_API_KEY)",
            )
        payload = await self._http.post_json(
            f"{self._base_url}/api/v1/patent/",
            json={
                "q": {"_text_any": {"patent_title": query.text}},
                "f": _REQUEST_FIELDS,
                "o": {"size": limit},
            },
            headers={"X-API-KEY": self._api_key},
        )
        records = payload.get("patents")
        if not isinstance(records, list):
            raise ProviderError(self.name, "unexpected response shape: no 'patents' list")
        stubs = [s for s in (self._to_stub(r) for r in records) if s is not None]
        logger.info(
            "patentsview: %d usable stubs of %d records", len(stubs), len(records)
        )
        return stubs

    async def healthcheck(self) -> bool:
        if not self._api_key:
            return False
        probe = QueryVariant(text="robot", kind="keyword", rationale="healthcheck")
        try:
            await self.search(probe, limit=1)
            return True
        except ProviderError:
            return False

    def _to_stub(self, record: Any) -> PatentStub | None:
        if not isinstance(record, dict):
            return None
        raw_id = record.get("patent_id")
        if not isinstance(raw_id, str) or not raw_id:
            return None
        try:
            # PatentsView ids are bare grant numbers ("10123456"); add the US prefix.
            candidate = raw_id if any(c.isalpha() for c in raw_id) else f"US{raw_id}"
            patent_id = normalize_patent_id(candidate)
        except ValueError:
            logger.debug("patentsview: skipping record with unparseable id %r", raw_id)
            return None
        return PatentStub(
            patent_id=patent_id,
            title=str(record.get("patent_title") or "Untitled"),
            abstract=str(record["patent_abstract"]) if record.get("patent_abstract") else None,
            publication_date=str(record["patent_date"]) if record.get("patent_date") else None,
            cpc=[],
            source=self.name,
            provider_score=None,
        )

    async def aclose(self) -> None:
        await self._http.aclose()
