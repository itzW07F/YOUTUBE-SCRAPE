"""Analytics RAG chunking, store, and cosine retrieval."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from youtube_scrape.application.analytics_rag_store import (
    clear_and_insert,
    cosine_similarity,
    load_all_chunks,
    top_cosine,
)
from youtube_scrape.application.analytics_scrape_rag import (
    collect_rag_chunks,
    compute_source_fingerprints,
    get_rag_status,
    _has_download_only,
    _detect_available_sources,
)
from youtube_scrape.application.gallery_metadata_refresh import resolve_output_dir_for_refresh

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "analytics"


def test_cosine_similarity_unit() -> None:
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-6
    assert cosine_similarity(a, [0.0, 1.0, 0.0]) < 1e-6


def test_sqlite_roundtrip_and_top_k(tmp_path: Path) -> None:
    db = tmp_path / "x" / "chunks.sqlite3"
    rows = [
        ("t", "a", "hello", [1.0, 0.0, 0.0]),
        ("t", "b", "world", [0.0, 1.0, 0.0]),
    ]
    clear_and_insert(db, rows)
    loaded = load_all_chunks(db)
    assert len(loaded) == 2
    tops = top_cosine([0.9, 0.1, 0.0], loaded, k=1)
    assert len(tops) == 1
    assert tops[0][0] == "t" and tops[0][1] == "a"


@pytest.fixture
def rag_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    sub = tmp_path / "ragvid01"
    sub.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "video.json", sub / "video.json")
    shutil.copy(FIXTURE_DIR / "comments.json", sub / "comments.json")
    (sub / "transcript.txt").write_text("line one\nline two\nline three\n", encoding="utf-8")
    root = resolve_output_dir_for_refresh(str(sub), [tmp_path.resolve()])
    return root


def test_collect_rag_chunks_includes_sections(rag_output: Path) -> None:
    warns: list[str] = []
    chunks = collect_rag_chunks(rag_output, warns)
    kinds = {c[0] for c in chunks}
    assert "video" in kinds
    assert "transcript" in kinds
    assert "comment" in kinds


def test_fingerprint_changes_when_file_updates(rag_output: Path) -> None:
    a = compute_source_fingerprints(rag_output)
    (rag_output / "transcript.txt").write_text("changed\n", encoding="utf-8")
    b = compute_source_fingerprints(rag_output)
    assert a.get("transcript.txt") != b.get("transcript.txt")


def test_build_scrape_mini_header_smoke(rag_output: Path) -> None:
    from youtube_scrape.application.analytics_scrape_context_pack import build_scrape_mini_header

    w: list[str] = []
    h = build_scrape_mini_header(rag_output, w)
    assert "title:" in h.lower() or "video_id:" in h.lower()


# Tests for RAG status checking (Vector DB feature)

def test_detect_available_sources_finds_scrape_files(tmp_path: Path) -> None:
    """Should detect scrape artifacts in output folder."""
    sub = tmp_path / "testvid"
    sub.mkdir()
    (sub / "video.json").write_text('{"test": true}', encoding="utf-8")
    (sub / "comments.json").write_text('{"comments": []}', encoding="utf-8")
    (sub / "transcript.txt").write_text("test transcript", encoding="utf-8")

    available, missing = _detect_available_sources(sub)

    assert "video.json" in available
    assert "comments.json" in available
    assert "transcript.txt" in available
    assert "metadata_history.jsonl" in missing


def test_has_download_only_detects_yt_dlp_only(tmp_path: Path) -> None:
    """Should detect folders with only download artifacts (no scrape data)."""
    # Download-only folder
    download_only = tmp_path / "download_only"
    download_only.mkdir()
    (download_only / "download").mkdir()

    assert _has_download_only(download_only) is True

    # Scrape folder with download
    scrape_with_download = tmp_path / "scrape_with_download"
    scrape_with_download.mkdir()
    (scrape_with_download / "download").mkdir()
    (scrape_with_download / "video.json").write_text('{"test": true}', encoding="utf-8")

    assert _has_download_only(scrape_with_download) is False

    # Scrape folder without download
    scrape_only = tmp_path / "scrape_only"
    scrape_only.mkdir()
    (scrape_only / "video.json").write_text('{"test": true}', encoding="utf-8")

    assert _has_download_only(scrape_only) is False


def test_get_rag_status_not_vectorized(tmp_path: Path) -> None:
    """Should return correct status for non-vectorized folder."""
    sub = tmp_path / "novid"
    sub.mkdir()
    (sub / "video.json").write_text(json.dumps({
        "data": {"metadata": {"video_id": "test123", "title": "Test Video"}}
    }), encoding="utf-8")
    (sub / "comments.json").write_text('{"comments": []}', encoding="utf-8")

    status = get_rag_status(sub)

    assert status["is_vectorized"] is False
    assert status["chunk_count"] == 0
    assert status["embed_model"] is None
    assert status["has_download_only"] is False
    # Vector DB only tracks video.json and comments.json
    assert "video.json" in status["eligible_sources"]
    assert "comments.json" in status["eligible_sources"]
    # Other files like transcript.txt are not tracked for Vector DB


def test_get_rag_status_vectorized(tmp_path: Path) -> None:
    """Should return correct status for vectorized folder."""
    sub = tmp_path / "vecvid"
    sub.mkdir()
    (sub / "video.json").write_text(json.dumps({
        "data": {"metadata": {"video_id": "vec123", "title": "Vectorized Video"}}
    }), encoding="utf-8")

    # Create RAG artifacts
    rag_dir = sub / ".analytics_rag"
    rag_dir.mkdir()
    (rag_dir / "chunks.sqlite3").write_bytes(b"fake db")
    (rag_dir / "manifest.json").write_text(json.dumps({
        "rag_schema_version": "2",
        "sources": {"video.json": "abc123"},
        "embed_model": "nomic-embed-text",
        "chunk_count": 42,
        "embed_dim": 768,
    }), encoding="utf-8")

    status = get_rag_status(sub)

    assert status["is_vectorized"] is True
    assert status["chunk_count"] == 42
    assert status["embed_model"] == "nomic-embed-text"
    assert status["embed_dim"] == 768
    assert status["has_download_only"] is False


def test_get_rag_status_download_only(tmp_path: Path) -> None:
    """Should correctly identify download-only folders."""
    sub = tmp_path / "dlonly"
    sub.mkdir()
    download_dir = sub / "download"
    download_dir.mkdir()
    (download_dir / "video.mp4").write_text("fake video", encoding="utf-8")

    status = get_rag_status(sub)

    assert status["is_vectorized"] is False
    assert status["chunk_count"] == 0
    assert status["has_download_only"] is True
    assert status["eligible_sources"] == []


@pytest.mark.asyncio
async def test_build_rag_index_with_progress_success(tmp_path: Path) -> None:
    """Test build_rag_index_with_progress with mocked Ollama."""
    from youtube_scrape.application.analytics_scrape_rag import build_rag_index_with_progress

    sub = tmp_path / "buildtest"
    sub.mkdir()
    (sub / "video.json").write_text(json.dumps({
        "data": {"metadata": {"video_id": "build123", "title": "Build Test"}}
    }), encoding="utf-8")

    # Mock WebSocket manager
    manager = MagicMock()
    manager.send_progress = AsyncMock()
    manager.send_status = AsyncMock()

    # Mock ollama_embed_prompt to return fake vectors
    with patch("youtube_scrape.application.analytics_scrape_rag.ollama_embed_prompt") as mock_embed:
        mock_embed.return_value = [0.1, 0.2, 0.3, 0.4]

        result = await build_rag_index_with_progress(
            sub,
            embed_model="nomic-embed-text",
            base_url="http://localhost:11434",
            timeout_s=30.0,
            job_id="test-job-123",
            manager=manager,
            force_refresh=True,
        )

    assert result["success"] is True
    assert result["chunk_count"] > 0
    assert result["embed_model"] == "nomic-embed-text"

    # Verify WebSocket calls
    assert manager.send_progress.called
    assert manager.send_status.called


@pytest.mark.asyncio
async def test_build_rag_index_with_progress_no_chunks(tmp_path: Path) -> None:
    """Test build with no eligible chunks."""
    from youtube_scrape.application.analytics_scrape_rag import build_rag_index_with_progress

    sub = tmp_path / "emptytest"
    sub.mkdir()
    # No scrape files - only download folder
    (sub / "download").mkdir()

    manager = MagicMock()
    manager.send_progress = AsyncMock()
    manager.send_status = AsyncMock()

    result = await build_rag_index_with_progress(
        sub,
        embed_model="nomic-embed-text",
        base_url="http://localhost:11434",
        timeout_s=30.0,
        job_id="test-job-empty",
        manager=manager,
        force_refresh=True,
    )

    assert result["success"] is False
    assert "No text chunks found" in result["error"]
