"""Analytics endpoints over local scrape artifacts."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from youtube_scrape.adapters.llm_errors import LlmTransportError
from youtube_scrape.adapters.llm_providers import probe_analytics_llm
from youtube_scrape.application.analytics_gui_llm_resolve import effective_analytics_llm_settings
from youtube_scrape.application.analytics_ollama_report import generate_ollama_macro_report
from youtube_scrape.application.analytics_snapshot import build_analytics_snapshot
from youtube_scrape.application.gallery_metadata_refresh import output_roots_from_env, resolve_output_dir_for_refresh
from youtube_scrape.domain.analytics_models import (
    AnalyticsLlmProbePayload,
    AnalyticsSnapshot,
    GuiAnalyticsLlmOverlay,
    OllamaReportPayload,
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
