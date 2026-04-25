import pytest

from youtube_scrape.domain.json_extract import (
    extract_yt_initial_data,
    extract_yt_initial_player_response,
)
from youtube_scrape.exceptions import ExtractionError


def test_extract_player_response_var_marker() -> None:
    html = '<html><script>var ytInitialPlayerResponse = {"videoDetails": {"videoId": "abc"}};</script></html>'
    data = extract_yt_initial_player_response(html)
    assert data["videoDetails"]["videoId"] == "abc"


def test_extract_initial_data() -> None:
    html = '<html><script>var ytInitialData = {"foo": 1};</script></html>'
    data = extract_yt_initial_data(html)
    assert data["foo"] == 1


def test_missing_player_raises() -> None:
    with pytest.raises(ExtractionError):
        extract_yt_initial_player_response("<html></html>")
