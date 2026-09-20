"""Patent ID normalization and dedupe keys (spec section 7.4).

Providers disagree on formats (`US 10,123,456 B2`, `US10123456`, `US-2021012345-A1`).
Normalize once at the provider edge; everything downstream sees canonical IDs.

Known limitation: the grammar does not cover design (D), plant (PP), or reissue (RE)
number prefixes; those raise ValueError like any unrecognized format. Extend `_parse`
deliberately, with tests, if a provider starts returning them.
"""

import re
from typing import NamedTuple

_ID_PATTERN = re.compile(
    r"^(?P<cc>[A-Z]{2})[\s\-]*(?P<num>[\d,/\s\-]+?)[\s\-]*(?P<kind>[A-Z]\d?)?$"
)


class _ParsedId(NamedTuple):
    country_code: str
    number: str
    kind: str


def _parse(raw: str) -> _ParsedId:
    """Parse a raw patent id, raising ValueError for anything unrecognized."""
    match = _ID_PATTERN.match(raw.strip().upper())
    if match is None:
        raise ValueError(f"Unrecognized patent id: {raw!r}")
    number = re.sub(r"\D", "", match["num"])
    if not number:
        raise ValueError(f"Patent id has no numeric portion: {raw!r}")
    return _ParsedId(match["cc"], number, match["kind"] or "")


def normalize_patent_id(raw: str) -> str:
    """Return the canonical form, e.g. 'US 10,123,456 B2' -> 'US10123456B2'."""
    parsed = _parse(raw)
    return f"{parsed.country_code}{parsed.number}{parsed.kind}"


def dedupe_key(patent_id: str) -> str:
    """Country code + number with kind codes stripped.

    B1/B2 and A1 publications of the same number collapse so the top-50 pool is not
    five copies of one invention. Family-level collapse (where a provider exposes
    family ids) is a registry concern and lands with the adapters.
    """
    parsed = _parse(patent_id)
    return f"{parsed.country_code}{parsed.number}"
