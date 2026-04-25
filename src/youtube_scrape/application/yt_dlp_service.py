"""Video/audio downloading using yt-dlp as a Python library.

This module provides a service class that wraps yt-dlp's Python API for reliable
video and audio downloading. It handles:
- Full video downloads (muxed audio+video)
- Audio-only extraction
- MP3 transcoding
- Format selection (best, worst, specific itag)

yt-dlp is the primary download method for the application, replacing the
experimental browser-based approach which had limitations (~22s clips, UMP
corruption, 403 errors on range requests).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.exceptions import YouTubeScrapeError
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)


class YtDlpDownloadService:
    """Video/audio downloading using yt-dlp as a library.

    This service provides reliable full-file downloads by leveraging yt-dlp's
    sophisticated handling of:
    - JavaScript challenge solving (n-parameter and signature deciphering)
    - Browser impersonation (TLS fingerprinting, headers)
    - Multi-client API strategy (android_vr, web_safari, etc.)
    - DASH/HLS stream downloading with proper authentication
    """

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the yt-dlp download service.

        Args:
            settings: Optional settings object for configuration.
        """
        self._settings = settings

    def _make_ydl_opts(
        self,
        output_path: Path,
        *,
        format_selector: str = "best",
        audio_only: bool = False,
        mp3_output: bool = False,
        quiet: bool = True,
        name_from_title: bool = False,
    ) -> dict[str, Any]:
        """Build yt-dlp options dictionary.

        Args:
            output_path: Desired output file path (stem used, extension from yt-dlp).
            format_selector: Format selection string (best, worst, itag, etc.).
            audio_only: If True, download audio-only format.
            mp3_output: If True, transcode to MP3.
            quiet: If True, suppress yt-dlp output.
            name_from_title: If True, use video title as filename.

        Returns:
            Options dictionary for YoutubeDL.
        """
        # Build output template from path
        # When name_from_title is enabled, use yt-dlp's %(title)s template
        if name_from_title:
            outtmpl = str(output_path.parent / "%(title)s.%(ext)s")
        else:
            outtmpl = str(output_path.parent / f"{output_path.stem}.%(ext)s")

        opts: dict[str, Any] = {
            "format": format_selector,
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": quiet,
            "no_warnings": quiet,
            "overwrites": True,
            "continuedl": False,
        }

        if audio_only:
            # Download best audio, fallback to best overall
            opts["format"] = "bestaudio/best"

        if mp3_output:
            # Extract audio and convert to MP3
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        return opts

    def download(
        self,
        url: str,
        output_path: Path,
        *,
        stream_kind: Literal["video", "audio"] = "video",
        audio_encoding: Literal["container", "mp3"] = "container",
        selection: str = "best",
        name_from_title: bool = False,
    ) -> ResultEnvelope:
        """Download video or audio using yt-dlp.

        Args:
            url: YouTube URL or video ID.
            output_path: Desired output file path.
            stream_kind: "video" for muxed A+V, "audio" for audio-only.
            audio_encoding: "container" for original format, "mp3" for MP3.
            selection: Format selection (best, worst, or itag number).

        Returns:
            ResultEnvelope with download result.

        Raises:
            YouTubeScrapeError: If download fails.
        """
        audio_only = stream_kind == "audio"
        mp3_output = audio_encoding == "mp3"

        opts = self._make_ydl_opts(
            output_path,
            format_selector=selection,
            audio_only=audio_only,
            mp3_output=mp3_output,
            name_from_title=name_from_title,
        )

        log.info(
            "yt_dlp_download_start",
            extra={
                "url": url[:80],
                "output": str(output_path),
                "audio_only": audio_only,
                "mp3_output": mp3_output,
                "selection": selection,
            },
        )

        try:
            with YoutubeDL(opts) as ydl:
                # Extract info and download
                info = ydl.extract_info(url, download=True)

                if info is None:
                    msg = "yt-dlp returned no info for the video"
                    raise YouTubeScrapeError(msg, details="yt_dlp_no_info")

                # Find the actual written file
                written_path = self._resolve_output_path(output_path, info)

                if not written_path.exists():
                    msg = f"yt-dlp reported success but file not found: {written_path}"
                    raise YouTubeScrapeError(msg, details="yt_dlp_file_missing")

                file_size = written_path.stat().st_size

                log.info(
                    "yt_dlp_download_ok",
                    extra={
                        "path": str(written_path),
                        "bytes": file_size,
                        "title": info.get("title", "unknown"),
                        "duration": info.get("duration"),
                    },
                )

                return make_envelope(
                    settings=self._settings,
                    kind="download",
                    data={
                        "path": str(written_path),
                        "bytes_written": file_size,
                        "strategy": "yt_dlp",
                        "title": info.get("title"),
                        "duration": info.get("duration"),
                        "format_id": info.get("format_id"),
                        "resolution": info.get("resolution"),
                        "audio_codec": info.get("acodec"),
                        "video_codec": info.get("vcodec"),
                    },
                )

        except DownloadError as e:
            msg = f"yt-dlp download failed: {e}"
            log.error("yt_dlp_download_failed", extra={"error": str(e)})
            raise YouTubeScrapeError(msg, details=str(e)) from e
        except Exception as e:
            msg = f"Unexpected error during yt-dlp download: {e}"
            log.error("yt_dlp_download_exception", extra={"error": str(e), "type": type(e).__name__})
            raise YouTubeScrapeError(msg, details=str(e)) from e

    def _resolve_output_path(self, requested_path: Path, info: dict[str, Any]) -> Path:
        """Resolve the actual output path from yt-dlp info.

        yt-dlp may change the extension or filename (when using title template).
        This method finds the correct file.

        Args:
            requested_path: The originally requested output path.
            info: The info dict returned by yt-dlp.

        Returns:
            Path to the actual downloaded file.
        """
        parent = requested_path.parent

        # First check if the requested path exists (rare, yt-dlp usually adds ext)
        if requested_path.exists():
            return requested_path

        # Check yt-dlp's reported filename first - this is the most reliable source
        if "filename" in info:
            reported_filename = info["filename"]
            # Try as-is (might be absolute path)
            reported = Path(reported_filename)
            if reported.exists():
                return reported
            # Try in the parent directory (might be relative basename)
            reported_in_parent = parent / reported.name
            if reported_in_parent.exists():
                return reported_in_parent

        # When using name_from_title, yt-dlp uses the video title as filename
        # Check for files matching the video title
        title = info.get("title")
        if title:
            # Sanitize title like yt-dlp does (basic sanitization)
            safe_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in title)
            extensions = [".mp4", ".webm", ".mkv", ".m4a", ".mp3"]
            for ext in extensions:
                candidate = parent / f"{safe_title}{ext}"
                if candidate.exists():
                    return candidate

        # Check common extensions based on the requested stem
        stem = requested_path.stem
        extensions = [".mp4", ".webm", ".mkv", ".m4a", ".mp3"]
        for ext in extensions:
            candidate = parent / f"{stem}{ext}"
            if candidate.exists():
                return candidate

        # Last resort: return requested path (caller will check existence)
        return requested_path

    def is_available(self) -> bool:
        """Check if yt-dlp is available and functional.

        Returns:
            True if yt-dlp can be imported and basic operations work.
        """
        try:
            # Try to import and create a YoutubeDL instance
            with YoutubeDL({"quiet": True}) as ydl:
                # Just checking initialization works
                return True
        except Exception:
            return False

    def get_version(self) -> str | None:
        """Get yt-dlp version string.

        Returns:
            Version string like "2026.03.17", or None if unavailable.
        """
        try:
            from yt_dlp.version import __version__
            return __version__
        except Exception:
            return None