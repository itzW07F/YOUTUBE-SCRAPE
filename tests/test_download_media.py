"""DownloadMediaService guards (no browser)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from youtube_scrape.application.download_media import (
    DownloadMediaService,
    _clen_from_videoplayback_url,
)
from youtube_scrape.exceptions import YouTubeScrapeError
from youtube_scrape.settings import Settings


def test_clen_from_videoplayback_url() -> None:
    u = "https://rr1---sn.example.googlevideo.com/videoplayback?clen=12345&itag=18"
    assert _clen_from_videoplayback_url(u) == 12345
    assert _clen_from_videoplayback_url("https://example.com/watch?v=abc") is None


@pytest.mark.asyncio
async def test_mp3_requires_audio_stream() -> None:
    settings = Settings()
    svc = DownloadMediaService(
        browser=MagicMock(),
        http=MagicMock(),
        files=MagicMock(),
        settings=settings,
    )
    with pytest.raises(YouTubeScrapeError, match="MP3 output requires"):
        await svc.download(
            "dQw4w9WgXcQ",
            selection="best",
            output_path=Path("/tmp/out.mp3"),
            experimental=True,
            stream_kind="video",
            audio_encoding="mp3",
        )
