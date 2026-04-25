"""Configuration management for youtube-scrape.

Provides a centralized configuration system with file-based defaults
and CLI override support. The hierarchy is:

1. CLI arguments (highest priority)
2. Config file values
3. Environment variables
4. Built-in defaults (lowest priority)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticUndefined
import yaml

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATHS = [
    Path("~/.config/youtube-scrape/config.yaml").expanduser(),
    Path("~/.config/youtube-scrape/config.yml").expanduser(),
    Path("~/.config/youtube-scrape/config.json").expanduser(),
    Path("youtube-scrape.yaml"),
    Path("youtube-scrape.yml"),
    Path("youtube-scrape.json"),
]


class OutputConfig(BaseModel):
    """Output formatting and destination settings."""

    schema_version: str = Field(default="1", description="Schema version for output JSON.")
    directory: Path = Field(default=Path("output"), description="Default output directory.")
    write_metadata_json: bool = Field(default=True, description="Write metadata JSON files.")
    create_subdirectories: bool = Field(default=True, description="Create video-id subdirectories.")


class BrowserConfig(BaseModel):
    """Browser/Camoufox behavior settings."""

    headless: bool = Field(default=True, description="Run browser headlessly.")
    timeout_s: float = Field(default=45.0, ge=1.0, description="Browser operation timeout.")
    reuse_context: bool = Field(default=True, description="Reuse browser across operations.")
    user_data_dir: Path | None = Field(default=None, description="Persistent browser profile directory.")
    proxy_server: str | None = Field(default=None, description="Proxy server URL.")
    page_settle_after_load_ms: int = Field(default=0, ge=0, le=30000, description="Wait after page load.")
    humanize: bool = Field(default=True, description="Human-like mouse movements.")
    preroll_skip_budget_s: float = Field(default=55.0, ge=0.0, le=180.0, description="Max seconds to wait for ad skip.")


class HttpConfig(BaseModel):
    """HTTP client settings."""

    timeout_s: float = Field(default=30.0, ge=1.0, description="HTTP request timeout.")
    max_retries: int = Field(default=3, ge=1, le=10, description="HTTP retry attempts.")


class CommentsConfig(BaseModel):
    """Comment scraping configuration."""

    enabled: bool = Field(default=True, description="Scrape comments.")
    max_comments: int | None = Field(default=100, ge=1, description="Max comments to fetch (null = unlimited).")
    fetch_all: bool = Field(default=False, description="Fetch until exhaustion (with safety ceiling).")
    include_replies: bool = Field(default=True, description="Include reply comments.")
    max_replies_per_thread: int | None = Field(default=3, ge=0, description="Max replies per thread (null = unlimited).")
    safety_ceiling: int = Field(default=50000, ge=1, description="Hard cap to prevent runaway scraping.")


class TranscriptConfig(BaseModel):
    """Transcript/caption settings."""

    enabled: bool = Field(default=True, description="Download transcripts.")
    language: str | None = Field(default=None, description="Preferred language code (null = auto).")
    fmt: Literal["txt", "vtt", "json"] = Field(default="txt", description="Output format.")
    fallback_languages: list[str] = Field(default_factory=list, description="Fallback language codes.")


class ThumbnailsConfig(BaseModel):
    """Thumbnail download settings."""

    enabled: bool = Field(default=True, description="Download thumbnails.")
    max_variants: int | None = Field(default=None, ge=1, description="Max variants to download (null = all).")
    write_image_files: bool = Field(default=True, description="Write actual image files (not just metadata).")


class DownloadConfig(BaseModel):
    """Video/audio download settings."""

    enabled: bool = Field(default=False, description="Download video/audio.")
    format: Literal["best", "worst"] | int = Field(default="best", description="Format selector (best/worst/itag).")
    stream: Literal["video", "audio"] = Field(default="video", description="Video or audio-only.")
    audio_encoding: Literal["container", "mp3"] = Field(default="container", description="Audio format.")
    experimental_fallback: bool = Field(default=False, description="Allow experimental fallback if yt-dlp fails.")
    max_bytes: int | None = Field(default=None, ge=1, description="Max bytes to download (for testing).")
    name_from_title: bool = Field(default=False, description="Name files from video title.")


class VideoMetadataConfig(BaseModel):
    """Video metadata scraping options."""

    enabled: bool = Field(default=True, description="Scrape video metadata.")
    include_format_preview: bool = Field(default=True, description="Include available format list.")
    include_caption_tracks: bool = Field(default=True, description="Include caption track list.")


class BatchConfig(BaseModel):
    """Batch processing settings."""

    fail_fast: bool = Field(default=False, description="Stop on first failure.")
    max_failures_before_breaker: int = Field(default=5, ge=1, description="Circuit breaker threshold.")
    default_mode: Literal["video", "comments", "transcript"] = Field(default="video", description="Default batch mode.")


class LoggingConfig(BaseModel):
    """Logging settings."""

    level: str = Field(default="INFO", description="Logging level.")
    format: str = Field(default="%(levelname)s %(name)s %(message)s", description="Log format string.")


class ScrapeConfig(BaseModel):
    """Complete configuration for youtube-scrape.

    This is the single source of truth for all scraping options.
    CLI arguments override these values.
    """

    # Global settings
    output: OutputConfig = Field(default_factory=OutputConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    http: HttpConfig = Field(default_factory=HttpConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Feature-specific settings
    video: VideoMetadataConfig = Field(default_factory=VideoMetadataConfig)
    comments: CommentsConfig = Field(default_factory=CommentsConfig)
    transcript: TranscriptConfig = Field(default_factory=TranscriptConfig)
    thumbnails: ThumbnailsConfig = Field(default_factory=ThumbnailsConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)

    # Batch settings
    batch: BatchConfig = Field(default_factory=BatchConfig)

    @field_validator("logging")
    @classmethod
    def uppercase_log_level(cls, v: LoggingConfig) -> LoggingConfig:
        v.level = v.level.upper()
        return v

    @classmethod
    def from_file(cls, path: Path) -> ScrapeConfig:
        """Load configuration from YAML or JSON file."""
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        content = path.read_text(encoding="utf-8")

        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        elif path.suffix == ".json":
            data = json.loads(content)
        else:
            raise ValueError(f"Unsupported config format: {path.suffix}. Use .yaml, .yml, or .json")

        return cls.model_validate(data)

    @classmethod
    def find_and_load(cls, explicit_path: Path | None = None) -> ScrapeConfig:
        """Find and load config file from default locations or explicit path.

        Raises:
            FileNotFoundError: If no config file is found.
        """
        if explicit_path:
            if explicit_path.exists():
                log.info(f"Loading config from: {explicit_path}")
                return cls.from_file(explicit_path)
            raise FileNotFoundError(
                f"Config file not found at explicit path: {explicit_path}\n"
                f"Please create a config file or specify a valid path with --config"
            )

        for path in DEFAULT_CONFIG_PATHS:
            if path.exists():
                log.info(f"Loading config from: {path}")
                return cls.from_file(path)

        # No config file found - this is an error
        searched = "\n  - ".join([str(p) for p in DEFAULT_CONFIG_PATHS])
        raise FileNotFoundError(
            f"No configuration file found.\n\n"
            f"Searched in:\n  - {searched}\n\n"
            f"To fix this:\n"
            f"  1. Copy the example config: cp config-example.yaml youtube-scrape.yaml\n"
            f"  2. Or create at: ~/.config/youtube-scrape/config.yaml\n"
            f"  3. Or specify explicitly: --config /path/to/config.yaml"
        )

    def merge_with_cli(
        self,
        **cli_overrides: object,
    ) -> ScrapeConfig:
        """Create a new config with CLI overrides applied.

        Only applies overrides that are not None (i.e., were explicitly set on CLI).
        """
        # Convert to dict for manipulation
        data = self.model_dump()

        # Mapping of CLI arg names to config paths
        # Format: cli_arg_name -> (section, key)
        CLI_MAPPING: dict[str, tuple[str, ...]] = {
            # Global/Browser
            "headless": ("browser", "headless"),
            "browser_timeout": ("browser", "timeout_s"),
            "reuse_browser": ("browser", "reuse_context"),
            "user_data_dir": ("browser", "user_data_dir"),
            "proxy": ("browser", "proxy_server"),
            "schema_version": ("output", "schema_version"),
            "log_level": ("logging", "level"),
            "http_timeout": ("http", "timeout_s"),
            # Comments
            "max_comments": ("comments", "max_comments"),
            "all": ("comments", "fetch_all"),
            "include_replies": ("comments", "include_replies"),
            "max_replies_per_thread": ("comments", "max_replies_per_thread"),
            # Transcript
            "language": ("transcript", "language"),
            "fmt": ("transcript", "fmt"),
            # Thumbnails
            "max_variants": ("thumbnails", "max_variants"),
            # Download
            "format": ("download", "format"),
            "stream": ("download", "stream"),
            "audio_encoding": ("download", "audio_encoding"),
            "experimental_download": ("download", "experimental_fallback"),
            "max_bytes": ("download", "max_bytes"),
            "name_from_title": ("download", "name_from_title"),
            # Batch
            "fail_fast": ("batch", "fail_fast"),
            "mode": ("batch", "default_mode"),
        }

        for cli_name, value in cli_overrides.items():
            if value is None:
                continue  # Not set on CLI
            if cli_name not in CLI_MAPPING:
                continue  # Unknown CLI arg

            path = CLI_MAPPING[cli_name]
            # Navigate to nested dict and set value
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value

        return self.model_validate(data)

    def get_output_path(self, video_id: str, suffix: str | None = None) -> Path:
        """Generate output path for a video."""
        base = self.output.directory

        if self.output.create_subdirectories:
            base = base / video_id

        base.mkdir(parents=True, exist_ok=True)

        if suffix:
            return base / f"{video_id}{suffix}"
        return base