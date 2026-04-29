"""Tests for engagement_count_parse and watch_initial_extract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from youtube_scrape.domain.engagement_count_parse import parse_engagement_count_text
from youtube_scrape.domain.models import VideoMetadata
from youtube_scrape.domain.watch_initial_extract import (
    DOM_COMMENT_COUNT_SCRATCH_KEY,
    enrich_video_metadata_from_initial,
    extract_like_dislike_from_vpir,
    extract_public_comment_count_from_initial,
    find_video_primary_info_renderer,
    parse_public_comment_total_from_heading_text,
)


def test_parse_engagement_count_text_basic() -> None:
    assert parse_engagement_count_text("12,500 likes") == 12500
    assert parse_engagement_count_text("Liked by 1.2K people") == 1200
    assert parse_engagement_count_text("9,999 Comments") == 9999
    assert parse_engagement_count_text("Dislike this video") is None
    assert parse_engagement_count_text(None) is None


def test_extract_comment_count_from_comment_count_simple_text() -> None:
    initial = {"commentCount": {"simpleText": "2.5K"}}
    assert extract_public_comment_count_from_initial(initial) == 2500


def test_extract_public_comment_count_from_initial_nested() -> None:
    raw = Path(__file__).parent / "fixtures" / "initial_data_watch_primary.json"
    initial = json.loads(raw.read_text(encoding="utf-8"))
    assert extract_public_comment_count_from_initial(initial) == 9999


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
    assert rich.comment_count == 9999
    assert rich.published_text == "Apr 28, 2025"
    assert rich.published_at is not None


def test_enrichment_does_not_override_like_or_date_but_prefers_watch_comment_total() -> None:
    raw = Path(__file__).parent / "fixtures" / "initial_data_watch_primary.json"
    initial = json.loads(raw.read_text(encoding="utf-8"))
    existing = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
    base = VideoMetadata(
        video_id="x",
        like_count=99,
        published_at=existing,
        published_text="already",
        comment_count=42,
    )
    rich = enrich_video_metadata_from_initial(base, initial, now_utc=datetime.now(UTC))
    assert rich.like_count == 99
    assert rich.published_at == existing
    assert rich.published_text == "already"
    assert extract_public_comment_count_from_initial(initial) == 9999
    assert rich.comment_count == 9999


def test_extract_prefers_comments_header_over_loose_comment_count() -> None:
    """Regression: DFS can surface unrelated ``commentCount`` before the comments header subtree."""
    initial = {
        "sidebar": {"commentCount": {"simpleText": "12"}},
        "contents": {
            "twoColumnWatchNextResults": {
                "results": {
                    "results": {
                        "contents": [
                            {
                                "itemSectionRenderer": {
                                    "contents": [
                                        {
                                            "commentsHeaderRenderer": {
                                                "countText": {
                                                    "runs": [{"text": "9,998"}, {"text": " Comments"}],
                                                },
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
            },
        },
    }
    assert extract_public_comment_count_from_initial(initial) == 9998


def test_parse_public_comment_total_from_heading_text() -> None:
    assert parse_public_comment_total_from_heading_text("2,434,618 Comments") == 2_434_618
    assert parse_public_comment_total_from_heading_text("Comments are turned off") is None


def test_enrich_prefers_dom_scratch_comment_total_over_ytinitial() -> None:
    """Hydrated DOM total wins; static ytInitialData can lack numbers in ``countText``."""
    initial = {
        DOM_COMMENT_COUNT_SCRATCH_KEY: 2_500_000,
        "sidebar": {"commentCount": {"simpleText": "12"}},
        "contents": {
            "twoColumnWatchNextResults": {
                "results": {
                    "results": {
                        "contents": [
                            {
                                "itemSectionRenderer": {
                                    "contents": [
                                        {
                                            "commentsHeaderRenderer": {
                                                "countText": {"runs": [{"text": "Comments"}]},
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                },
            },
        },
    }
    base = VideoMetadata(video_id="x", comment_count=None)
    rich = enrich_video_metadata_from_initial(base, initial, now_utc=datetime.now(UTC))
    assert rich.comment_count == 2_500_000


def test_primary_column_engagement_comment_label_text() -> None:
    """When header renderers are absent, scrape “N Comments” under engagement in the primary column."""
    initial = {
        "contents": {
            "twoColumnWatchNextResults": {
                "results": {
                    "results": {
                        "contents": [
                            {
                                "videoDummy": {
                                    "inlineLabel": {
                                        "simpleText": "4,210 Comments",
                                        "accessibility": {
                                            "accessibilityData": {"label": "4,210 comments"},
                                        },
                                    },
                                },
                            },
                        ],
                    },
                },
            },
        },
    }
    assert extract_public_comment_count_from_initial(initial) == 4210
