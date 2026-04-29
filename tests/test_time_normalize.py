from datetime import UTC, datetime

from youtube_scrape.domain.time_normalize import parse_published_text_to_utc


def test_parse_relative_time_to_utc() -> None:
    now_utc = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    parsed = parse_published_text_to_utc("10 minutes ago", now_utc=now_utc)
    assert parsed == datetime(2026, 1, 2, 11, 50, tzinfo=UTC)


def test_parse_absolute_date_to_utc() -> None:
    parsed = parse_published_text_to_utc("Feb 1, 2026")
    assert parsed == datetime(2026, 2, 1, 0, 0, tzinfo=UTC)


def test_parse_invalid_value_returns_none() -> None:
    assert parse_published_text_to_utc("sometime recently maybe") is None
