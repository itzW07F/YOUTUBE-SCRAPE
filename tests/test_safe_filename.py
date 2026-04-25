"""Tests for ``safe_video_filename``."""

from __future__ import annotations

from youtube_scrape.domain.safe_filename import safe_video_filename


def test_strips_illegal_chars() -> None:
    assert safe_video_filename('Foo / Bar: "x"') == "Foo Bar x.mp4"


def test_empty_title_uses_default() -> None:
    assert safe_video_filename("") == "video.mp4"
    assert safe_video_filename("   ") == "video.mp4"


def test_truncates_long_title() -> None:
    long = "a" * 300
    out = safe_video_filename(long, max_stem_chars=50)
    assert out == "a" * 50 + ".mp4"
