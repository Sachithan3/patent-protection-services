"""SSRF guard for the page-fetching fallback (spec section 14.3).

The LLM never supplies URLs and the page fetcher builds them from normalized patent
ids only; this module still hardens the one place fetches happen: https-only, an
explicit host allowlist, and refusal to talk to private/reserved IP ranges.

Only pure checks live here (unit-testable without network). DNS resolution and
response-size/time caps are enforced by the adapter that uses these helpers.

The IP denylist is explicit rather than trusting `ipaddress.is_private/is_global`:
their values for some ranges changed across CPython releases (CVE-2024-4032), and a
fetch-guard must not drift with the stdlib version on the deploy box.
"""

import ipaddress
from urllib.parse import urlparse

DEFAULT_ALLOWED_HOSTS = frozenset({"patents.google.com"})

_DENIED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        # IPv4: unspecified, private, shared, loopback, link-local (cloud metadata),
        # IETF/docs/benchmark ranges, multicast, reserved, broadcast.
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        # IPv6: unspecified, loopback, documentation, unique-local, link-local, multicast.
        "::/128",
        "::1/128",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
        "ff00::/8",
    )
)


class DisallowedUrlError(ValueError):
    """Raised when a URL fails the SSRF checks."""


def _unwrap_mapped(address: ipaddress.IPv4Address | ipaddress.IPv6Address
                  ) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Collapse IPv4-mapped IPv6 addresses so '::ffff:10.0.0.1' is judged as '10.0.0.1'."""
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_allowed_ip(ip_text: str) -> bool:
    """True only for public unicast addresses outside every denied range."""
    address = _unwrap_mapped(ipaddress.ip_address(ip_text))
    return not any(address in network for network in _DENIED_NETWORKS)


def validate_page_url(
    url: str,
    *,
    allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
) -> str:
    """Validate a page URL for fetching and return it unchanged.

    Raises DisallowedUrlError for non-https schemes, embedded credentials, or
    hosts outside the allowlist. Redirect targets must be re-validated by the
    fetcher (httpx should be configured with redirects disabled).
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise DisallowedUrlError("only https URLs are allowed")
    if parsed.username or parsed.password:
        raise DisallowedUrlError("URLs with embedded credentials are not allowed")
    if parsed.hostname not in allowed_hosts:
        raise DisallowedUrlError(f"host is not allowlisted: {parsed.hostname!r}")
    return url
