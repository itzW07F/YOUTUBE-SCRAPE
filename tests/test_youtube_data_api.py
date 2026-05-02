"""Tests for YouTube Data API adapter and reference route."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# `api.*` resolves from `src/youtube_scrape` (same layout as uvicorn "api.server:app").
_pkg_root = Path(__file__).resolve().parents[1] / "src" / "youtube_scrape"
_pre = str(_pkg_root.resolve())
if _pre not in sys.path:
    sys.path.insert(0, _pre)

import httpx
import pytest
from fastapi.testclient import TestClient

from api.server import app
from youtube_scrape.adapters.youtube_data_api import YouTubeDataApiError, _parse_json_response
from youtube_scrape.application.youtube_data_api_scrape import (
    _metadata_from_videos_item,
    parse_youtube_content_duration,
)


def test_parse_youtube_content_duration() -> None:
    assert parse_youtube_content_duration("PT1H2M3S") == 3600 + 120 + 3
    assert parse_youtube_content_duration("PT45S") == 45
    assert parse_youtube_content_duration(None) is None
    assert parse_youtube_content_duration("invalid") is None


def test_metadata_from_videos_item_maps_snippet() -> None:
    item = {
        "snippet": {
            "title": "Hello",
            "channelId": "UCx",
            "channelTitle": "Ch",
            "description": "Desc",
            "publishedAt": "2020-01-02T15:04:05Z",
            "tags": ["a", "b"],
            "categoryId": "22",
            "thumbnails": {
                "default": {"url": "https://i.ytimg.com/vi/x/default.jpg", "width": 120, "height": 90},
            },
        },
        "statistics": {"viewCount": "10", "likeCount": "2", "commentCount": "5"},
        "contentDetails": {"duration": "PT1M"},
        "status": {"lifeCycleStatus": "live"},
    }
    meta = _metadata_from_videos_item("vid123", item)
    assert meta.video_id == "vid123"
    assert meta.title == "Hello"
    assert meta.channel_id == "UCx"
    assert meta.view_count == 10
    assert meta.duration_seconds == 60
    assert meta.is_live is True
    assert len(meta.thumbnails) >= 1


def test_parse_json_response_http_error() -> None:
    resp = httpx.Response(
        403,
        json={"error": {"message": "The request cannot be completed...", "errors": [{"reason": "forbidden"}]}},
    )
    with pytest.raises(YouTubeDataApiError) as ei:
        _parse_json_response(resp, context="videos.list")
    assert ei.value.status_code == 403
    assert "forbidden" in str(ei.value).lower() or "403" in str(ei.value)


def test_reference_discovery_route_mocked() -> None:
    fake_doc = {
        "title": "YouTube Data API v3",
        "id": "youtube:v3",
        "version": "v3",
        "revision": "20250101",
    }
    with patch("api.routes.reference.fetch_discovery_document", new_callable=AsyncMock, return_value=fake_doc):
        client = TestClient(app)
        r = client.get("/reference/youtube-data-api/discovery")
    assert r.status_code == 200
    data = r.json()
    assert data["revision"] == "20250101"
    assert data["title"] == "YouTube Data API v3"
    assert "fetched_at" in data
