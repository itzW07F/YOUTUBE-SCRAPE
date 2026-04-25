"""Unified download service - yt-dlp primary, experimental fallback.

This module provides a unified interface for video/audio downloading that:
1. Uses yt-dlp as the primary download method (reliable, full files)
2. Falls back to experimental browser-based download only when yt-dlp fails
   and only for audio/MP3 extraction scenarios

The experimental download path is deprecated for video downloads due to
fundamental limitations (~22s clips, UMP corruption, 403 errors).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from youtube_scrape.adapters.browser_playwright import CamoufoxBrowserSession
from youtube_scrape.adapters.http_httpx import HttpxHttpClient
from youtube_scrape.application.download_media import DownloadMediaService
from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.application.yt_dlp_service import YtDlpDownloadService
from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.exceptions import YouTubeScrapeError
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)


class DownloadService:
    """Unified download service with yt-dlp as primary method.

    This service provides a single interface for all video/audio downloads:
    - Video downloads (muxed A+V): yt-dlp only
    - Audio downloads (container/MP3): yt-dlp primary, experimental fallback

    The experimental browser-based download is kept only as a fallback for
    audio extraction scenarios when yt-dlp is unavailable or fails.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the download service.

        Args:
            settings: Application settings for configuration.
        """
        self._settings = settings
        self._yt_dlp = YtDlpDownloadService(settings)
        # Experimental service kept for audio/MP3 fallback only
        self._experimental: DownloadMediaService | None = None

    async def download(
        self,
        url: str,
        output_path: Path,
        *,
        stream_kind: Literal["video", "audio"] = "video",
        audio_encoding: Literal["container", "mp3"] = "container",
        selection: str = "best",
        experimental_fallback: bool = False,
        name_from_title: bool = False,
    ) -> ResultEnvelope:
        """Download video or audio from YouTube.

        Args:
            url: YouTube URL or video ID.
            output_path: Desired output file path.
            stream_kind: "video" for muxed A+V, "audio" for audio-only.
            audio_encoding: "container" for original format, "mp3" for MP3.
            selection: Format selection (best, worst, or itag number).
            experimental_fallback: If True and yt-dlp fails for audio/MP3,
                try experimental browser-based download.
            name_from_title: If True, use video title as filename.

        Returns:
            ResultEnvelope with download result.

        Raises:
            YouTubeScrapeError: If download fails.
        """
        # PRIMARY PATH: Always try yt-dlp first
        try:
            log.info(
                "download_service_yt_dlp_attempt",
                extra={
                    "url": url[:80],
                    "stream_kind": stream_kind,
                    "audio_encoding": audio_encoding,
                    "selection": selection,
                },
            )

            result = self._yt_dlp.download(
                url,
                output_path,
                stream_kind=stream_kind,
                audio_encoding=audio_encoding,
                selection=selection,
                name_from_title=name_from_title,
            )

            # Log successful download
            data = result.data if hasattr(result, "data") else {}
            log.info(
                "download_service_yt_dlp_success",
                extra={
                    "path": data.get("path", str(output_path)),
                    "bytes": data.get("bytes_written", 0),
                    "strategy": "yt_dlp",
                },
            )

            return result

        except Exception as yt_dlp_error:
            # yt-dlp failed - decide whether to use experimental fallback
            log.warning(
                "download_service_yt_dlp_failed",
                extra={
                    "error": str(yt_dlp_error)[:200],
                    "stream_kind": stream_kind,
                    "experimental_fallback": experimental_fallback,
                },
            )

            # FALLBACK PATH: Only for audio/MP3 with explicit fallback flag
            if experimental_fallback and stream_kind == "audio":
                log.warning(
                    "download_service_experimental_fallback",
                    extra={
                        "message": (
                            "yt-dlp failed for audio download. "
                            "Attempting experimental browser-based fallback. "
                            "Note: Experimental download is deprecated and produces short clips."
                        )
                    },
                )
                return await self._experimental_download(
                    url,
                    output_path,
                    stream_kind=stream_kind,
                    audio_encoding=audio_encoding,
                    selection=selection,
                )

            # No fallback available - re-raise the original error
            raise

    async def _experimental_download(
        self,
        url: str,
        output_path: Path,
        *,
        stream_kind: Literal["video", "audio"],
        audio_encoding: Literal["container", "mp3"],
        selection: str,
    ) -> ResultEnvelope:
        """Fallback to experimental browser-based download.

        This is kept only for audio/MP3 extraction when yt-dlp fails.
        The experimental path is deprecated for video downloads.

        Args:
            url: YouTube URL or video ID.
            output_path: Desired output file path.
            stream_kind: "video" or "audio".
            audio_encoding: "container" or "mp3".
            selection: Format selection.

        Returns:
            ResultEnvelope with download result.
        """
        # Initialize experimental service on first use
        if self._experimental is None:
            browser = CamoufoxBrowserSession(self._settings)
            http = HttpxHttpClient(
                timeout_s=max(
                    self._settings.http_timeout_s,
                    self._settings.media_download_timeout_s,
                ),
                max_retries=self._settings.http_max_retries,
            )
            self._experimental = DownloadMediaService(
                browser=browser,
                http=http,
                settings=self._settings,
            )

        log.warning(
            "download_service_experimental_deprecated",
            extra={
                "message": (
                    "Using experimental browser-based download. "
                    "This is deprecated and produces ~22 second clips with potential "
                    "playback issues due to YouTube's player buffer limitations. "
                    "Consider fixing yt-dlp installation for full audio downloads."
                )
            },
        )

        # Run experimental download
        result = await self._experimental.download(
            url,
            output_path,
            stream_kind=stream_kind,
            audio_encoding=audio_encoding,
            selection=selection,
        )

        # Add fallback flag to result
        if hasattr(result, "data") and isinstance(result.data, dict):
            result.data["yt_dlp_fallback"] = True
            result.data["strategy"] = "experimental_fallback"

        return result

    def is_yt_dlp_available(self) -> bool:
        """Check if yt-dlp is available.

        Returns:
            True if yt-dlp is functional.
        """
        return self._yt_dlp.is_available()

    def get_yt_dlp_version(self) -> str | None:
        """Get yt-dlp version.

        Returns:
            Version string or None.
        """
        return self._yt_dlp.get_version()