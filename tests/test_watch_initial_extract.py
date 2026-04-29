"""Tests for engagement_count_parse and watch_initial_extract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from youtube_scrape.domain.engagement_count_parse import parse_engagement_count_text
from youtube_scrape.domain.models import VideoMetadata
from youtube_scrape.domain.watch_initial_extract import (
    enrich_video_metadata_from_initial,
    extract_like_dislike_from_vpir,
    find_video_primary_info_renderer,
)


def test_parse_engagement_count_text_basic() -> None:
    assert parse_engagement_count_text("12,500 likes") == 12500
    assert parse_engagement_count_text("Liked by 1.2K people") == 1200
    assert parse_engagement_count_text("Dislike this video") is None
    assert parse_engagement_count_text(None) is None


def test_watch_initial_enrichment_fills_likes_and_date() -> None:
    raw = Path(__file__).parent / "fixtures" / "initial_data_watch_primary.json"
    initial = json.loads(raw.read_text(encoding="utf-8"))
    vpir = find_video_primary_info_renderer(initial)
    assert vpir is not None
    like_n, dislike_n = extract_like_dislike_from_vpir(vpir)
    assert like_n == 12500
    assert dislike_n is None
    base = VideoMetadata(video_id="x", like_count=None, published_at=None, published_text=None)
    rich = enrich_video_metadata_from_initial(
        base,
        initial,
        now_utc=datetime(2025, 4, 29, 12, 0, 0, tzinfo=UTC),
    )
    assert rich.like_count == 12500
    assert rich.published_text == "Apr 28, 2025"
    assert rich.published_at is not None


def test_enrichment_does_not_override_player_values() -> None:
    raw = Path(__file__).parent / "fixtures" / "initial_data_watch_primary.json"
    initial = json.loads(raw.read_text(encoding="utf-8"))
    existing = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
    base = VideoMetadata(
        video_id="x",
        like_count=99,
        published_at=existing,
        published_text="already",
    )
    rich = enrich_video_metadata_from_initial(base, initial, now_utc=datetime.now(UTC))
    assert rich.like_count == 99
    assert rich.published_at == existing
    assert rich.published_text == "already"
