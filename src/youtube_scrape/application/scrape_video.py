"""Application service: video metadata + thumbnails list."""

from __future__ import annotations

import logging
from typing import Any

from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.domain.player_parser import (
    parse_caption_tracks,
    parse_stream_formats,
    parse_video_metadata,
)
from youtube_scrape.domain.ports import BrowserSession
from youtube_scrape.domain.youtube_url import watch_url
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)


class ScrapeVideoService:
    """Load the watch page and return structured metadata."""

    def __init__(self, *, browser: BrowserSession, settings: Settings) -> None:
        self._browser = browser
        self._settings = settings

    async def scrape(self, url_or_id: str) -> ResultEnvelope:
        """Return a ``ResultEnvelope`` of kind ``video``."""
        url = watch_url(url_or_id)
        log.info("scrape_video_start", extra={"url": url})
        player, _initial, _html = await self._browser.extract_watch_payload(url)
        meta = parse_video_metadata(player)
        captions = parse_caption_tracks(player)
        streams = parse_stream_formats(player)
        payload: dict[str, Any] = {
            "metadata": meta.model_dump(mode="json"),
            "caption_tracks": [c.model_dump(mode="json") for c in captions],
            "stream_formats_preview": streams[:20],
            "stream_formats_total": len(streams),
        }
        return make_envelope(settings=self._settings, kind="video", data=payload)
