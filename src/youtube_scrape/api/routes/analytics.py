"""Analytics endpoints over local scrape artifacts."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from youtube_scrape.adapters.llm_errors import LlmTransportError
from youtube_scrape.adapters.llm_providers import probe_analytics_llm
from youtube_scrape.adapters.ollama_client import OllamaHttpError, model_matches_installed, normalize_ollama_base_url, ollama_list_model_names
from youtube_scrape.application.analytics_gui_llm_resolve import effective_analytics_llm_settings
from youtube_scrape.application.analytics_llm_chat import run_analytics_llm_chat
from youtube_scrape.application.analytics_ollama_report import generate_ollama_macro_report
from youtube_scrape.application.analytics_scrape_rag import (
    build_rag_index_with_progress,
    get_rag_status,
    rag_manifest_path,
)
from youtube_scrape.application.analytics_snapshot import build_analytics_snapshot
from youtube_scrape.application.gallery_metadata_refresh import output_roots_from_env, resolve_output_dir_for_refresh
from api.state import get_job_store, get_websocket_manager
from youtube_scrape.domain.analytics_models import (
    AnalyticsChatRequestBody,
    AnalyticsChatResponse,
    AnalyticsLlmProbePayload,
    AnalyticsOllamaModelsPayload,
    AnalyticsSnapshot,
    GuiAnalyticsLlmOverlay,
    OllamaReportPayload,
    RagBuildRequest,
    RagBuildResponse,
    RagGlobalStatusItem,
    RagGlobalStatusPayload,
    RagStatusPayload,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class AnalyticsOutputDirBody(BaseModel):
    output_dir: str = Field(..., description="Absolute path to a scrape output folder under configured roots")


class OllamaReportBody(BaseModel):
    output_dir: str = Field(..., description="Absolute path to a scrape output folder under configured roots")
    force_refresh: bool = Field(default=False)
    gui_llm_overlay: GuiAnalyticsLlmOverlay | None = Field(
        default=None,
        description=(
            "Optional snapshot from Electron; merged over server Settings so Analytics LLM works without restarting "
            "the API (e.g. remote Ollama base URL)."
        ),
    )


class LlmProbeRequestBody(BaseModel):
    gui_llm_overlay: GuiAnalyticsLlmOverlay | None = Field(
        default=None,
        description="Optional GUI snapshot overriding server-only env for this probe.",
    )


def _resolve_dir(raw: str) -> Path:
    try:
        return resolve_output_dir_for_refresh(raw, output_roots_from_env())
    except ValueError as exc:
        roots = output_roots_from_env()
        roots_preview = "; ".join(str(p) for p in roots[:4])
        if len(roots) > 4:
            roots_preview += "; …"
        raise HTTPException(
            status_code=400,
            detail=f"{exc} Allowed output roots: {roots_preview}",
        ) from exc


@router.post("/snapshot", response_model=AnalyticsSnapshot)
async def analytics_snapshot(body: AnalyticsOutputDirBody) -> AnalyticsSnapshot:
    """Deterministic metrics from ``video.json``, ``metadata_history.jsonl``, ``comments.json``."""
    path = _resolve_dir(body.output_dir)
    logger.info("analytics_api_snapshot_request", extra={"folder": path.name})
    snapshot = build_analytics_snapshot(path)
    logger.info(
        "analytics_api_snapshot_ok",
        extra={
            "folder": path.name,
            "comments_file_present": snapshot.comments_file_present,
            "metadata_points": snapshot.metadata_history_points,
        },
    )
    return snapshot


@router.post("/llm-probe", response_model=AnalyticsLlmProbePayload)
async def analytics_llm_probe(body: LlmProbeRequestBody) -> AnalyticsLlmProbePayload:
    """Shallow connectivity check for the configured analytics LLM (no scrape folder needed)."""

    overlay = body.gui_llm_overlay
    settings = effective_analytics_llm_settings(gui=overlay)
    logger.info(
        "analytics_api_llm_probe_request",
        extra={
            "provider": settings.analytics_llm_provider,
            "gui_overlay": overlay is not None,
            **(
                {"ollama_base_override": overlay.ollama_base_url[:80]}
                if overlay and overlay.ollama_base_url
                else {}
            ),
        },
    )
    data = await probe_analytics_llm(settings)
    payload = AnalyticsLlmProbePayload.model_validate(data)
    logger.info(
        "analytics_api_llm_probe_ok",
        extra={"provider": payload.provider, "ok": payload.ok},
    )
    return payload


@router.post("/ollama-list-models", response_model=AnalyticsOllamaModelsPayload)
async def analytics_ollama_list_models(body: LlmProbeRequestBody) -> AnalyticsOllamaModelsPayload:
    """List all model names from the effective Ollama daemon (``GET /api/tags``) for Settings UI."""

    settings = effective_analytics_llm_settings(gui=body.gui_llm_overlay)
    if settings.analytics_llm_provider != "ollama":
        raise HTTPException(
            status_code=400,
            detail="Model listing is only available when analytics_llm_provider is ollama.",
        )
    root = normalize_ollama_base_url(settings.ollama_base_url)
    logger.info(
        "analytics_api_ollama_list_models_request",
        extra={"gui_overlay": body.gui_llm_overlay is not None},
    )
    try:
        names = await ollama_list_model_names(base_url=root, timeout_s=20.0)
    except OllamaHttpError as exc:
        logger.warning("analytics_api_ollama_list_models_error", extra={"detail": str(exc)[:500]})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.info("analytics_api_ollama_list_models_ok", extra={"model_count": len(names)})
    return AnalyticsOllamaModelsPayload(base_url=root, models=names)


@router.post("/ollama-report", response_model=OllamaReportPayload)
async def analytics_ollama_report(body: OllamaReportBody) -> OllamaReportPayload:
    """Macro LLM brief via configured backend (cached in ``analytics_llm_cache.json``)."""
    path = _resolve_dir(body.output_dir)
    logger.info(
        "analytics_api_ollama_report_request",
        extra={
            "folder": path.name,
            "force_refresh": body.force_refresh,
            "gui_overlay": body.gui_llm_overlay is not None,
        },
    )
    settings = effective_analytics_llm_settings(gui=body.gui_llm_overlay)
    try:
        payload = await generate_ollama_macro_report(
            path, settings=settings, force_refresh=body.force_refresh
        )
        logger.info(
            "analytics_api_ollama_report_ok",
            extra={
                "folder": path.name,
                "from_cache": payload.from_cache,
                "theme_count": len(payload.brief.themes),
            },
        )
        return payload
    except ValueError as exc:
        logger.warning(
            "analytics_api_ollama_report_bad_request",
            extra={"folder": path.name, "detail": str(exc)[:300]},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmTransportError as exc:
        logger.warning(
            "analytics_api_ollama_report_llm_error",
            extra={"folder": path.name, "detail": str(exc)[:500]},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class OllamaReportCheckResponse(BaseModel):
    has_cached_brief: bool = Field(description="True if a valid cached brief exists for this folder")
    cache_path: str = Field(description="Absolute path to the cache file")
    model: str | None = Field(None, description="Model used for cached brief if available")
    generated_at: str | None = Field(None, description="ISO timestamp when cached brief was generated")


@router.post("/ollama-report-check", response_model=OllamaReportCheckResponse)
async def analytics_ollama_report_check(body: OllamaReportBody) -> OllamaReportCheckResponse:
    """Check if a cached macro LLM brief exists without generating one.

    Use this endpoint to determine whether to auto-load a cached brief
    or wait for user action to generate a new one.
    """
    from youtube_scrape.application.analytics_ollama_report import _CACHE_NAME, _read_cache

    path = _resolve_dir(body.output_dir)
    cache_path = path / _CACHE_NAME

    settings = effective_analytics_llm_settings(gui=body.gui_llm_overlay)
    model = settings.analytics_llm_model_label()

    cached = _read_cache(cache_path)
    has_cache = cached is not None and cached.model == model

    return OllamaReportCheckResponse(
        has_cached_brief=has_cache,
        cache_path=str(cache_path),
        model=cached.model if cached else None,
        generated_at=cached.generated_at if cached else None,
    )


@router.post("/chat", response_model=AnalyticsChatResponse)
async def analytics_chat(body: AnalyticsChatRequestBody) -> AnalyticsChatResponse:
    """Conversational Q&A grounded in scraped artifacts under ``output_dir``."""

    path = _resolve_dir(body.output_dir)
    logger.info(
        "analytics_api_chat_request",
        extra={"folder": path.name, "turns": len(body.messages), "gui_overlay": body.gui_llm_overlay is not None},
    )
    try:
        result = await run_analytics_llm_chat(
            path,
            messages=body.messages,
            gui_overlay=body.gui_llm_overlay,
        )
        logger.info("analytics_api_chat_ok", extra={"folder": path.name, "chars": len(result.assistant)})
        return result
    except ValueError as exc:
        logger.warning(
            "analytics_api_chat_bad_request",
            extra={"folder": path.name, "detail": str(exc)[:240]},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmTransportError as exc:
        logger.warning(
            "analytics_api_chat_llm_error",
            extra={"folder": path.name, "detail": str(exc)[:500]},
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/rag-status", response_model=RagStatusPayload)
async def analytics_rag_status(body: AnalyticsOutputDirBody) -> RagStatusPayload:
    """Get RAG vectorization status for a scrape output folder."""
    path = _resolve_dir(body.output_dir)
    logger.info("analytics_api_rag_status_request", extra={"folder": path.name})
    status = get_rag_status(path)
    logger.info(
        "analytics_api_rag_status_ok",
        extra={
            "folder": path.name,
            "is_vectorized": status["is_vectorized"],
            "chunk_count": status["chunk_count"],
        },
    )
    return RagStatusPayload.model_validate(status)


async def _run_rag_build_job(
    job_id: str,
    output_dir: Path,
    embed_model: str,
    base_url: str,
    timeout_s: float,
    force_refresh: bool,
) -> None:
    """Background task to build RAG index with WebSocket progress."""
    jobs = get_job_store()
    manager = get_websocket_manager()

    # Initialize job
    jobs[job_id] = {
        "id": job_id,
        "status": "running",
        "progress": 0,
        "type": "rag_build",
        "output_dir": str(output_dir),
        "started_at": datetime.utcnow().isoformat(),
        "logs": [],
    }

    try:
        result = await build_rag_index_with_progress(
            output_dir,
            embed_model=embed_model,
            base_url=base_url,
            timeout_s=timeout_s,
            job_id=job_id,
            manager=manager,
            force_refresh=force_refresh,
        )

        job = jobs[job_id]
        if result.get("success"):
            job["status"] = "completed"
            job["progress"] = 100
            job["completed_at"] = datetime.utcnow().isoformat()
            job["result"] = result
        else:
            job["status"] = "failed"
            job["progress"] = 100
            job["error"] = result.get("error", "Unknown error")
            job["completed_at"] = datetime.utcnow().isoformat()
            job["result"] = result

    except Exception as exc:
        logger.exception("analytics_api_rag_build_job_failed")
        job = jobs[job_id]
        job["status"] = "failed"
        job["error"] = str(exc)
        job["progress"] = 100
        job["completed_at"] = datetime.utcnow().isoformat()
        await manager.send_status(job_id, "failed", {"error": str(exc)})


@router.post("/rag-build", response_model=RagBuildResponse)
async def analytics_rag_build(
    body: RagBuildRequest,
    background_tasks: BackgroundTasks,
) -> RagBuildResponse:
    """Trigger RAG vectorization build for a scrape output folder.

    Returns a job_id for WebSocket progress tracking via /ws/progress/{job_id}.
    """
    path = _resolve_dir(body.output_dir)

    # Check RAG eligibility
    settings = effective_analytics_llm_settings(gui=body.gui_llm_overlay)
    if not (settings.analytics_rag_enabled and settings.analytics_llm_provider == "ollama"):
        raise HTTPException(
            status_code=400,
            detail="RAG is not enabled or provider is not Ollama. Enable analytics_rag_enabled with ollama provider.",
        )

    # Check if there's data to vectorize
    status = get_rag_status(path)
    if status["has_download_only"]:
        raise HTTPException(
            status_code=400,
            detail="This folder contains only downloaded media (no scrape data). Run a scrape with video/comments/transcript options first.",
        )
    if not status["eligible_sources"]:
        raise HTTPException(
            status_code=400,
            detail="No eligible scrape data found for vectorization. Run a scrape first.",
        )

    # Check if already up-to-date (unless force refresh)
    if not body.force_refresh and status["is_vectorized"]:
        manifest_path = rag_manifest_path(path)
        if manifest_path.is_file():
            import json
            try:
                man = json.loads(manifest_path.read_text(encoding="utf-8"))
                requested_model = settings.ollama_embed_model or "nomic-embed-text"
                manifest_model = man.get("embed_model")
                if isinstance(manifest_model, str) and model_matches_installed(requested_model, [manifest_model]):
                    return RagBuildResponse(
                        job_id="",
                        output_dir=body.output_dir,
                        status="started",
                        message="RAG index is already up to date (use force_refresh to rebuild)",
                    )
            except Exception:
                pass

    job_id = f"rag-{uuid.uuid4().hex[:8]}"
    logger.info(
        "analytics_api_rag_build_request",
        extra={
            "folder": path.name,
            "job_id": job_id,
            "embed_model": settings.ollama_embed_model,
            "force_refresh": body.force_refresh,
        },
    )

    background_tasks.add_task(
        _run_rag_build_job,
        job_id=job_id,
        output_dir=path,
        embed_model=settings.ollama_embed_model or "nomic-embed-text",
        base_url=settings.ollama_base_url,
        timeout_s=settings.ollama_timeout_s,
        force_refresh=body.force_refresh,
    )

    return RagBuildResponse(
        job_id=job_id,
        output_dir=body.output_dir,
        status="started",
        message="RAG index build started. Connect to WebSocket for progress.",
    )


def _scan_output_dirs_for_global_status() -> list[RagGlobalStatusItem]:
    """Scan all configured output roots for videos and their RAG status."""
    roots = output_roots_from_env()
    items: list[RagGlobalStatusItem] = []

    for root in roots:
        if not root.is_dir():
            continue
        for subdir in root.iterdir():
            if not subdir.is_dir():
                continue
            # Skip hidden dirs
            if subdir.name.startswith("."):
                continue

            status = get_rag_status(subdir)

            # Try to get video info from video.json
            video_id: str | None = None
            title: str | None = None
            video_json_path = subdir / "video.json"
            if video_json_path.is_file():
                try:
                    import json
                    data = json.loads(video_json_path.read_text(encoding="utf-8"))
                    inner = data.get("data", {}) if isinstance(data.get("data"), dict) else data
                    video_id = inner.get("video_id") or inner.get("id")
                    title = inner.get("title")
                except Exception:
                    pass

            # Use folder name as fallback
            if not video_id:
                video_id = subdir.name

            has_scrape_data = bool(status["eligible_sources"])

            items.append(RagGlobalStatusItem(
                output_dir=str(subdir),
                video_id=video_id,
                title=title,
                is_vectorized=status["is_vectorized"],
                chunk_count=status["chunk_count"],
                embed_model=status["embed_model"],
                last_updated=status["last_updated"],
                has_scrape_data=has_scrape_data,
            ))

    return items


@router.post("/rag-global-status", response_model=RagGlobalStatusPayload)
async def analytics_rag_global_status() -> RagGlobalStatusPayload:
    """Get global RAG vectorization status for all videos."""
    logger.info("analytics_api_rag_global_status_request")
    items = _scan_output_dirs_for_global_status()

    total = len(items)
    vectorized = sum(1 for i in items if i.is_vectorized)
    download_only = sum(1 for i in items if not i.has_scrape_data)

    logger.info(
        "analytics_api_rag_global_status_ok",
        extra={
            "total": total,
            "vectorized": vectorized,
            "pending": total - vectorized - download_only,
            "download_only": download_only,
        },
    )

    return RagGlobalStatusPayload(
        videos=items,
        total_count=total,
        vectorized_count=vectorized,
        pending_count=total - vectorized - download_only,
        download_only_count=download_only,
    )
