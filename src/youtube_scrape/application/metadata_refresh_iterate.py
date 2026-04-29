"""Sequential gallery metadata refresh: single browser session, yield each folder."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import NamedTuple

from youtube_scrape.adapters.browser_playwright import CamoufoxBrowserSession
from youtube_scrape.application.gallery_metadata_refresh import (
    append_metadata_history_jsonl,
    output_roots_from_env,
    resolve_output_dir_for_refresh,
    utc_now_iso_z,
)
from youtube_scrape.application.scrape_video import ScrapeVideoService
from youtube_scrape.settings import Settings

logger = logging.getLogger(__name__)


class MetadataRefreshItemResult(NamedTuple):
    """Outcome for one output folder."""

    output_dir: str
    ok: bool
    error: str | None = None


async def iterate_metadata_refresh(
    pairs: Sequence[tuple[str, str]],
) -> AsyncIterator[tuple[int, MetadataRefreshItemResult]]:
    """Re-scrape each ``(output_dir_str, watch_url)`` pair; yields ``(index, result)`` per folder."""
    roots = output_roots_from_env()
    settings = Settings()
    browser = CamoufoxBrowserSession(settings)

    try:
        service = ScrapeVideoService(browser=browser, settings=settings)
        for index, (out_str, url) in enumerate(pairs):
            try:
                out = resolve_output_dir_for_refresh(out_str, roots)
            except ValueError as exc:
                logger.warning("metadata_refresh_path_rejected %s: %s", out_str, exc)
                yield index, MetadataRefreshItemResult(output_dir=out_str, ok=False, error=str(exc))
                continue
            try:
                logger.info("metadata_refresh_scrape_start output=%s url=%s", out, url)
                envelope = await service.scrape(url)
                (out / "video.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                meta = envelope.data.get("metadata") if isinstance(envelope.data, dict) else {}
                meta_dict: dict = meta if isinstance(meta, dict) else {}
                vid = str(meta_dict.get("video_id") or "")
                append_metadata_history_jsonl(
                    out,
                    captured_at_iso_z=utc_now_iso_z(),
                    video_id=vid,
                    metadata=meta_dict,
                )
                logger.info("metadata_refresh_ok output=%s", out_str)
                yield index, MetadataRefreshItemResult(output_dir=out_str, ok=True, error=None)
            except Exception as exc:
                logger.exception("metadata refresh failed for %s", out_str)
                yield index, MetadataRefreshItemResult(output_dir=out_str, ok=False, error=str(exc))
    finally:
        await browser.aclose()
