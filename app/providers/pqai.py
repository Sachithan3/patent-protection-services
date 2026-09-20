"""PQAI semantic search adapter (spec section 7.2; verified facts in docs/PROVIDERS.md).

PQAI is the primary candidate generator: natural-language queries over a semantic
index. Requires a token (PQAI+ subscription or email request) — a spec deviation
recorded in PROVIDERS.md. Response items are mapped defensively because exact
result-item field names are pending live confirmation.
"""

import logging
from typing import Any

from app.models.patents import PatentStub
from app.models.plan import QueryVariant
from app.providers.base import ProviderError
from app.providers.http import ProviderHttpClient
from app.providers.ids import normalize_patent_id

logger = logging.getLogger(__name__)

_ID_FIELDS = ("id", "publication_number", "publicationNumber", "pn")
_DATE_FIELDS = ("date", "publication_date", "publicationDate")


class PqaiSearchProvider:
    """Search adapter for api.projectpq.ai."""

    name = "pqai"

    def __init__(self, http: ProviderHttpClient, *, base_url: str, token: str | None) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._token = token

    async def search(self, query: QueryVariant, limit: int) -> list[PatentStub]:
        """Run a /search/102/ query and map results into normalized stubs."""
        if not self._token:
            raise ProviderError(self.name, "PQAI token is not configured (PQAI_TOKEN)")
        payload = await self._http.get_json(
            f"{self._base_url}/search/102/",
            params={"q": query.text, "n": limit, "type": "patent", "token": self._token},
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise ProviderError(self.name, "unexpected response shape: no 'results' list")
        stubs = [stub for stub in (self._to_stub(item) for item in results) if stub is not None]
        logger.info(
            "pqai: query returned %d usable stubs of %d results",
            len(stubs),
            len(results),
        )
        return stubs

    async def healthcheck(self) -> bool:
        """The docs route needs no token; reaching it proves the service is up."""
        try:
            return bool(await self._http.get_text(f"{self._base_url}/docs"))
        except ProviderError:
            return False

    def _to_stub(self, item: Any) -> PatentStub | None:
        if not isinstance(item, dict):
            return None
        document = item["patent"] if isinstance(item.get("patent"), dict) else item
        raw_id = next((document.get(field) for field in _ID_FIELDS if document.get(field)), None)
        if not isinstance(raw_id, str):
            logger.debug("pqai: skipping result without a recognizable id: %r", document)
            return None
        try:
            patent_id = normalize_patent_id(raw_id)
        except ValueError:
            logger.debug("pqai: skipping result with unparseable id %r", raw_id)
            return None
        abstract = document.get("abstract")
        raw_date = next((document.get(f) for f in _DATE_FIELDS if document.get(f)), None)
        cpc_bag = document.get("cpc")
        cpc = [str(code) for code in cpc_bag] if isinstance(cpc_bag, list) else []
        score = document.get("score", item.get("score"))
        numeric_score = float(score) if isinstance(score, int | float) else None
        return PatentStub(
            patent_id=patent_id,
            title=str(document.get("title") or "Untitled"),
            abstract=str(abstract) if abstract else None,
            publication_date=str(raw_date) if raw_date else None,
            cpc=cpc,
            source=self.name,
            provider_score=numeric_score,
        )

    async def aclose(self) -> None:
        await self._http.aclose()
