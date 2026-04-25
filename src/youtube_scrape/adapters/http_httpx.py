"""httpx-backed HTTP client with retries and jittered backoff."""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx

from youtube_scrape.adapters.clock import MonotonicClock
from youtube_scrape.domain.ports import Clock
from youtube_scrape.exceptions import HttpTransportError

log = logging.getLogger(__name__)


class HttpxHttpClient:
    """Async HTTP client implementing :class:`HttpClient`."""

    def __init__(
        self,
        *,
        timeout_s: float,
        max_retries: int,
        clock: Clock | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(timeout_s)
        self._max_retries = max_retries
        self._clock = clock or MonotonicClock()
        self._client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _sleep_backoff(self, attempt: int) -> None:
        base = 0.35 * (2**attempt)
        jitter = random.uniform(0, 0.2)
        await asyncio.sleep(base + jitter)

    async def get_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("http_get_failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt + 1 == self._max_retries:
                    break
                await self._sleep_backoff(attempt)
        msg = f"GET failed after retries: {url}"
        raise HttpTransportError(msg, details=str(last_exc))

    async def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                if max_bytes is None:
                    resp = await self._client.get(url, headers=headers)
                    resp.raise_for_status()
                    return resp.content
                async with self._client.stream("GET", url, headers=headers) as resp:
                    resp.raise_for_status()
                    parts: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        if not chunk:
                            continue
                        remain = max_bytes - total
                        if remain <= 0:
                            break
                        parts.append(chunk if len(chunk) <= remain else chunk[:remain])
                        total += len(parts[-1])
                        if total >= max_bytes:
                            break
                    return b"".join(parts)
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("http_get_bytes_failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt + 1 == self._max_retries:
                    break
                await self._sleep_backoff(attempt)
        msg = f"GET bytes failed after retries: {url}"
        raise HttpTransportError(msg, details=str(last_exc))

    async def stream_get_to_file(
        self,
        url: str,
        path: Path,
        *,
        headers: dict[str, str] | None = None,
    ) -> int:
        """Stream a full GET body to ``path`` (atomic replace). Returns bytes written."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".httpxtmp")
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                tmp.unlink(missing_ok=True)
                total = 0
                async with self._client.stream("GET", url, headers=headers) as resp:
                    resp.raise_for_status()
                    with tmp.open("wb") as f:
                        async for chunk in resp.aiter_bytes():
                            if not chunk:
                                continue
                            f.write(chunk)
                            total += len(chunk)
                tmp.replace(path)
                return total
            except httpx.HTTPError as exc:
                last_exc = exc
                tmp.unlink(missing_ok=True)
                with suppress(OSError):
                    path.unlink(missing_ok=True)
                log.warning(
                    "http_stream_get_failed",
                    extra={"url": url, "attempt": attempt, "error": str(exc)},
                )
                if attempt + 1 == self._max_retries:
                    break
                await self._sleep_backoff(attempt)
        msg = f"GET stream failed after retries: {url}"
        raise HttpTransportError(msg, details=str(last_exc))

    async def post_json(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post(url, json=json_body, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict):
                    msg = "POST JSON response was not an object"
                    raise HttpTransportError(msg, details=url)
                return data
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning("http_post_failed", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt + 1 == self._max_retries:
                    break
                await self._sleep_backoff(attempt)
        msg = f"POST failed after retries: {url}"
        raise HttpTransportError(msg, details=str(last_exc))
