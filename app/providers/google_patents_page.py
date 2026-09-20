"""Google Patents page adapter: claims fallback only (spec sections 7.2, 14.3).

The LLM never supplies URLs and this fetcher builds them from normalized patent
ids only: ``https://patents.google.com/patent/<ID>/en``. Every fetch enforces the
SSRF guard in ``app/core/ssrf.py``: https-only allowlisted host, DNS resolution
whose IPs must all pass ``is_allowed_ip`` (blocks cloud-metadata and mapped-IPv6
tricks), no redirect following (httpx default), ~2 MB response cap, and a real
``User-Agent`` from settings.

Claim selectors are brittle by nature, so they live as module constants with a
documented expected structure. Anything unrecognized returns None (drop-not-guess,
spec 11.1) rather than letting the LLM see guessed text.
"""

import asyncio
import logging
import re
import socket
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from html.parser import HTMLParser

from app.core.ssrf import is_allowed_ip, validate_page_url
from app.models.patents import Claim, PatentClaims
from app.providers.base import ProviderError
from app.providers.http import ProviderHttpClient
from app.providers.ids import normalize_patent_id

logger = logging.getLogger(__name__)

# Expected Google Patents claim markup (provisional — re-confirm against live HTML
# once a real page is fetched; see docs/PROVIDERS.md). The parser keys on the
# claims section first, then on per-claim text blocks inside it.
CLAIMS_SECTION_MARKER = "claims"
CLAIM_TEXT_CLASS_MARKER = "claim-text"
CLAIM_NUM_CLASS_MARKER = "claim-number"

MAX_PAGE_CHARS = 2_000_000

_DEPENDENT_RE = re.compile(
    r"\b(of|according to|as claimed in|as in|of in)\s+claim\s+\d+"
    r"|\bclaim\s+\d+",
    re.IGNORECASE,
)

Resolver = Callable[[str], Awaitable[list[str]]]


async def _default_resolver(host: str) -> list[str]:
    """Resolve a hostname to IP strings without blocking the event loop."""
    infos = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


class _ClaimSectionParser(HTMLParser):
    """Collect per-claim text blocks inside the claims section of the page."""

    def __init__(self) -> None:
        super().__init__()
        self._section_depth = 0
        self._text_depth = 0
        self._current: list[str] = []
        self.claims: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        bag = {k: (v or "") for k, v in attrs}
        if self._section_depth == 0:
            if CLAIMS_SECTION_MARKER in bag.get("itemprop", "").lower():
                self._section_depth = 1
            return
        self._section_depth += 1
        classes = bag.get("class", "").lower()
        if CLAIM_TEXT_CLASS_MARKER in classes and self._text_depth == 0:
            self._text_depth = self._section_depth
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if self._section_depth == 0:
            return
        if self._text_depth and self._section_depth == self._text_depth:
            text = "".join(self._current).strip()
            if text:
                self.claims.append(text)
            self._current = []
            self._text_depth = 0
        self._section_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._text_depth:
            self._current.append(data)


def parse_claims_html(page_html: str) -> list[str] | None:
    """Extract ordered claim texts from a Google Patents page, or None.

    Returns None when the claims section or its claim blocks are absent, so the
    caller can fall through (drop-not-guess) instead of fabricating claims.
    """
    parser = _ClaimSectionParser()
    try:
        parser.feed(page_html)
    except Exception:  # noqa: BLE001 - malformed HTML must not break a job
        logger.debug("google_patents_page: HTML parse failed; treating as no claims")
        return None
    return parser.claims or None


def is_independent_claim(text: str) -> bool:
    """A claim is dependent when its text references another claim number."""
    return _DEPENDENT_RE.search(text) is None


class GooglePatentsPageProvider:
    """Claims-only fallback that scrapes one patent page per id (throttled hard)."""

    name = "google_patents_page"

    def __init__(
        self,
        http: ProviderHttpClient,
        *,
        base_url: str,
        user_agent: str,
        resolver: Resolver | None = None,
    ) -> None:
        self._http = http
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._resolver = resolver or _default_resolver

    def page_url(self, patent_id: str) -> str:
        """Build and SSRF-validate the page URL for a normalized patent id."""
        normalized = normalize_patent_id(patent_id)
        return validate_page_url(f"{self._base_url}/patent/{normalized}/en")

    async def get_claims(self, patent_id: str) -> PatentClaims | None:
        """Fetch the page and return parsed claims, or None when unavailable."""
        try:
            url = self.page_url(patent_id)
        except ValueError:
            logger.debug("google_patents_page: unparseable id %r; no claims", patent_id)
            return None
        await self._check_dns(url)
        try:
            page = await self._http.get_text(url, headers={"User-Agent": self._user_agent})
        except ProviderError:
            raise
        except Exception as error:  # noqa: BLE001 - never let scraping break a job
            raise ProviderError(self.name, f"page fetch failed: {error}") from error
        if len(page) > MAX_PAGE_CHARS:
            raise ProviderError(self.name, "page exceeds size cap; refusing to parse")
        texts = parse_claims_html(page)
        if not texts:
            logger.info("google_patents_page: no claims section for %s", patent_id)
            return None
        normalized = normalize_patent_id(patent_id)
        return PatentClaims(
            patent_id=normalized,
            claims=[
                Claim(number=n, text=text, is_independent=is_independent_claim(text))
                for n, text in enumerate(texts, start=1)
            ],
            source=self.name,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _check_dns(self, url: str) -> None:
        """Resolve the page host and refuse private/reserved IPs (SSRF guard)."""
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        try:
            ips = await self._resolver(host)
        except Exception as error:
            raise ProviderError(self.name, f"DNS resolution failed for {host!r}") from error
        if not ips:
            raise ProviderError(self.name, f"DNS returned no addresses for {host!r}")
        for ip in ips:
            try:
                allowed = is_allowed_ip(ip)
            except ValueError:
                allowed = False
            if not allowed:
                raise ProviderError(self.name, f"resolved IP is not allowed: {ip!r}")

    async def aclose(self) -> None:
        await self._http.aclose()
