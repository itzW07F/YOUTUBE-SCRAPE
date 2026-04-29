"""Opt-in live tests against a reference watch URL; writes artifacts under tests/output/reference/."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from youtube_scrape.adapters.browser_playwright import CamoufoxBrowserSession
from youtube_scrape.adapters.filesystem import LocalFileSink
from youtube_scrape.adapters.http_httpx import HttpxHttpClient
from youtube_scrape.application.download_media import DownloadMediaService
from youtube_scrape.application.scrape_comments import ScrapeCommentsService
from youtube_scrape.application.scrape_thumbnails import ScrapeThumbnailsService
from youtube_scrape.application.scrape_transcript import ScrapeTranscriptService
from youtube_scrape.application.scrape_video import ScrapeVideoService
from youtube_scrape.domain.youtube_url import parse_video_id
from youtube_scrape.exceptions import ExtractionError, HttpTransportError, UnsupportedFormatError
from youtube_scrape.settings import Settings

pytestmark = pytest.mark.live_reference

_DEFAULT_REFERENCE_URL = "https://www.youtube.com/watch?v=dYag3jVVfsQ"


def _require_env() -> None:
    if os.environ.get("RUN_BROWSER_TESTS") != "1":
        pytest.skip("Set RUN_BROWSER_TESTS=1 for live reference tests.")
    if os.environ.get("RUN_LIVE_REFERENCE_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_REFERENCE_TESTS=1 for live reference tests.")


def _reference_url() -> str:
    return os.environ.get("REFERENCE_VIDEO_URL", _DEFAULT_REFERENCE_URL).strip()


def _output_root() -> Path:
    return Path(__file__).resolve().parent / "output" / "reference"


def _run_dir() -> Path:
    vid = parse_video_id(_reference_url())
    path = _output_root() / vid
    path.mkdir(parents=True, exist_ok=True)
    return path


def _live_settings() -> Settings:
    profile = Path(__file__).resolve().parent / "output" / ".browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return Settings(
        headless=True,
        browser_timeout_s=90.0,
        http_timeout_s=60.0,
        max_navigation_retries=3,
        page_settle_after_load_ms=12_000,
        browser_reuse_context=True,
        user_data_dir=profile,
    )


def _live_download_settings() -> Settings:
    """Headful by default for progressive download (see ``RUN_LIVE_REFERENCE_HEADFUL``).

    ``watch_page_comments_hydration_ms=0`` and ``page_settle_after_load_ms=0`` skip comment-panel
    hydration so metadata extraction and download do not each burn the scroll/wait window.
    """
    base = _live_settings()
    v = os.environ.get("RUN_LIVE_REFERENCE_HEADFUL", "1").strip().lower()
    headless = v in ("0", "false", "no", "off")
    return base.model_copy(
        update={
            "headless": headless,
            "watch_page_comments_hydration_ms": 0,
            "page_settle_after_load_ms": 0,
            "browser_timeout_s": 120.0,
            "http_timeout_s": 75.0,
            "media_download_timeout_s": 900.0,
            "youtube_preroll_ad_skip_budget_s": 70.0,
        }
    )


@pytest.mark.asyncio
async def test_reference_video_envelope() -> None:
    _require_env()
    run_dir = _run_dir()
    settings = _live_settings()
    browser = CamoufoxBrowserSession(settings)
    try:
        svc = ScrapeVideoService(browser=browser, settings=settings)
        envelope = await svc.scrape(_reference_url())
    finally:
        await browser.aclose()
    out = run_dir / "video.json"
    out.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")

    assert envelope.schema_version
    assert envelope.kind == "video"
    meta = envelope.data.get("metadata", {})
    assert meta.get("video_id") == parse_video_id(_reference_url())
    assert isinstance(meta.get("title"), str) and len(meta.get("title", "")) > 0
    assert int(envelope.data.get("stream_formats_total", -1)) >= 0


@pytest.mark.asyncio
async def test_reference_thumbnails() -> None:
    _require_env()
    run_dir = _run_dir()
    settings = _live_settings()
    browser = CamoufoxBrowserSession(settings)
    http = HttpxHttpClient(timeout_s=settings.http_timeout_s, max_retries=settings.http_max_retries)
    files = LocalFileSink()
    try:
        svc = ScrapeThumbnailsService(
            browser=browser,
            http=http,
            files=files,
            settings=settings,
        )
        thumbs_dir = run_dir / "thumbs"
        envelope = await svc.scrape(_reference_url(), out_dir=thumbs_dir, max_variants=5)
        (run_dir / "thumbs.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    finally:
        await http.aclose()
        await browser.aclose()

    assert envelope.kind == "thumbnails"
    saved = envelope.data.get("saved", [])
    assert isinstance(saved, list)
    assert len(saved) >= 1
    for item in saved:
        p = Path(str(item["path"]))
        assert p.exists()
        assert p.stat().st_size > 0


@pytest.mark.asyncio
async def test_reference_comments_sample() -> None:
    _require_env()
    run_dir = _run_dir()
    settings = _live_settings()
    browser = CamoufoxBrowserSession(settings)
    http = HttpxHttpClient(timeout_s=settings.http_timeout_s, max_retries=settings.http_max_retries)
    try:
        svc = ScrapeCommentsService(browser=browser, http=http, settings=settings)
        envelope = await svc.scrape(
            _reference_url(),
            max_comments=55,
            fetch_all=False,
            max_replies_per_thread=5,
            include_replies=True,
        )
    finally:
        await http.aclose()
        await browser.aclose()

    (run_dir / "comments.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    count = int(envelope.data.get("returned", 0))
    assert count > 0, (
        "Expected comments from Innertube continuations (entity mutations). "
        "If this fails, check ScrapeCommentsService / comments_extract against current youtubei responses."
    )
    rows = envelope.data.get("comments", [])
    assert isinstance(rows, list)
    assert any(c.get("like_count") is not None for c in rows), "Expected toolbar-derived like_count on entity comments"
    assert sum(1 for c in rows if c.get("is_reply")) >= 2, "Expected nested reply rows from reply continuations"


@pytest.mark.asyncio
async def test_reference_progressive_download_sample() -> None:
    """Full progressive download to ``<sanitized watch title>.mp4`` (ADR-0004).

    Order: direct ``httpx`` GET, Playwright ``APIRequest`` GET, same-origin ``fetch``, route sniffer
    (including byte-range merge), then playback capture on **one** watch tab. Output path is taken
    from ``ytInitialPlayerResponse`` inside that same download navigation (no separate metadata scrape).

    Uses a **headed** Camoufox by default (``RUN_LIVE_REFERENCE_HEADFUL`` unset or truthy); set to
    ``0``/``false``/``no``/``off`` for headless.

    Skips when no plain progressive URL exists or every strategy fails; see ``download.skip.txt``.
    """
    _require_env()
    run_dir = _run_dir()
    settings = _live_download_settings()
    browser = CamoufoxBrowserSession(settings)
    http = HttpxHttpClient(
        timeout_s=max(settings.http_timeout_s, settings.media_download_timeout_s),
        max_retries=settings.http_max_retries,
    )
    files = LocalFileSink()
    try:
        svc = DownloadMediaService(browser=browser, http=http, files=files, settings=settings)
        try:
            envelope = await svc.download(
                _reference_url(),
                selection="best",
                output_path=run_dir / "__youtube_scrape_pending__.mp4",
                experimental=True,
                max_bytes=None,
                derive_output_title_under_dir=run_dir,
            )
        except UnsupportedFormatError as exc:
            skip_path = run_dir / "download.skip.txt"
            skip_path.write_text(f"{exc}\n{getattr(exc, 'details', '')}\n", encoding="utf-8")
            pytest.skip(f"No progressive plain URL for reference video: {exc}")
        except HttpTransportError as exc:
            skip_path = run_dir / "download.skip.txt"
            skip_path.write_text(
                f"{exc}\n{getattr(exc, 'details', '')}\n"
                "Direct HTTP and single-tab browser strategies all failed (see ADR-0004).\n",
                encoding="utf-8",
            )
            pytest.skip(f"Media bytes not retrievable: {exc}")
    finally:
        await http.aclose()
        await browser.aclose()

    dest = Path(str(envelope.data["path"]))
    (run_dir / "download.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "VIDEO_OUTPUT.txt").write_text(f"{dest.name}\n", encoding="utf-8")
    blob = dest.read_bytes()
    assert len(blob) >= 12
    assert b"ftyp" in blob[:32]
    assert int(envelope.data.get("bytes_written", 0)) == len(blob)
    assert envelope.data.get("truncated") is False
    assert len(blob) >= 50_000
    assert "codec_hint" in envelope.data
    caveats = envelope.data.get("playback_caveats")
    assert caveats is None or isinstance(caveats, list)
    exp_raw = envelope.data.get("contentLength")
    exp_cl: int | None = None
    if isinstance(exp_raw, int):
        exp_cl = exp_raw
    elif isinstance(exp_raw, str) and exp_raw.strip().isdigit():
        exp_cl = int(exp_raw.strip(), 10)
    if exp_cl is not None and exp_cl > 100_000:
        assert len(blob) + 256_000 >= exp_cl, (
            "Expected file size near streamingData contentLength for full download; "
            f"got {len(blob)} vs contentLength={exp_cl}"
        )


@pytest.mark.asyncio
async def test_reference_transcript() -> None:
    _require_env()
    run_dir = _run_dir()
    settings = _live_settings()
    browser = CamoufoxBrowserSession(settings)
    http = HttpxHttpClient(timeout_s=settings.http_timeout_s, max_retries=settings.http_max_retries)
    try:
        svc = ScrapeTranscriptService(browser=browser, http=http, settings=settings)
        try:
            envelope = await svc.scrape(_reference_url(), language=None, fmt="txt")
        except ExtractionError as exc:
            skip_path = run_dir / "transcript.skip.txt"
            skip_path.write_text(f"{exc}\n{getattr(exc, 'details', '')}\n", encoding="utf-8")
            pytest.skip(f"No transcript: {exc}")
    finally:
        await http.aclose()
        await browser.aclose()

    (run_dir / "transcript.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
    body = envelope.data.get("body", "")
    assert isinstance(body, str) and len(body) > 0
    (run_dir / "transcript.txt").write_text(body, encoding="utf-8")
