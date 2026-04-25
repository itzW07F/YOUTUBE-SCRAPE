import pytest

from youtube_scrape.domain.youtube_url import parse_video_id, watch_url
from youtube_scrape.exceptions import ExtractionError


def test_parse_raw_id() -> None:
    assert parse_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_watch_url() -> None:
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_shorts_url() -> None:
    assert parse_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_watch_url() -> None:
    assert watch_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_invalid() -> None:
    with pytest.raises(ExtractionError):
        parse_video_id("not-a-url")
