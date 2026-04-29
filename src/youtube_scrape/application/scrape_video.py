"""Application service: video metadata + thumbnails list."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.domain.models import ResultEnvelope, VideoMetadata
from youtube_scrape.domain.player_parser import (
    parse_caption_tracks,
    parse_stream_formats,
    parse_video_metadata,
)
from youtube_scrape.domain.ports import BrowserSession
from youtube_scrape.domain.return_youtube_dislike_fetch import fetch_ryd_vote_counts
from youtube_scrape.domain.watch_initial_extract import enrich_video_metadata_from_initial
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
        player, initial, _html = await self._browser.extract_watch_payload(url)
        meta = parse_video_metadata(player)
        meta = enrich_video_metadata_from_initial(meta, initial, now_utc=datetime.now(UTC))
        meta = await self._maybe_enrich_from_return_youtube_dislike(meta)
        captions = parse_caption_tracks(player)
        streams = parse_stream_formats(player)
        payload: dict[str, Any] = {
            "metadata": meta.model_dump(mode="json"),
            "caption_tracks": [c.model_dump(mode="json") for c in captions],
            "stream_formats_preview": streams[:20],
            "stream_formats_total": len(streams),
        }
        return make_envelope(settings=self._settings, kind="video", data=payload)

    async def _maybe_enrich_from_return_youtube_dislike(self, meta: VideoMetadata) -> VideoMetadata:
        """Fill missing like/dislike counts from Return YouTube Dislike public API."""
        if not self._settings.fetch_ryd_vote_counts:
            return meta
        need_dislike = meta.dislike_count is None
        need_like = meta.like_count is None
        if not need_dislike and not need_like:
            return meta
        ryd_likes, ryd_dislikes = await fetch_ryd_vote_counts(
            meta.video_id,
            base_url=self._settings.ryd_api_base_url,
            timeout_s=self._settings.ryd_timeout_s,
        )
        updates: dict[str, Any] = {}
        if need_dislike and ryd_dislikes is not None:
            updates["dislike_count"] = ryd_dislikes
            updates["dislike_source"] = "return_youtube_dislike"
        if need_like and ryd_likes is not None:
            updates["like_count"] = ryd_likes
        if not updates:
            return meta
        return meta.model_copy(update=updates)
