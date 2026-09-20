"""Unit tests for the SSRF guard: URL validation and IP range checks."""

import pytest

from app.core.ssrf import DisallowedUrlError, is_allowed_ip, validate_page_url

ALLOWED_IPS = ["8.8.8.8", "1.1.1.1", "172.32.0.1", "2606:4700::1111"]

BLOCKED_IPS = [
    "127.0.0.1",  # loopback
    "10.0.0.1",  # RFC1918
    "172.16.0.1",  # RFC1918
    "192.168.1.1",  # RFC1918
    "169.254.169.254",  # link-local: cloud metadata, the #1 SSRF target
    "0.0.0.0",  # unspecified
    "100.64.0.1",  # shared address space (CGNAT)
    "198.18.0.5",  # benchmarking range
    "224.0.0.1",  # multicast
    "240.0.0.1",  # reserved
    "255.255.255.255",  # broadcast
    "::1",  # IPv6 loopback
    "::",  # IPv6 unspecified
    "fc00::1",  # unique-local
    "fe80::1",  # link-local
    "2001:db8::1",  # documentation range
    "::ffff:10.0.0.1",  # IPv4-mapped private address
    "::ffff:169.254.169.254",  # IPv4-mapped cloud metadata
]


@pytest.mark.parametrize("ip", ALLOWED_IPS)
def test_public_ips_are_allowed(ip: str) -> None:
    assert is_allowed_ip(ip) is True


@pytest.mark.parametrize("ip", BLOCKED_IPS)
def test_private_and_reserved_ips_are_blocked(ip: str) -> None:
    assert is_allowed_ip(ip) is False


def test_https_url_on_allowlisted_host_passes() -> None:
    url = "https://patents.google.com/patent/US10123456B2/en"
    assert validate_page_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://patents.google.com/patent/US10123456B2/en",  # not https
        "https://evil.example.com/patent/US10123456B2/en",  # host not allowlisted
        "https://patents.google.com.evil.com/patent/x",  # suffix trick: hostname differs
        "https://user:pass@patents.google.com/patent/x",  # embedded credentials
        "ftp://patents.google.com/patent/x",  # wrong scheme
    ],
)
def test_rejects_urls_outside_policy(url: str) -> None:
    with pytest.raises(DisallowedUrlError):
        validate_page_url(url)


def test_hostname_must_match_exactly_not_by_suffix() -> None:
    with pytest.raises(DisallowedUrlError):
        validate_page_url("https://notpatents.google.com/patent/x")
