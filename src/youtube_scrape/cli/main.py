"""Typer CLI composition root."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any, Literal, cast, get_args

import typer

from youtube_scrape.adapters.browser_playwright import CamoufoxBrowserSession
from youtube_scrape.adapters.filesystem import LocalFileSink
from youtube_scrape.adapters.http_httpx import HttpxHttpClient
from youtube_scrape.application.batch_scrape import BatchRunner
from youtube_scrape.application.download_media import (
    AudioEncoding,
    DownloadMediaService,
    Selection,
    StreamKind,
)
from youtube_scrape.application.download_service import DownloadService
from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.application.yt_dlp_download import is_yt_dlp_available, run_yt_dlp_download
from youtube_scrape.application.scrape_comments import ScrapeCommentsService
from youtube_scrape.application.scrape_thumbnails import ScrapeThumbnailsService
from youtube_scrape.application.scrape_transcript import ScrapeTranscriptService
from youtube_scrape.application.scrape_video import ScrapeVideoService
from youtube_scrape.config import ScrapeConfig
from youtube_scrape.domain.youtube_url import parse_video_id
from youtube_scrape.settings import Settings

app = typer.Typer(
    help="YouTube scraper: Camoufox-backed extraction without the Data API.",
    no_args_is_help=True,
    add_completion=False,
)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(levelname)s %(name)s %(message)s",
    )


TranscriptFormat = Literal["txt", "vtt", "json"]
BatchMode = Literal["video", "comments", "transcript"]


def _write_out(path: Path | None, payload: str) -> None:
    if path is None:
        sys.stdout.write(payload)
        if not payload.endswith("\n"):
            sys.stdout.write("\n")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


@app.callback()
def _main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to YAML/JSON config file."),
    ] = None,
    log_level: Annotated[str | None, typer.Option("--log-level", help="Logging level name.")] = None,
    headless: Annotated[bool | None, typer.Option("--headless/--headed", help="Run Camoufox headless.")] = None,
    schema_version: Annotated[
        str | None,
        typer.Option("--schema-version", help="Emitted JSON schema_version field."),
    ] = None,
    proxy: Annotated[str | None, typer.Option("--proxy", help="Proxy server URL for Camoufox/HTTP.")] = None,
    user_data_dir: Annotated[
        Path | None,
        typer.Option("--user-data-dir", help="Persistent Firefox profile directory."),
    ] = None,
    reuse_browser: Annotated[
        bool | None,
        typer.Option(
            "--reuse-browser/--no-reuse-browser",
            help="One Camoufox for all browser steps in a command (recommended with downloads).",
        ),
    ] = None,
    browser_timeout_s: Annotated[float | None, typer.Option("--browser-timeout", help="Seconds.")] = None,
    http_timeout_s: Annotated[float | None, typer.Option("--http-timeout", help="Seconds.")] = None,
) -> None:
    # Load config file - REQUIRED. No hardcoded defaults allowed.
    try:
        scrape_config = ScrapeConfig.find_and_load(config)
    except FileNotFoundError as e:
        print(f"\n❌ Configuration Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Apply CLI overrides (only if explicitly set)
    overrides = {
        "log_level": log_level,
        "headless": headless,
        "schema_version": schema_version,
        "proxy": proxy,
        "user_data_dir": user_data_dir,
        "reuse_browser": reuse_browser,
        "browser_timeout": browser_timeout_s,
        "http_timeout": http_timeout_s,
    }
    scrape_config = scrape_config.merge_with_cli(**{k: v for k, v in overrides.items() if v is not None})

    # Configure logging
    _configure_logging(scrape_config.logging.level)

    # Create Settings and store both it and ScrapeConfig
    settings = Settings(
        log_level=scrape_config.logging.level,
        headless=scrape_config.browser.headless,
        output_schema_version=scrape_config.output.schema_version,
        proxy_server=scrape_config.browser.proxy_server,
        user_data_dir=scrape_config.browser.user_data_dir,
        browser_reuse_context=scrape_config.browser.reuse_context,
        browser_timeout_s=scrape_config.browser.timeout_s,
        http_timeout_s=scrape_config.http.timeout_s,
    )
    # Attach config to settings object (won't be validated by pydantic since we use extra="ignore")
    settings.__dict__["_scrape_config"] = scrape_config
    ctx.obj = settings


@app.command("video")
def video_cmd(
    ctx: typer.Context,
    url_or_id: Annotated[str, typer.Argument(help="Watch URL or 11-char video id.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write JSON here; default stdout.")] = None,
) -> None:
    """Scrape video metadata, caption track list, and stream format preview."""

    settings = cast(Settings, ctx.obj)

    async def _run() -> str:
        browser = CamoufoxBrowserSession(settings)
        try:
            svc = ScrapeVideoService(browser=browser, settings=settings)
            envelope = await svc.scrape(url_or_id)
            return envelope.model_dump_json(indent=2)
        finally:
            await browser.aclose()

    text = asyncio.run(_run())
    _write_out(out, text)


@app.command("transcript")
def transcript_cmd(
    ctx: typer.Context,
    url_or_id: Annotated[str, typer.Argument(help="Watch URL or video id.")],
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    language: Annotated[str | None, typer.Option("--language", "-l", help="Caption language code.")] = None,
    fmt: Annotated[str, typer.Option("--fmt", help="Caption payload: txt | vtt | json.")] = "txt",
) -> None:
    """Download captions / transcript for a video."""

    settings = cast(Settings, ctx.obj)
    allowed_fmt = get_args(TranscriptFormat)
    if fmt not in allowed_fmt:
        raise typer.BadParameter(f"fmt must be one of: {', '.join(allowed_fmt)}")
    fmt_typed: TranscriptFormat = fmt  # type: ignore[assignment]

    async def _run() -> str:
        browser = CamoufoxBrowserSession(settings)
        http = HttpxHttpClient(
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
        )
        try:
            svc = ScrapeTranscriptService(browser=browser, http=http, settings=settings)
            envelope = await svc.scrape(url_or_id, language=language, fmt=fmt_typed)
            return envelope.model_dump_json(indent=2)
        finally:
            await http.aclose()
            await browser.aclose()

    text = asyncio.run(_run())
    _write_out(out, text)


@app.command("thumbnails")
def thumbnails_cmd(
    ctx: typer.Context,
    url_or_id: Annotated[str, typer.Argument(help="Watch URL or video id.")],
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", "-d", help="Directory to write image files into."),
    ],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write result JSON envelope here; default stdout."),
    ] = None,
    max_variants: Annotated[
        int | None,
        typer.Option("--max", help="Cap number of distinct thumbnail URLs to fetch."),
    ] = None,
) -> None:
    """Download thumbnail image variants listed in the player response."""

    settings = cast(Settings, ctx.obj)

    async def _run() -> str:
        browser = CamoufoxBrowserSession(settings)
        http = HttpxHttpClient(
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
        )
        files = LocalFileSink()
        try:
            svc = ScrapeThumbnailsService(
                browser=browser,
                http=http,
                files=files,
                settings=settings,
            )
            envelope = await svc.scrape(url_or_id, out_dir=out_dir, max_variants=max_variants)
            return envelope.model_dump_json(indent=2)
        finally:
            await http.aclose()
            await browser.aclose()

    text = asyncio.run(_run())
    _write_out(out, text)


@app.command("comments")
def comments_cmd(
    ctx: typer.Context,
    url_or_id: Annotated[str, typer.Argument(help="Watch URL or video id.")],
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
    max_comments: Annotated[
        int | None,
        typer.Option("--max-comments", help="Stop after N comments (approx)."),
    ] = None,
    all_comments: Annotated[bool, typer.Option("--all", help="Fetch until exhaustion or safety ceiling.")] = False,
    max_replies: Annotated[
        int | None,
        typer.Option("--max-replies-per-thread", help="Cap replies per top-level thread."),
    ] = None,
    include_replies: Annotated[
        bool,
        typer.Option("--include-replies/--no-replies", help="Include reply comments."),
    ] = True,
) -> None:
    """Scrape comments and optional replies."""

    settings = cast(Settings, ctx.obj)

    async def _run() -> str:
        browser = CamoufoxBrowserSession(settings)
        http = HttpxHttpClient(
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
        )
        try:
            svc = ScrapeCommentsService(browser=browser, http=http, settings=settings)
            envelope = await svc.scrape(
                url_or_id,
                max_comments=max_comments,
                fetch_all=all_comments,
                max_replies_per_thread=max_replies,
                include_replies=include_replies,
            )
            return envelope.model_dump_json(indent=2)
        finally:
            await http.aclose()
            await browser.aclose()

    text = asyncio.run(_run())
    _write_out(out, text)


def _parse_selection(value: str) -> Selection:
    lowered = value.strip().lower()
    if lowered == "best":
        return "best"
    if lowered == "worst":
        return "worst"
    return int(value.strip(), 10)


@app.command("download")
def download_cmd(
    ctx: typer.Context,
    url_or_id: Annotated[str, typer.Argument(help="Watch URL or video id.")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Destination file path, or a directory when using --name-from-title. Defaults to config output.directory.",
        ),
    ] = None,
    name_from_title: Annotated[
        bool | None,
        typer.Option(
            "--name-from-title",
            help="Write using the watch page title (sanitized). Uses config value if not specified.",
        ),
    ] = None,
    selection: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="best | worst | numeric itag (progressive plain URL only).",
        ),
    ] = "best",
    experimental_download: Annotated[
        bool,
        typer.Option(
            "--experimental-download/--no-experimental-download",
            help="Fallback to browser-based capture if yt-dlp fails. Produces short clips; use only for audio/MP3 when yt-dlp unavailable.",
        ),
    ] = False,
    max_bytes: Annotated[
        int | None,
        typer.Option(
            "--max-bytes",
            help="Optional cap on bytes read (truncates; for smoke tests). Omit for full file.",
        ),
    ] = None,
    stream: Annotated[
        str,
        typer.Option(
            "--stream",
            help="video: progressive combined A+V. audio: adaptive audio-only plain URL (no muxed video).",
        ),
    ] = "video",
    audio_encoding: Annotated[
        str,
        typer.Option(
            "--audio-encoding",
            help="container: write bytes as served (m4a/webm). mp3: transcode with ffmpeg (requires --stream audio).",
        ),
    ] = "container",
    network_debug: Annotated[
        bool,
        typer.Option(
            "--network-debug/--no-network-debug",
            help="Camoufox path only: write <output>.network-debug.json and a sniffer-best spool for diagnosis.",
        ),
    ] = False,
    try_ffmpeg_repair: Annotated[
        bool,
        typer.Option(
            "--try-ffmpeg-repair/--no-try-ffmpeg-repair",
            help="After experimental download, if the file is a DASH fMP4 fragment, run best-effort ffmpeg -c copy remux to a sibling .repaired.mp4 (may still fail).",
        ),
    ] = False,
) -> None:
    """Download video or audio using yt-dlp (primary) or experimental fallback."""

    settings = cast(Settings, ctx.obj)
    config = settings.__dict__.get("_scrape_config")
    if config is None:
        from youtube_scrape.config import ScrapeConfig
        config = ScrapeConfig()

    sel = _parse_selection(selection)
    s = stream.strip().lower()
    if s not in ("video", "audio"):
        raise typer.BadParameter("stream must be video or audio")
    ae = audio_encoding.strip().lower()
    if ae not in ("container", "mp3"):
        raise typer.BadParameter("audio-encoding must be container or mp3")
    stream_typed: StreamKind = s  # type: ignore[assignment]
    audio_enc_typed: AudioEncoding = ae  # type: ignore[assignment]

    # Use config defaults if not provided via CLI
    use_name_from_title = name_from_title if name_from_title is not None else config.download.name_from_title
    output_path = output if output is not None else config.output.directory

    # Create unified download service
    service = DownloadService(settings)

    # Log yt-dlp version for debugging
    ytdlp_version = service.get_yt_dlp_version()
    if ytdlp_version:
        logging.getLogger(__name__).info(f"yt-dlp version: {ytdlp_version}")
    else:
        logging.getLogger(__name__).warning("yt-dlp version check failed")

    async def _run() -> str:
        video_id = parse_video_id(url_or_id) or "video"

        # Build output directory path
        if use_name_from_title:
            # When using title as filename, output_path is the base directory
            dest_dir = output_path
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Use a placeholder - yt-dlp will replace with actual title
            dest = dest_dir / "__youtube_scrape_pending__.mp4"
        else:
            # When using video ID as filename
            dest_dir = output_path
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{video_id}.mp4"

        # Use unified download service - yt-dlp primary, experimental fallback
        envelope = await service.download(
            url_or_id,
            dest,
            stream_kind=stream_typed,
            audio_encoding=audio_enc_typed,
            selection=sel,
            experimental_fallback=experimental_download,
            name_from_title=use_name_from_title,
        )

        if use_name_from_title:
            written = Path(str(envelope.data.get("path", dest)))
            with suppress(OSError):
                (output_path / "VIDEO_OUTPUT.txt").write_text(f"{written.name}\n", encoding="utf-8")
        return envelope.model_dump_json(indent=2)

    text = asyncio.run(_run())
    _write_out(None, text)


@app.command("all")
def all_cmd(
    ctx: typer.Context,
    url_or_id: Annotated[str, typer.Argument(help="Watch URL or 11-char video id.")],
    out_dir: Annotated[
        Path | None,
        typer.Option("--out-dir", "-d", help="Output directory for all artifacts."),
    ] = None,
) -> None:
    """Run all enabled scrapes from config (video, comments, transcript, thumbnails, download)."""

    settings = cast(Settings, ctx.obj)
    config = settings.__dict__.get("_scrape_config")
    if config is None:
        from youtube_scrape.config import ScrapeConfig
        config = ScrapeConfig()

    # Use config output directory or CLI override
    output_dir = out_dir or config.get_output_path(parse_video_id(url_or_id) or "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {}

    async def _run() -> dict[str, Any]:
        browser = CamoufoxBrowserSession(settings)
        http = HttpxHttpClient(
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
        )
        files = LocalFileSink()

        try:
            # 1. Video metadata (always base)
            if config.video.enabled:
                logging.info("[all] Scraping video metadata...")
                svc = ScrapeVideoService(browser=browser, settings=settings)
                envelope = await svc.scrape(url_or_id)
                results["video"] = envelope.model_dump()
                video_path = output_dir / "video.json"
                video_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                logging.info(f"[all] Video metadata saved to {video_path}")

            # 2. Thumbnails
            if config.thumbnails.enabled:
                logging.info("[all] Downloading thumbnails...")
                thumbs_dir = output_dir / "thumbnails"
                thumbs_dir.mkdir(exist_ok=True)
                svc = ScrapeThumbnailsService(
                    browser=browser,
                    http=http,
                    files=files,
                    settings=settings,
                )
                envelope = await svc.scrape(
                    url_or_id,
                    out_dir=thumbs_dir,
                    max_variants=config.thumbnails.max_variants,
                )
                results["thumbnails"] = envelope.model_dump()
                thumbs_path = output_dir / "thumbnails.json"
                thumbs_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                logging.info(f"[all] Thumbnails saved to {thumbs_dir}")

            # 3. Transcript
            if config.transcript.enabled:
                logging.info("[all] Downloading transcript...")
                svc = ScrapeTranscriptService(browser=browser, http=http, settings=settings)
                envelope = await svc.scrape(
                    url_or_id,
                    language=config.transcript.language,
                    fmt=config.transcript.fmt,
                )
                results["transcript"] = envelope.model_dump()
                # Save transcript in requested format
                ext = config.transcript.fmt
                transcript_path = output_dir / f"transcript.{ext}"
                if ext == "json":
                    transcript_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                else:
                    # For txt/vtt, write the content directly
                    content = envelope.data.get("content", "")
                    transcript_path.write_text(content, encoding="utf-8")
                logging.info(f"[all] Transcript saved to {transcript_path}")

            # 4. Comments
            if config.comments.enabled:
                logging.info("[all] Scraping comments...")
                svc = ScrapeCommentsService(browser=browser, http=http, settings=settings)
                envelope = await svc.scrape(
                    url_or_id,
                    max_comments=config.comments.max_comments,
                    fetch_all=config.comments.fetch_all,
                    max_replies_per_thread=config.comments.max_replies_per_thread,
                    include_replies=config.comments.include_replies,
                )
                results["comments"] = envelope.model_dump()
                comments_path = output_dir / "comments.json"
                comments_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                logging.info(f"[all] Comments saved to {comments_path}")

            # 5. Video/audio download
            if config.download.enabled:
                logging.info("[all] Downloading media...")
                dl_svc = DownloadService(settings)
                # Determine output filename
                if config.download.name_from_title:
                    dest = output_dir / "__pending__.mp4"
                else:
                    video_id = parse_video_id(url_or_id) or "video"
                    dest = output_dir / f"{video_id}.mp4"

                envelope = await dl_svc.download(
                    url_or_id,
                    dest,
                    stream_kind=config.download.stream,
                    audio_encoding=config.download.audio_encoding,
                    selection=str(config.download.format),
                    experimental_fallback=config.download.experimental_fallback,
                    name_from_title=config.download.name_from_title,
                )
                results["download"] = envelope.model_dump()
                final_path = envelope.data.get("path", str(dest))
                logging.info(f"[all] Media saved to {final_path}")

            return results

        finally:
            await http.aclose()
            await browser.aclose()

    final_results = asyncio.run(_run())

    # Write summary
    summary = {
        "schema_version": config.output.schema_version,
        "video_id": parse_video_id(url_or_id),
        "output_directory": str(output_dir.absolute()),
        "operations_run": list(final_results.keys()),
        "config_used": {
            "video": config.video.enabled,
            "thumbnails": config.thumbnails.enabled,
            "transcript": config.transcript.enabled,
            "comments": config.comments.enabled,
            "download": config.download.enabled,
        },
        "results": final_results,
    }

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    _write_out(None, json.dumps(summary, indent=2))


@app.command("batch")
def batch_cmd(
    ctx: typer.Context,
    urls_file: Annotated[Path, typer.Argument(help="Text file with one URL or id per line.")],
    report: Annotated[Path, typer.Option("--report", "-o", help="JSON report output path.")] = Path(
        "batch-report.json"
    ),
    mode: Annotated[str, typer.Option("--mode", help="video | comments | transcript")] = "video",
    fail_fast: Annotated[bool, typer.Option("--fail-fast", help="Stop on first failure.")] = False,
) -> None:
    """Run scrapes for many URLs sequentially."""

    settings = cast(Settings, ctx.obj)
    allowed_modes = get_args(BatchMode)
    if mode not in allowed_modes:
        raise typer.BadParameter(f"mode must be one of: {', '.join(allowed_modes)}")
    mode_typed: BatchMode = mode  # type: ignore[assignment]
    lines = urls_file.read_text(encoding="utf-8").splitlines()
    runner = BatchRunner(settings=settings, files=LocalFileSink())

    async def handle(url: str) -> dict[str, Any]:
        browser = CamoufoxBrowserSession(settings)
        http = HttpxHttpClient(
            timeout_s=settings.http_timeout_s,
            max_retries=settings.http_max_retries,
        )
        try:
            if mode_typed == "video":
                video_svc = ScrapeVideoService(browser=browser, settings=settings)
                env = await video_svc.scrape(url)
                return {"envelope": env.model_dump(mode="json")}
            if mode_typed == "comments":
                comments_svc = ScrapeCommentsService(browser=browser, http=http, settings=settings)
                env = await comments_svc.scrape(
                    url,
                    max_comments=None,
                    fetch_all=False,
                    max_replies_per_thread=None,
                    include_replies=True,
                )
                return {"envelope": env.model_dump(mode="json")}
            transcript_svc = ScrapeTranscriptService(browser=browser, http=http, settings=settings)
            env = await transcript_svc.scrape(url, language=None, fmt="txt")
            return {"envelope": env.model_dump(mode="json")}
        finally:
            await http.aclose()
            await browser.aclose()

    rows = asyncio.run(runner.run(lines, handler=handle, fail_fast=fail_fast))
    runner.write_report(report, rows)
    _write_out(None, json.dumps({"report": str(report), "count": len(rows)}, indent=2))


@app.command("parse-id")
def parse_id_cmd(
    url_or_id: Annotated[str, typer.Argument(help="URL or raw id.")],
) -> None:
    """Resolve and print the canonical 11-character video id."""
    _write_out(None, parse_video_id(url_or_id) + "\n")


def run() -> None:
    """Entry point for ``python -m youtube_scrape``."""
    app()


if __name__ == "__main__":
    app()
