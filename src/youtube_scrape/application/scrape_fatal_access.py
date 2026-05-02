"""Classify errors where YouTube denies the normal watch page (fail-fast for scrape jobs)."""

from __future__ import annotations

from youtube_scrape.exceptions import YouTubeScrapeError

# Lowercase substrings: anonymous clients rarely recover without cookies / sign-in.
_FATAL_ACCESS_MARKERS: tuple[str, ...] = (
    "failed to load watch page after retries",
    "ytinitialplayerresponse",
    "sign in to confirm",
    "not a bot",
    "age-restricted",
    "age restricted",
    "confirm your age",
    "inappropriate for some users",
    "login required",
    "this video is private",
    "video is private",
    "video is unavailable",
)


def is_fatal_watch_access_failure(exc: BaseException) -> bool:
    """Return True when later browser-backed scrape steps are very unlikely to succeed."""
    parts: list[str] = [str(exc)]
    if isinstance(exc, YouTubeScrapeError) and exc.details:
        parts.append(str(exc.details))
    blob = " ".join(parts).lower()
    return any(marker in blob for marker in _FATAL_ACCESS_MARKERS)


def format_fatal_watch_access_message(exc: BaseException) -> str | None:
    """Return a single log/job message to use when aborting the rest of the pipeline, or None."""
    if not is_fatal_watch_access_failure(exc):
        return None
    return (
        "Scrape aborted: YouTube did not serve a normal watch experience for this URL "
        "(often age-restricted or sign-in/bot verification). Remaining steps were not run. "
        f"Underlying error: {exc}"
    )
