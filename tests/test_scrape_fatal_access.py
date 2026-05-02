"""Fatal-access classification for scrape jobs."""

from youtube_scrape.application.scrape_fatal_access import (
    format_fatal_watch_access_message,
    is_fatal_watch_access_failure,
)
from youtube_scrape.exceptions import ExtractionError, NavigationError


def test_detects_watch_page_navigation_failure() -> None:
    exc = NavigationError(
        "Failed to load watch page after retries: https://www.youtube.com/watch?v=x",
        details="timeout",
    )
    assert is_fatal_watch_access_failure(exc) is True
    msg = format_fatal_watch_access_message(exc)
    assert msg is not None
    assert "Underlying error:" in msg
    assert "aborted" in msg.lower()


def test_detects_player_response_extraction() -> None:
    exc = ExtractionError("Could not locate ytInitialPlayerResponse", details="parse")
    assert is_fatal_watch_access_failure(exc) is True
    assert format_fatal_watch_access_message(exc) is not None


def test_detects_ytdlp_bot_phrasing() -> None:
    exc = RuntimeError("Sign in to confirm you're not a bot.")
    assert is_fatal_watch_access_failure(exc) is True


def test_non_matching_errors_not_fatal() -> None:
    exc = ValueError("Unexpected parse at line 3")
    assert is_fatal_watch_access_failure(exc) is False
    assert format_fatal_watch_access_message(exc) is None
