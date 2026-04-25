"""Ports (interfaces) for infrastructure adapters [DI]."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class Clock(Protocol):
    """Monotonic time source for backoff and deadlines."""

    def monotonic(self) -> float:
        """Return monotonic seconds suitable for measuring intervals."""
        ...


class FileSink(Protocol):
    """Filesystem writes for outputs and downloads."""

    def write_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        """Write UTF-8 text, creating parent directories as needed."""
        ...

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Write binary payload, creating parent directories as needed."""
        ...


class HttpClient(Protocol):
    """HTTP transport for Innertube, captions, thumbnails, and media segments."""

    async def get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        """GET returning decoded text."""
        ...

    async def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        """GET returning raw bytes (optionally truncated for large media smoke tests)."""
        ...

    async def post_json(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST JSON and parse JSON response."""
        ...


class BrowserSession(Protocol):
    """Camoufox-backed browser for extracting embedded JSON from watch pages."""

    async def fetch_text_in_watch_context(self, watch_url: str, resource_url: str) -> str:
        """GET ``resource_url`` after loading ``watch_url`` using the browser request context (cookies)."""
        ...

    async def extract_watch_payload(
        self,
        watch_url: str,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Navigate to ``watch_url`` and return ``(player_response, yt_initial_data, html)``.

        ``player_response`` is the parsed ``ytInitialPlayerResponse`` object.
        ``yt_initial_data`` may be an empty dict if the marker is absent.

        Raises:
            NavigationError: when navigation or extraction fails after retries.
        """
        ...
