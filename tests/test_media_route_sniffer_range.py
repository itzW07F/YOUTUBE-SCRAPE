"""Unit tests for route-sniffer Content-Range merge (no browser)."""

from __future__ import annotations

from youtube_scrape.adapters.browser_playwright import (
    MediaRouteSnifferState,
    _parse_content_range_header,
)


def test_parse_content_range_206() -> None:
    s, e, t = _parse_content_range_header("bytes 0-4/10", 5, status=206)
    assert (s, e, t) == (0, 4, 10)


def test_parse_content_range_200_no_header() -> None:
    s, e, t = _parse_content_range_header(None, 100, status=200)
    assert (s, e, t) == (0, 99, 100)


def test_parse_content_range_star_total_only() -> None:
    s, e, t = _parse_content_range_header("bytes */1000", 1, status=206)
    assert s == 0 and e == -1 and t == 1000


def test_merge_contiguous_ranges() -> None:
    st = MediaRouteSnifferState()
    st.add_range_part(0, 1, b"ab", 4)
    st.add_range_part(2, 3, b"cd", None)
    assert st.range_total == 4
    assert st.try_merge_byte_range_assembly() == b"abcd"


def test_merge_incomplete_returns_none() -> None:
    st = MediaRouteSnifferState()
    st.add_range_part(0, 1, b"ab", 4)
    assert st.try_merge_byte_range_assembly() is None
