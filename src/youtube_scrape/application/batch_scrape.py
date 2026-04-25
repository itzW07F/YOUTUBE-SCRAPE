"""Batch processing with optional circuit breaker."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from youtube_scrape.domain.ports import FileSink
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)


class BatchRunner:
    """Run async jobs for many URLs with consecutive-failure circuit breaking."""

    def __init__(self, *, settings: Settings, files: FileSink) -> None:
        self._settings = settings
        self._files = files

    async def run(
        self,
        urls: list[str],
        *,
        handler: Callable[[str], Awaitable[dict[str, Any]]],
        fail_fast: bool,
    ) -> list[dict[str, Any]]:
        """Execute ``handler`` for each URL and return result rows."""
        rows: list[dict[str, Any]] = []
        consecutive_failures = 0
        for raw in urls:
            url = raw.strip()
            if not url or url.startswith("#"):
                continue
            try:
                row = await handler(url)
                rows.append({"url": url, "ok": True, **row})
                consecutive_failures = 0
            except Exception as exc:  # noqa: BLE001 - batch captures all failures explicitly
                log.exception("batch_item_failed", extra={"url": url})
                rows.append({"url": url, "ok": False, "error": str(exc)})
                consecutive_failures += 1
                if fail_fast:
                    break
                if consecutive_failures >= self._settings.batch_max_failures_before_breaker:
                    log.error(
                        "batch_circuit_breaker_open",
                        extra={"failures": consecutive_failures},
                    )
                    break
        return rows

    def write_report(self, path: Path, rows: list[dict[str, Any]]) -> None:
        """Persist a JSON report for batch runs."""
        self._files.write_text(path, json.dumps(rows, indent=2, ensure_ascii=False) + "\n")
