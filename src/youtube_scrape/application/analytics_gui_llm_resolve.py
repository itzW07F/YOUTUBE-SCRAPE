"""Merge GUI overlays into typed Settings for analytics LLM endpoints."""

from __future__ import annotations

from youtube_scrape.adapters.ollama_client import normalize_ollama_base_url
from youtube_scrape.domain.analytics_models import GuiAnalyticsLlmOverlay
from youtube_scrape.settings import Settings


def effective_analytics_llm_settings(
    *,
    gui: GuiAnalyticsLlmOverlay | None = None,
) -> Settings:
    """Load Settings from env / .env then apply optional Electron GUI snapshot."""

    base = Settings()
    if gui is None:
        return base
    patch = gui.model_dump(exclude_none=True)
    if not patch:
        return base
    if "ollama_base_url" in patch:
        ub = patch.get("ollama_base_url")
        if isinstance(ub, str):
            patch["ollama_base_url"] = normalize_ollama_base_url(ub)
    return base.model_copy(update=patch)
