"""Single source of truth for configuration (env + CLI overrides)."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AnalyticsLlmProvider = Literal["ollama", "openai_compatible", "anthropic", "google_gemini"]


class Settings(BaseSettings):
    """Application settings loaded from environment and defaults."""

    model_config = SettingsConfigDict(
        env_prefix="YOUTUBE_SCRAPE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = Field(default="INFO", description="Python logging level name.")
    headless: bool = Field(default=True)
    browser_timeout_s: float = Field(default=45.0, ge=1.0)
    http_timeout_s: float = Field(default=30.0, ge=1.0)
    media_download_timeout_s: float = Field(
        default=900.0,
        ge=60.0,
        description="Longer timeout for full media GET (httpx + Playwright) when not using --max-bytes.",
    )
    max_navigation_retries: int = Field(default=3, ge=1, le=10)
    navigation_backoff_s: float = Field(default=1.5, ge=0.1)
    http_max_retries: int = Field(default=3, ge=1, le=10)
    batch_max_failures_before_breaker: int = Field(
        default=5,
        ge=1,
        description="Optional circuit breaker: stop batch after N consecutive hard failures.",
    )
    comments_safety_ceiling: int = Field(
        default=50_000,
        ge=1,
        description="Hard cap for --all to prevent runaway continuation loops.",
    )
    output_schema_version: str = Field(default="1")
    user_data_dir: Path | None = Field(default=None)
    browser_reuse_context: bool = Field(
        default=True,
        description="Reuse one Camoufox instance across steps in the same session (extract + media GET share cookies).",
    )
    proxy_server: str | None = Field(default=None)
    page_settle_after_load_ms: int = Field(
        default=0,
        ge=0,
        le=30_000,
        description=(
            "Extra wait (ms) after watch navigation; combined with watch_page_comments_hydration_ms "
            "via max(...) for scroll/hydrate budget."
        ),
    )
    watch_page_comments_hydration_ms: int = Field(
        default=12_000,
        ge=0,
        le=30_000,
        description=(
            "Scroll/wait budget so ytd-comments-header-renderer hydrates; needed because ytInitialData "
            "often omits numeric comment totals until the panel loads."
        ),
    )
    camoufox_humanize: bool = Field(
        default=True,
        description="Enable Camoufox humanized pointer movement (used when clicking Skip on preroll ads).",
    )
    youtube_preroll_ad_skip_budget_s: float = Field(
        default=55.0,
        ge=0.0,
        le=180.0,
        description="Max seconds to poll for skippable YouTube preroll after each watch navigation.",
    )
    ffmpeg_repair_dash_fragment: bool = Field(
        default=False,
        description=(
            "After experimental download, if output looks like a DASH fMP4 fragment, try ffmpeg -c copy "
            "remux to a sibling .repaired.mp4 (best-effort; may still fail if init is missing)."
        ),
    )
    fetch_ryd_vote_counts: bool = Field(
        default=True,
        description=(
            "If YouTube omits dislike_count, GET Return YouTube Dislike `/votes` "
            "(see returnyoutubedislike.com/docs/fetching). "
            "Adds network hop; toggle off for fully offline scraping."
        ),
    )
    ryd_api_base_url: str = Field(
        default="https://returnyoutubedislikeapi.com",
        description="Base URL only; `/votes` is appended by the client.",
    )
    ryd_timeout_s: float = Field(default=5.0, ge=0.5, le=120.0, description="Timeout for optional RYD fetch.")
    max_concurrent_scrape_jobs: int = Field(
        default=2,
        ge=1,
        le=16,
        description=(
            "How many scrape jobs run their browser pipeline concurrently. "
            "Additional jobs wait until a slot frees (limits Camoufox/CPU load)."
        ),
    )
    ffmpeg_threads: int = Field(
        default=0,
        ge=0,
        le=64,
        description="If > 0, pass -threads N to FFmpeg for MP3/remux helpers (0 = omit, FFmpeg default/auto).",
    )
    analytics_ollama_enabled: bool = Field(
        default=True,
        description="Allow /analytics/ollama-report to call a local Ollama server (disable for strict offline/API-only).",
    )
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        description="Base URL for local Ollama (no trailing slash).",
    )
    ollama_model: str = Field(
        default="gpt-oss:20b",
        description='Model name/tag passed to Ollama /api/chat (must exist locally; try `ollama list`).',
    )
    ollama_timeout_s: float = Field(default=180.0, ge=10.0, le=900.0, description="HTTP timeout for LLM calls.")

    analytics_llm_provider: AnalyticsLlmProvider = Field(
        default="ollama",
        description="Which backend serves /analytics/ollama-report and /analytics/llm-probe.",
    )
    openai_compatible_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible API root (includes /v1). No trailing slash.",
    )
    openai_compatible_api_key: str = Field(
        default="",
        description="Bearer token for OpenAI-compatible APIs (omit for no-auth gateways).",
    )
    openai_compatible_model: str = Field(default="gpt-4o-mini", description="chat/completions model id.")
    anthropic_api_key: str = Field(default="", description="Anthropic API key.")
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com",
        description="Anthropic API host (no path).",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Messages API model id.",
    )
    google_gemini_api_key: str = Field(default="", description="Google AI Studio / Gemini API key.")
    google_gemini_model: str = Field(
        default="gemini-2.0-flash",
        description="Model id for generateContent (e.g. gemini-2.0-flash).",
    )

    @field_validator("log_level")
    @classmethod
    def log_level_upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("ollama_base_url")
    @classmethod
    def ollama_base_url_has_scheme(cls, v: str) -> str:
        from youtube_scrape.adapters.ollama_client import normalize_ollama_base_url

        return normalize_ollama_base_url(v)

    def analytics_llm_model_label(self) -> str:
        """Model id used for analytics cache keys and API responses."""

        mapping: dict[AnalyticsLlmProvider, str] = {
            "ollama": self.ollama_model,
            "openai_compatible": self.openai_compatible_model,
            "anthropic": self.anthropic_model,
            "google_gemini": self.google_gemini_model,
        }
        return mapping[self.analytics_llm_provider]
