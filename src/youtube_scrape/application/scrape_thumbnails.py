"""Download poster thumbnail variants to disk via ``HttpClient``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.domain.player_parser import parse_video_metadata
from youtube_scrape.domain.ports import BrowserSession, FileSink, HttpClient
from youtube_scrape.domain.youtube_url import watch_url
from youtube_scrape.exceptions import ExtractionError
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)

# Thumbnail CDN often expects a YouTube referer on cold clients.
_YOUTUBE_PAGE_REFERER = "https://www.youtube.com/"


def _suffix_from_url(url: str) -> str:
    """Pick a safe file extension from the URL path; default ``.jpg``."""
    path = urlparse(url).path.lower()
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        if path.endswith(ext):
            return ext
    return ".jpg"


class ScrapeThumbnailsService:
    """Resolve thumbnail URLs from the player response and write each variant."""

    def __init__(
        self,
        *,
        browser: BrowserSession,
        http: HttpClient,
        files: FileSink,
        settings: Settings,
    ) -> None:
        self._browser = browser
        self._http = http
        self._files = files
        self._settings = settings

    async def scrape(
        self,
        url_or_id: str,
        *,
        out_dir: Path,
        max_variants: int | None = None,
    ) -> ResultEnvelope:
        """Download up to ``max_variants`` distinct thumbnail URLs (default: all from metadata)."""
        url = watch_url(url_or_id)
        log.info("scrape_thumbnails_start", extra={"url": url, "out_dir": str(out_dir)})
        player, _initial, _html = await self._browser.extract_watch_payload(url)
        meta = parse_video_metadata(player)
        if not meta.thumbnails:
            msg = "No thumbnail URLs in player response"
            raise ExtractionError(msg, details="no_thumbnails")

        saved: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for idx, thumb in enumerate(meta.thumbnails):
            if max_variants is not None and len(saved) >= max_variants:
                break
            turl = str(thumb.url).strip()
            if not turl or turl in seen_urls:
                continue
            seen_urls.add(turl)
            ext = _suffix_from_url(turl)
            w = thumb.width if thumb.width is not None else "u"
            h = thumb.height if thumb.height is not None else "u"
            filename = f"{meta.video_id}_{w}x{h}_{idx}{ext}"
            dest = out_dir / filename
            headers = None
            host = urlparse(turl).netloc.lower()
            if "ytimg.com" in host or "ggpht.com" in host:
                headers = {"Referer": _YOUTUBE_PAGE_REFERER}
            data = await self._http.get_bytes(turl, headers=headers)
            self._files.write_bytes(dest, data)
            saved.append(
                {
                    "path": str(dest),
                    "url": turl,
                    "width": thumb.width,
                    "height": thumb.height,
                    "bytes": len(data),
                }
            )

        payload: dict[str, Any] = {
            "video_id": meta.video_id,
            "title": meta.title,
            "out_dir": str(out_dir.resolve()),
            "saved": saved,
            "count": len(saved),
        }
        return make_envelope(settings=self._settings, kind="thumbnails", data=payload)
