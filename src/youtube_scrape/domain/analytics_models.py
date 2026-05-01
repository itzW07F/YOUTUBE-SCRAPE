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


class AnalyticsLlmProbePayload(BaseModel):
    """Result of ``POST /analytics/llm-probe`` (connectivity sanity check)."""

    ok: bool
    provider: str
    message: str
    models_sample: list[str] | None = None


class OllamaReportPayload(BaseModel):
    """API response body for ``/analytics/ollama-report``."""

    schema_version: Literal["1"] = "1"
    output_dir: str
    model: str
    generated_at: str
    from_cache: bool
    comment_digest_meta: dict[str, Any] = Field(default_factory=dict)
    brief: OllamaMacroBrief


class AnalyticsLlmCacheFile(BaseModel):
    """On-disk cache next to scrape artifacts."""

    comment_set_sha256: str
    model: str
    brief_schema_version: str
    generated_at: str
    brief: OllamaMacroBrief
