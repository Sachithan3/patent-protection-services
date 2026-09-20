"""Unit tests for patent ID normalization (spec section 16.1: 15+ formats)."""

import pytest

from app.providers.ids import dedupe_key, normalize_patent_id

NORMALIZE_CASES = [
    ("US10123456B2", "US10123456B2"),
    ("US 10,123,456 B2", "US10123456B2"),
    ("US-10123456-B2", "US10123456B2"),
    ("US10123456 B2", "US10123456B2"),
    ("US10123456", "US10123456"),
    ("US 10123456", "US10123456"),
    ("US 10,123,456", "US10123456"),
    ("us10123456b2", "US10123456B2"),
    ("US-2021012345-A1", "US2021012345A1"),
    ("US2021012345A1", "US2021012345A1"),
    ("US-2021-0123456-A1", "US20210123456A1"),
    ("EP3456789B1", "EP3456789B1"),
    ("EP 3 456 789 B1", "EP3456789B1"),
    ("WO2021/123456A1", "WO2021123456A1"),
    ("WO 2021/123456 A1", "WO2021123456A1"),
    ("JP2021-123456A", "JP2021123456A"),
    ("CN110123456A", "CN110123456A"),
]

REJECT_CASES = [
    "123456",  # no country code
    "AB-XYZ",  # no numeric portion
    "U1 123456",  # country code must be letters
    "US-D123456-S",  # design prefixes are an explicit known limitation
    "patent US10123456",  # prose, not an id
    "",
    "   ",
]


@pytest.mark.parametrize(("raw", "expected"), NORMALIZE_CASES)
def test_normalize_accepts_real_world_formats(raw: str, expected: str) -> None:
    assert normalize_patent_id(raw) == expected


@pytest.mark.parametrize("raw", REJECT_CASES)
def test_normalize_rejects_unrecognized_formats(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_patent_id(raw)


def test_dedupe_key_collapses_kind_codes_and_punctuation() -> None:
    assert dedupe_key("US10123456B2") == "US10123456"
    assert dedupe_key("US10123456A1") == "US10123456"
    assert dedupe_key("US 10,123,456 B2") == "US10123456"


def test_dedupe_key_raises_on_unrecognized_id() -> None:
    with pytest.raises(ValueError):
        dedupe_key("not-a-patent")
