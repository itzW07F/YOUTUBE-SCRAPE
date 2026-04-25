"""Domain-specific failures for scrape operations."""


class YouTubeScrapeError(Exception):
    """Base error for all scrape failures."""

    def __init__(self, message: str, *, details: str | None = None) -> None:
        super().__init__(message)
        self.details = details


class ExtractionError(YouTubeScrapeError):
    """Raised when embedded page data cannot be read or parsed."""

    pass


class NavigationError(YouTubeScrapeError):
    """Raised when the browser cannot load the target page."""

    pass


class HttpTransportError(YouTubeScrapeError):
    """Raised when an HTTP call fails after retries."""

    pass


class ContinuationError(YouTubeScrapeError):
    """Raised when comment continuation tokens are missing or invalid."""

    pass


class UnsupportedFormatError(YouTubeScrapeError):
    """Raised when the selected stream requires unsupported cipher handling."""

    pass
