"""Typed payloads for local analytics over scrape artifacts (no HTTP imports)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MetadataHistoryPoint(BaseModel):
    """One append-only row from ``metadata_history.jsonl``."""

    captured_at: str
    video_id: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    dislike_count: int | None = None
    comment_count: int | None = None


class VideoMetricsSummary(BaseModel):
    """Latest snapshot from ``video.json`` envelope when present."""

    video_id: str | None = None
    title: str | None = None
    channel_title: str | None = None
    description: str | None = None
    published_at: str | None = None
    view_count: int | None = None
    like_count: int | None = None
    dislike_count: int | None = None
    comment_count: int | None = None
    duration_seconds: int | None = None


class CommentVolumeBucket(BaseModel):
    bucket_start: str
    count: int


class LikeCountBucket(BaseModel):
    label: str
    count: int


class AuthorAggregate(BaseModel):
    author: str
    comment_count: int
    total_likes: int | None = Field(
        default=None,
        description="Sum of comment like_count when numeric; None if no numeric likes in corpus.",
    )


class KeywordTerm(BaseModel):
    term: str
    count: int


class CommentStats(BaseModel):
    total_flat: int
    top_level_count: int | None = None
    reply_count: int | None = None
    with_published_at: int
    volume_by_day: list[CommentVolumeBucket] = Field(default_factory=list)
    like_buckets: list[LikeCountBucket] = Field(default_factory=list)
    top_authors: list[AuthorAggregate] = Field(default_factory=list)


class AnalyticsSnapshot(BaseModel):
    """Versioned deterministic analytics for one scrape output folder."""

    schema_version: Literal["1"] = "1"
    output_dir: str
    video_metrics: VideoMetricsSummary | None = None
    metadata_history: list[MetadataHistoryPoint] = Field(default_factory=list)
    metadata_history_points: int = Field(
        default=0,
        description="Count of parsed history rows (for UX: trends need multiple refreshes).",
    )
    comments_file_present: bool = False
    comment_stats: CommentStats | None = None
    keywords: list[KeywordTerm] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class OllamaMacroBrief(BaseModel):
    """Structured macro synthesis; LLM output must validate against this shape."""

    themes: list[str] = Field(default_factory=list)
    sentiment_overview: str = ""
    suggestions_and_requests: str = ""
    complaints_and_criticism: str = ""
    agreements_and_disagreements: str = ""
    notable_quotes: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


AnalyticsGuiProvider = Literal["ollama", "openai_compatible", "anthropic", "google_gemini"]


class GuiAnalyticsLlmOverlay(BaseModel):
    """Optional snapshot from Electron (same knobs as Settings / spawn env).

    Applied on top of ``Settings()`` so Analytics works without restarting the Python
    API after GUI changes (remote Ollama URL, provider, keys, …).
    """

    model_config = ConfigDict(extra="ignore")

    analytics_llm_provider: AnalyticsGuiProvider | None = None
    analytics_ollama_enabled: bool | None = None
    ollama_base_url: str | None = None
    ollama_model: str | None = None
    openai_compatible_base_url: str | None = None
    openai_compatible_api_key: str | None = None
    openai_compatible_model: str | None = None
    anthropic_base_url: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    google_gemini_api_key: str | None = None
    google_gemini_model: str | None = None
    analytics_rag_enabled: bool | None = None
    analytics_rag_top_k: int | None = None
    ollama_embed_model: str | None = None


class AnalyticsLlmProbePayload(BaseModel):
    """Result of ``POST /analytics/llm-probe`` (connectivity sanity check)."""

    ok: bool
    provider: str
    message: str
    models_sample: list[str] | None = None


class AnalyticsOllamaModelsPayload(BaseModel):
    """Result of ``POST /analytics/ollama-list-models`` (full tag list for GUI dropdown)."""

    base_url: str = Field(description="Normalized Ollama daemon base URL used for /api/tags.")
    models: list[str] = Field(default_factory=list)


class MacroBriefTiming(BaseModel):
    """Wall-clock phases for ``POST /analytics/ollama-report`` (milliseconds, server-side)."""

    total_ms: int = Field(..., ge=0, description="End-to-end time for this handler (excluding HTTP client overhead).")
    rag_resolve_ms: int = Field(default=0, ge=0, description="Hybrid RAG pack resolution (embed + retrieve + merge).")
    digest_build_ms: int = Field(default=0, ge=0, description="Stratified digest build when not using RAG context.")
    ensure_ready_ms: int = Field(default=0, ge=0, description="Provider readiness probe (e.g. Ollama model check).")
    llm_main_ms: int = Field(default=0, ge=0, description="Primary structured JSON generation call.")
    llm_repair_ms: int = Field(default=0, ge=0, description="JSON repair pass after a parse failure.")
    llm_refill_ms: int = Field(default=0, ge=0, description="Refill pass when the brief parsed but was empty.")
    llm_plain_ms: int = Field(default=0, ge=0, description="Plain JSON fallback (no response_format) when needed.")
    llm_plain_repair_ms: int = Field(default=0, ge=0, description="Repair after plain fallback parse failure.")


class OllamaReportPayload(BaseModel):
    """API response body for ``/analytics/ollama-report``."""

    schema_version: Literal["1"] = "1"
    output_dir: str
    model: str
    generated_at: str
    from_cache: bool
    comment_digest_meta: dict[str, Any] = Field(default_factory=dict)
    brief: OllamaMacroBrief
    macro_brief_timing: MacroBriefTiming | None = Field(
        default=None,
        description="Server-side latency breakdown; omitted only on older clients (always set by current API).",
    )


class AnalyticsChatMessage(BaseModel):
    """One conversational turn exposed to ``/analytics/chat`` (no synthetic priming pairs)."""

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=32_000)


class AnalyticsChatRequestBody(BaseModel):
    """Body for conversational analytics over scraped artifacts."""

    output_dir: str = Field(..., description="Absolute path to a scrape output folder under configured roots")
    messages: list[AnalyticsChatMessage] = Field(
        ...,
        min_length=1,
        description="Odd-length transcript ending in user — alternating user then assistant.",
    )
    gui_llm_overlay: GuiAnalyticsLlmOverlay | None = Field(
        default=None,
        description="Same optional GUI snapshot used by other Analytics LLM routes.",
    )


class AnalyticsChatResponse(BaseModel):
    """Natural-language assistant reply grounded in scraped context."""

    schema_version: Literal["1"] = "1"
    assistant: str
    warnings: list[str] = Field(default_factory=list)
    provider: str
    model: str
    llm_latency_ms: int = Field(
        ...,
        ge=0,
        description="Wall-clock time for the upstream LLM request (milliseconds).",
    )
    scrape_bundle_chars: int = Field(
        ...,
        ge=0,
        description="Character length of the scrape text bundle injected into chat (excluding priming wording).",
    )
    estimated_scrape_bundle_tokens: int = Field(
        ...,
        ge=0,
        description="Rough token estimate from scrape_bundle_chars÷4 — not tokenizer-accurate.",
    )
    estimated_request_prompt_tokens: int = Field(
        ...,
        ge=0,
        description="Rough token estimate from full system+conversation payload chars÷4.",
    )
    prompt_tokens: int | None = Field(
        default=None,
        description="Provider-native prompt/input token count when returned by the API.",
    )
    completion_tokens: int | None = Field(
        default=None,
        description="Provider-native completion/output token count when returned by the API.",
    )
    total_tokens: int | None = Field(
        default=None,
        description="Provider-native total token count when returned (or summed when inferable).",
    )
    analytics_rag_mode: Literal["legacy", "hybrid", "fallback_meta"] | None = Field(
        default=None,
        description="legacy = full scrape bundle; hybrid = header + retrieved excerpts; fallback_meta = metadata-only when RAG fails.",
    )
    analytics_rag_chunks_used: int | None = Field(
        default=None,
        description="Chunks inserted into the priming payload when mode=hybrid.",
    )
    analytics_rag_index_build_ms: int | None = Field(
        default=None,
        ge=0,
        description="Wall time to build or rebuild the on-disk RAG index for this request (0 when reused).",
    )
    analytics_rag_embed_ms: int | None = Field(
        default=None,
        ge=0,
        description="Wall time for query embedding(s) on this request when mode=hybrid.",
    )


class AnalyticsLlmCacheFile(BaseModel):
    """On-disk cache next to scrape artifacts."""

    comment_set_sha256: str
    model: str
    brief_schema_version: str
    generated_at: str
    brief: OllamaMacroBrief
    macro_context_mode: str = Field(
        default="comment_sample",
        description="comment_sample = stratified comment digest; rag_hybrid = Vector DB retrieval context.",
    )


class RagStatusPayload(BaseModel):
    """Status of RAG vectorization for a scrape output folder."""

    schema_version: Literal["1"] = "1"
    output_dir: str
    is_vectorized: bool
    chunk_count: int = 0
    embed_model: str | None = None
    embed_dim: int | None = None
    last_updated: str | None = None
    eligible_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    has_download_only: bool = False


class RagBuildRequest(BaseModel):
    """Request to trigger RAG vectorization build."""

    output_dir: str = Field(..., description="Absolute path to a scrape output folder")
    force_refresh: bool = Field(default=False, description="Force rebuild even if index is up to date")
    gui_llm_overlay: GuiAnalyticsLlmOverlay | None = Field(
        default=None,
        description="Optional GUI snapshot for Ollama settings (embed model, base URL)",
    )


class RagBuildResponse(BaseModel):
    """Response after triggering RAG build."""

    schema_version: Literal["1"] = "1"
    job_id: str
    output_dir: str
    status: Literal["started", "failed"]
    message: str


class RagGlobalStatusItem(BaseModel):
    """Vectorization status for one video in the global view."""

    output_dir: str
    video_id: str | None = None
    title: str | None = None
    is_vectorized: bool
    chunk_count: int = 0
    embed_model: str | None = None
    last_updated: str | None = None
    has_scrape_data: bool = True


class RagGlobalStatusPayload(BaseModel):
    """Global view of vectorization status across all videos."""

    schema_version: Literal["1"] = "1"
    videos: list[RagGlobalStatusItem] = Field(default_factory=list)
    total_count: int = 0
    vectorized_count: int = 0
    pending_count: int = 0
    download_only_count: int = 0
