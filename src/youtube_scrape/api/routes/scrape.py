"""Scrape endpoints for the API."""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Literal, cast

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field

from api.state import get_job_store, get_websocket_manager
from youtube_scrape.adapters.browser_playwright import CamoufoxBrowserSession
from youtube_scrape.adapters.filesystem import LocalFileSink
from youtube_scrape.adapters.http_httpx import HttpxHttpClient
from youtube_scrape.application.download_service import DownloadService
from youtube_scrape.application.scrape_comments import ScrapeCommentsService
from youtube_scrape.application.scrape_thumbnails import ScrapeThumbnailsService
from youtube_scrape.application.scrape_transcript import ScrapeTranscriptService
from youtube_scrape.application.scrape_video import ScrapeVideoService
from youtube_scrape.domain.youtube_url import parse_video_id
from youtube_scrape.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter()

TranscriptFormat = Literal["txt", "vtt", "json"]

# UI-oriented log lines (WebSocket + optional step metadata for the GUI).
OPERATION_SCRAPING_LABEL: Dict[str, str] = {
    "video": "Scraping video details",
    "thumbnails": "Scraping thumbnails",
    "transcript": "Scraping transcript",
    "comments": "Scraping comments",
    "download": "Downloading media",
}
OPERATION_DONE_LABEL: Dict[str, str] = {
    "video": "Video details saved",
    "thumbnails": "Thumbnails saved",
    "transcript": "Transcript saved",
    "comments": "Comments saved",
    "download": "Media download finished",
}


class ScrapeVideoRequest(BaseModel):
    """Request model for video scraping."""
    url: str = Field(..., description="YouTube video URL")
    include_video: bool = Field(default=True, description="Include video metadata")
    include_comments: bool = Field(default=False, description="Include comments")
    include_transcript: bool = Field(default=False, description="Include transcript")
    include_thumbnails: bool = Field(default=False, description="Include thumbnails")
    include_download: bool = Field(default=False, description="Download video/audio")
    max_comments: int = Field(default=100, ge=1, le=10000, description="Maximum comments to fetch")
    transcript_format: str = Field(default="txt", description="Transcript format: txt, vtt, json")
    video_quality: str = Field(default="best", description="Video quality preference")


class ScrapeResponse(BaseModel):
    """Response model for scrape requests."""
    job_id: str
    status: str
    output_dir: str
    message: str


def generate_job_id() -> str:
    """Generate a unique job ID."""
    return str(uuid.uuid4())[:8]


def extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL."""
    return parse_video_id(url)


def output_path_for_video(video_id: str) -> Path:
    """Return the absolute output path for a video scrape."""
    output_root = Path(os.environ.get("OUTPUT_DIR", "output")).resolve()
    return output_root / video_id


def requested_operations(request: ScrapeVideoRequest) -> list[str]:
    """Return operation names in the order they should run."""
    operations: list[str] = []
    if request.include_video:
        operations.append("video")
    if request.include_thumbnails:
        operations.append("thumbnails")
    if request.include_transcript:
        operations.append("transcript")
    if request.include_comments:
        operations.append("comments")
    if request.include_download:
        operations.append("download")
    return operations or ["video"]


def download_selection_for_quality(video_quality: str) -> tuple[Literal["video", "audio"], str]:
    """Map GUI quality labels to yt-dlp selectors."""
    if video_quality == "audio":
        return "audio", "bestaudio/best"
    if video_quality in {"1080", "720", "480"}:
        height = int(video_quality)
        return "video", f"best[height<={height}]/best"
    return "video", "best"


async def send_step_progress(job_id: str, operation_index: int, operation_count: int, message: str) -> None:
    """Send deterministic progress for operation boundaries."""
    manager = get_websocket_manager()
    progress = int((operation_index / operation_count) * 100)
    await manager.send_progress(job_id, progress, message)


_SCRAPE_JOB_SEM: asyncio.Semaphore | None = None


def _scrape_job_concurrency_sem() -> asyncio.Semaphore:
    """Limit how many scrape pipelines run at once (browser + I/O); extra jobs wait for a slot."""
    global _SCRAPE_JOB_SEM
    if _SCRAPE_JOB_SEM is None:
        _SCRAPE_JOB_SEM = asyncio.Semaphore(max(1, Settings().max_concurrent_scrape_jobs))
    return _SCRAPE_JOB_SEM


async def run_scrape_job(job_id: str, request: ScrapeVideoRequest) -> None:
    """Run the scrape job in background."""
    async with _scrape_job_concurrency_sem():
        await _run_scrape_job_impl(job_id, request)


async def _run_scrape_job_impl(job_id: str, request: ScrapeVideoRequest) -> None:
    jobs = get_job_store()
    manager = get_websocket_manager()

    job = jobs[job_id]
    video_id = extract_video_id(request.url)
    output_dir = output_path_for_video(video_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    operations = requested_operations(request)
    results: dict[str, Any] = {}
    settings = Settings()
    browser = CamoufoxBrowserSession(settings)
    http = HttpxHttpClient(
        timeout_s=settings.http_timeout_s,
        max_retries=settings.http_max_retries,
    )
    files = LocalFileSink()

    try:
        job["status"] = "running"
        job["output_dir"] = str(output_dir)
        job["started_at"] = datetime.utcnow().isoformat()
        job["operations"] = operations

        await manager.send_status(job_id, "running", {"message": "Initializing..."})
        await manager.send_progress(job_id, 0, "Initializing...")
        await manager.send_log(job_id, "info", "Starting scrape job...")

        partial_failures: list[dict[str, str]] = []
        failed_operations: set[str] = set()

        for index, operation in enumerate(operations):
            if job.get("cancel_requested"):
                job["status"] = "cancelled"
                await manager.send_status(job_id, "cancelled", {"message": "Job cancelled"})
                return

            label = OPERATION_SCRAPING_LABEL.get(operation, f"Scraping: {operation}")
            await manager.send_log(
                job_id,
                "info",
                label,
                step={"id": operation, "phase": "running"},
            )
            await send_step_progress(job_id, index, len(operations), label)

            try:
                if operation == "video":
                    envelope = await ScrapeVideoService(browser=browser, settings=settings).scrape(request.url)
                    results["video"] = envelope.model_dump()
                    (output_dir / "video.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                elif operation == "thumbnails":
                    thumbnails_dir = output_dir / "thumbnails"
                    thumbnails_dir.mkdir(exist_ok=True)
                    envelope = await ScrapeThumbnailsService(
                        browser=browser,
                        http=http,
                        files=files,
                        settings=settings,
                    ).scrape(request.url, out_dir=thumbnails_dir)
                    results["thumbnails"] = envelope.model_dump()
                    (output_dir / "thumbnails.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                elif operation == "transcript":
                    fmt: TranscriptFormat = (
                        cast(TranscriptFormat, request.transcript_format)
                        if request.transcript_format in {"txt", "vtt", "json"}
                        else "txt"
                    )
                    envelope = await ScrapeTranscriptService(browser=browser, http=http, settings=settings).scrape(
                        request.url,
                        language=None,
                        fmt=fmt,
                    )
                    results["transcript"] = envelope.model_dump()
                    transcript_path = output_dir / f"transcript.{fmt}"
                    if fmt == "json":
                        transcript_path.write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                    else:
                        content = envelope.data.get("content") or envelope.data.get("body") or ""
                        transcript_path.write_text(str(content), encoding="utf-8")
                elif operation == "comments":
                    envelope = await ScrapeCommentsService(browser=browser, http=http, settings=settings).scrape(
                        request.url,
                        max_comments=request.max_comments,
                        fetch_all=False,
                        max_replies_per_thread=3,
                        include_replies=True,
                    )
                    results["comments"] = envelope.model_dump()
                    (output_dir / "comments.json").write_text(envelope.model_dump_json(indent=2), encoding="utf-8")
                elif operation == "download":
                    stream_kind, selection = download_selection_for_quality(request.video_quality)
                    audio_encoding = "container"
                    download_dir = output_dir / "download"
                    download_dir.mkdir(exist_ok=True)
                    envelope = await DownloadService(settings).download(
                        request.url,
                        download_dir / f"{video_id}.mp4",
                        stream_kind=stream_kind,
                        audio_encoding=audio_encoding,
                        selection=selection,
                        experimental_fallback=False,
                        name_from_title=False,
                    )
                    results["download"] = envelope.model_dump()
                else:
                    raise ValueError(f"Unknown operation: {operation}")
            except Exception as exc:
                err_text = str(exc)
                logger.warning("Job %s step %s failed (continuing): %s", job_id, operation, err_text, exc_info=True)
                failed_operations.add(operation)
                partial_failures.append({"operation": operation, "error": err_text})
                await manager.send_log(
                    job_id,
                    "warn",
                    f"{label} — skipped: {err_text}",
                    step={"id": operation, "phase": "error"},
                )
            else:
                done_msg = OPERATION_DONE_LABEL.get(operation, f"Finished {operation}")
                await manager.send_log(
                    job_id,
                    "info",
                    done_msg,
                    step={"id": operation, "phase": "done"},
                )

            step_progress_msg = (
                OPERATION_DONE_LABEL.get(operation, "Step complete")
                if operation not in failed_operations
                else f"{operation} skipped — continuing"
            )
            await send_step_progress(job_id, index + 1, len(operations), step_progress_msg)

        summary = {
            "schema_version": settings.output_schema_version,
            "video_id": video_id,
            "output_directory": str(output_dir),
            "operations_run": list(results.keys()),
            "operations_failed": list(failed_operations),
            "errors": {item["operation"]: item["error"] for item in partial_failures},
            "results": results,
        }
        (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        job["status"] = "completed"
        job["progress"] = 100
        job["completed_at"] = datetime.utcnow().isoformat()
        job["result"] = summary
        if partial_failures:
            job["warnings"] = partial_failures

        completed_details: dict[str, Any] = {
            "output_dir": str(output_dir),
            "video_id": video_id,
        }
        if partial_failures:
            completed_details["warnings"] = partial_failures
            completed_details["partial_failures"] = True

        await manager.send_status(job_id, "completed", completed_details)

        logger.info(
            "Job %s completed (%d ok, %d failed steps)",
            job_id,
            len(operations) - len(partial_failures),
            len(partial_failures),
        )

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        job["status"] = "failed"
        job["error"] = str(e)
        await manager.send_log(job_id, "error", str(e))
        await manager.send_status(job_id, "failed", {"error": str(e)})
    finally:
        await http.aclose()
        await browser.aclose()


@router.post("/video", response_model=ScrapeResponse)
async def scrape_video(
    request: ScrapeVideoRequest,
    background_tasks: BackgroundTasks
) -> ScrapeResponse:
    """Start a video scrape job."""
    jobs = get_job_store()
    
    # Generate job ID
    job_id = generate_job_id()
    video_id = extract_video_id(request.url)
    output_dir = output_path_for_video(video_id)
    
    # Create job entry
    jobs[job_id] = {
        "id": job_id,
        "url": request.url,
        "status": "pending",
        "progress": 0,
        "type": "all",
        "output_dir": str(output_dir),
        "options": request.model_dump(),
        "created_at": datetime.utcnow().isoformat(),
        "logs": [],
    }
    
    # Start background task
    background_tasks.add_task(run_scrape_job, job_id, request)
    
    logger.info(f"Started scrape job {job_id} for {request.url}")
    
    return ScrapeResponse(
        job_id=job_id,
        status="started",
        output_dir=str(output_dir),
        message="Scrape job started successfully"
    )


@router.post("/comments")
async def scrape_comments(
    url: str,
    max_comments: int = 100
) -> Dict[str, Any]:
    """Start a comments-only scrape job."""
    request = ScrapeVideoRequest(
        url=url,
        include_video=False,
        include_comments=True,
        max_comments=max_comments
    )
    
    jobs = get_job_store()
    job_id = generate_job_id()
    video_id = extract_video_id(url)
    output_dir = output_path_for_video(video_id)
    
    jobs[job_id] = {
        "id": job_id,
        "url": url,
        "status": "pending",
        "progress": 0,
        "type": "comments",
        "output_dir": str(output_dir),
        "options": request.model_dump(),
        "created_at": datetime.utcnow().isoformat(),
        "logs": [],
    }
    
    return {
        "job_id": job_id,
        "status": "started",
        "output_dir": str(output_dir),
    }


@router.post("/transcript")
async def scrape_transcript(
    url: str,
    fmt: str = "txt"
) -> Dict[str, Any]:
    """Start a transcript-only scrape job."""
    request = ScrapeVideoRequest(
        url=url,
        include_video=False,
        include_transcript=True,
        transcript_format=fmt
    )
    
    jobs = get_job_store()
    job_id = generate_job_id()
    video_id = extract_video_id(url)
    output_dir = output_path_for_video(video_id)
    
    jobs[job_id] = {
        "id": job_id,
        "url": url,
        "status": "pending",
        "progress": 0,
        "type": "transcript",
        "output_dir": str(output_dir),
        "options": request.model_dump(),
        "created_at": datetime.utcnow().isoformat(),
        "logs": [],
    }
    
    return {
        "job_id": job_id,
        "status": "started",
        "output_dir": str(output_dir),
    }


@router.post("/thumbnails")
async def scrape_thumbnails(
    url: str
) -> Dict[str, Any]:
    """Start a thumbnails-only scrape job."""
    request = ScrapeVideoRequest(
        url=url,
        include_video=False,
        include_thumbnails=True
    )
    
    jobs = get_job_store()
    job_id = generate_job_id()
    video_id = extract_video_id(url)
    output_dir = output_path_for_video(video_id)
    
    jobs[job_id] = {
        "id": job_id,
        "url": url,
        "status": "pending",
        "progress": 0,
        "type": "thumbnails",
        "output_dir": str(output_dir),
        "options": request.model_dump(),
        "created_at": datetime.utcnow().isoformat(),
        "logs": [],
    }
    
    return {
        "job_id": job_id,
        "status": "started",
        "output_dir": str(output_dir),
    }
