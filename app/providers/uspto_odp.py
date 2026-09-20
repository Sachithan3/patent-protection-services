"""USPTO Open Data Portal adapter: bibliographic search; no claim text (docs/PROVIDERS.md).

ODP serves application metadata and file-wrapper data with Lucene query syntax and an
`X-API-KEY` header. It does NOT serve parsed claim text, so `get_claims` returns None by
design: the registry falls through to the next claims source (Google Patents page).

Known dedupe quirk: grant numbers and application numbers are different identifier
spaces; until family-level collapse lands (registry concern), the same invention can
appear once per identifier kind.
"""

import logging
from typing import Any

from app.models.patents import PatentClaims, PatentStub
from app.models.plan import QueryVariant
from app.providers.base import ProviderError
from app.providers.http import ProviderHttpClient
from app.providers.ids import normalize_patent_id

logger = logging.getLogger(__name__)

_RECORD_BAG_KEYS = ("patentFileWrapperDataBag", "patentBag", "results")


class UsptoOdpProvider:
    """Search (and notional claims) adapter for api.uspto.gov."""

    name = "uspto_odp"

    def __init__(self, http: ProviderHttpClient, *, base_url: str, api_key: str | None) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def search(self, query: QueryVariant, limit: int) -> list[PatentStub]:
        """Search application records; results carry metadata but no abstracts."""
        if not self._api_key:
            raise ProviderError(self.name, "USPTO API key is not configured (USPTO_API_KEY)")
        payload = await self._http.get_json(
            f"{self._base_url}/api/v1/patent/applications/search",
            params={"q": query.text, "limit": limit, "offset": 0},
            headers=self._headers(),
        )
        records = next(
            (b for b in (payload.get(k) for k in _RECORD_BAG_KEYS) if isinstance(b, list)),
            None,
        )
        if records is None:
            raise ProviderError(self.name, "unexpected response shape: no record bag")
        stubs = [s for s in (self._to_stub(r) for r in records) if s is not None]
        logger.info(
            "uspto_odp: %d usable stubs of %d records", len(stubs), len(records)
        )
        return stubs

    async def get_claims(self, patent_id: str) -> PatentClaims | None:
        """ODP has no claim text; returning None lets the registry fall through."""
        logger.info("uspto_odp: no claim text served by ODP; falling through for %s", patent_id)
        return None

    async def healthcheck(self) -> bool:
        """A minimal authenticated search proves key validity and service uptime."""
        if not self._api_key:
            return False
        try:
            await self._http.get_json(
                f"{self._base_url}/api/v1/patent/applications/search",
                params={"q": "a", "limit": 1},
                headers=self._headers(),
            )
            return True
        except ProviderError:
            return False

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self._api_key or ""}

    def _to_stub(self, record: Any) -> PatentStub | None:
        if not isinstance(record, dict):
            return None
        meta = record.get("applicationMetaData")
        if not isinstance(meta, dict):
            meta = {}
        raw_id = meta.get("patentNumber") or record.get("applicationNumberText")
        if not isinstance(raw_id, str) or not raw_id:
            logger.debug("uspto_odp: skipping record without an id: %r", record)
            return None
        candidate = raw_id if any(c.isalpha() for c in raw_id) else f"US{raw_id}"
        try:
            patent_id = normalize_patent_id(candidate)
        except ValueError:
            logger.debug("uspto_odp: skipping record with unparseable id %r", raw_id)
            return None
        return PatentStub(
            patent_id=patent_id,
            title=self._extract_title(record, meta),
            abstract=None,  # ODP bibliographic data carries no abstract text
            assignee=_first_str(meta, ("firstApplicantName", "applicantName")),
            publication_date=_first_str(meta, ("grantDate", "filingDate")),
            cpc=[],
            source=self.name,
            provider_score=None,
        )

    def _extract_title(self, record: dict[str, Any], meta: dict[str, Any]) -> str:
        direct = _first_str(record, ("inventionTitle", "title")) or _first_str(
            meta, ("inventionTitle",)
        )
        if direct:
            return direct
        title_bag = meta.get("inventionTitleBag")
        if isinstance(title_bag, list) and title_bag:
            first = title_bag[0]
            if isinstance(first, dict) and first.get("inventionTitleText"):
                return str(first["inventionTitleText"])
        return "Untitled"

    async def aclose(self) -> None:
        await self._http.aclose()


def _first_str(source: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if value:
            return str(value)
    return None
