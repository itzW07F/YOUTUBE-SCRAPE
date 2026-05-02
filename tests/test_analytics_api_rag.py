"""Tests for Analytics RAG API endpoints (rag-status, rag-build, rag-global-status).

These tests use mocked dependencies to avoid import path issues.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Setup OUTPUT_DIR and mock settings for testing."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("YOUTUBE_SCRAPE_OLLAMA_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_RAG_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_LLM_PROVIDER", "ollama")
    return tmp_path


def test_get_rag_status_function(mock_settings_env: Path) -> None:
    """Test the get_rag_status function directly."""
    from youtube_scrape.application.analytics_scrape_rag import get_rag_status

    # Create a test output folder
    output_dir = mock_settings_env / "testvid123"
    output_dir.mkdir()
    (output_dir / "video.json").write_text(json.dumps({
        "data": {"metadata": {"video_id": "test123", "title": "Test"}}
    }), encoding="utf-8")

    status = get_rag_status(output_dir)

    assert status["is_vectorized"] is False
    assert status["chunk_count"] == 0
    assert "video.json" in status["eligible_sources"]
    assert status["has_download_only"] is False


def test_get_rag_status_vectorized(mock_settings_env: Path) -> None:
    """Test get_rag_status returns correct data for vectorized folder."""
    from youtube_scrape.application.analytics_scrape_rag import get_rag_status

    output_dir = mock_settings_env / "vecvid456"
    output_dir.mkdir()
    (output_dir / "video.json").write_text(json.dumps({
        "data": {"metadata": {"video_id": "vec456", "title": "Vectorized"}}
    }), encoding="utf-8")

    # Create RAG artifacts
    rag_dir = output_dir / ".analytics_rag"
    rag_dir.mkdir()
    (rag_dir / "chunks.sqlite3").write_bytes(b"fake")
    (rag_dir / "manifest.json").write_text(json.dumps({
        "rag_schema_version": "2",
        "sources": {"video.json": "hash123"},
        "embed_model": "nomic-embed-text",
        "chunk_count": 5,
        "embed_dim": 768,
    }), encoding="utf-8")

    status = get_rag_status(output_dir)

    assert status["is_vectorized"] is True
    assert status["chunk_count"] == 5
    assert status["embed_model"] == "nomic-embed-text"
    assert status["embed_dim"] == 768


def test_get_rag_status_download_only(mock_settings_env: Path) -> None:
    """Test get_rag_status correctly identifies download-only folders."""
    from youtube_scrape.application.analytics_scrape_rag import get_rag_status

    output_dir = mock_settings_env / "dlonly"
    output_dir.mkdir()
    (output_dir / "download").mkdir()
    (output_dir / "download" / "video.mp4").write_text("fake", encoding="utf-8")

    status = get_rag_status(output_dir)

    assert status["is_vectorized"] is False
    assert status["chunk_count"] == 0
    assert status["has_download_only"] is True
    assert status["eligible_sources"] == []


def test_pydantic_models_validation() -> None:
    """Test that Pydantic models validate correctly."""
    from youtube_scrape.domain.analytics_models import (
        RagStatusPayload,
        RagBuildRequest,
        RagBuildResponse,
        RagGlobalStatusItem,
        RagGlobalStatusPayload,
    )

    # Test RagStatusPayload
    status = RagStatusPayload(
        output_dir="/tmp/test",
        is_vectorized=True,
        chunk_count=42,
        embed_model="nomic-embed-text",
        embed_dim=768,
        eligible_sources=["video.json", "comments.json"],
        missing_sources=["transcript.txt"],
        has_download_only=False,
    )
    assert status.schema_version == "1"
    assert status.chunk_count == 42

    # Test RagBuildRequest
    request = RagBuildRequest(
        output_dir="/tmp/test",
        force_refresh=True,
    )
    assert request.force_refresh is True

    # Test RagBuildResponse
    response = RagBuildResponse(
        job_id="rag-abc123",
        output_dir="/tmp/test",
        status="started",
        message="Build started",
    )
    assert response.job_id == "rag-abc123"

    # Test RagGlobalStatusItem
    item = RagGlobalStatusItem(
        output_dir="/tmp/test",
        video_id="test123",
        title="Test Video",
        is_vectorized=True,
        chunk_count=10,
        embed_model="nomic-embed-text",
        has_scrape_data=True,
    )
    assert item.video_id == "test123"

    # Test RagGlobalStatusPayload
    payload = RagGlobalStatusPayload(
        videos=[item],
        total_count=1,
        vectorized_count=1,
        pending_count=0,
        download_only_count=0,
    )
    assert payload.total_count == 1


def test_detect_available_sources(mock_settings_env: Path) -> None:
    """Test _detect_available_sources function."""
    from youtube_scrape.application.analytics_scrape_rag import _detect_available_sources

    output_dir = mock_settings_env / "sourcetest"
    output_dir.mkdir()
    (output_dir / "video.json").write_text("{}", encoding="utf-8")
    (output_dir / "comments.json").write_text("{}", encoding="utf-8")

    available, missing = _detect_available_sources(output_dir)

    assert "video.json" in available
    assert "comments.json" in available
    assert "transcript.txt" in missing


def test_has_download_only(mock_settings_env: Path) -> None:
    """Test _has_download_only function."""
    from youtube_scrape.application.analytics_scrape_rag import _has_download_only

    # Download-only folder
    dl_only = mock_settings_env / "dlonly"
    dl_only.mkdir()
    (dl_only / "download").mkdir()
    assert _has_download_only(dl_only) is True

    # Scrape folder
    scrape = mock_settings_env / "scrape"
    scrape.mkdir()
    (scrape / "video.json").write_text("{}", encoding="utf-8")
    assert _has_download_only(scrape) is False
