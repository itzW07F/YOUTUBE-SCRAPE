"""Analytics contextual chat assembly and orchestration."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from youtube_scrape.application.analytics_llm_chat import run_analytics_llm_chat
from youtube_scrape.application.analytics_scrape_context_pack import build_scrape_context_pack
from youtube_scrape.application.gallery_metadata_refresh import resolve_output_dir_for_refresh
from youtube_scrape.domain.analytics_models import AnalyticsChatMessage

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "analytics"


@pytest.fixture
def analytics_output_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    sub = tmp_path / "abc123xyz01"
    sub.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "video.json", sub / "video.json")
    shutil.copy(FIXTURE_DIR / "comments.json", sub / "comments.json")
    shutil.copy(FIXTURE_DIR / "metadata_history.jsonl", sub / "metadata_history.jsonl")
    resolved = resolve_output_dir_for_refresh(str(sub), [tmp_path.resolve()])
    assert resolved == sub.resolve()
    return resolved


def test_build_scrape_context_pack_fixture_hits_main_sections(analytics_output_chat: Path) -> None:
    pack = build_scrape_context_pack(analytics_output_chat, max_chars=80_000)
    assert "## video.json" in pack.text
    assert "## comments" in pack.text
    assert "## metadata_history.jsonl" in pack.text


def test_build_scrape_context_pack_truncation_warns(analytics_output_chat: Path) -> None:
    pack = build_scrape_context_pack(analytics_output_chat, max_chars=900)
    assert pack.warnings


def test_build_scrape_context_pack_prefers_txt_transcript(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    sub = tmp_path / "tid"
    sub.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "video.json", sub / "video.json")
    (sub / "transcript.json").write_text('{"only":"json_here"}', encoding="utf-8")
    (sub / "transcript.txt").write_text("hello_txt_transcript_anchor", encoding="utf-8")
    root = resolve_output_dir_for_refresh(str(sub), [tmp_path.resolve()])
    pack = build_scrape_context_pack(root, max_chars=20_000)
    assert "hello_txt_transcript_anchor" in pack.text
    assert "## transcript" in pack.text


@pytest.mark.asyncio
async def test_run_analytics_llm_chat_prepends_bundle_and_prim(
    monkeypatch: pytest.MonkeyPatch, analytics_output_chat: Path
) -> None:
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_OLLAMA_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_RAG_ENABLED", "false")

    mock_backend = AsyncMock()

    def fake_builder(_settings: object) -> AsyncMock:
        return mock_backend

    monkeypatch.setattr("youtube_scrape.application.analytics_llm_chat.build_analytics_llm", fake_builder)

    from youtube_scrape.adapters.llm_chat_types import LlmChatResult

    mock_backend.chat_messages = AsyncMock(
        return_value=LlmChatResult(
            content="  anchored answer  ",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
    )

    result = await run_analytics_llm_chat(
        analytics_output_chat,
        messages=[AnalyticsChatMessage(role="user", content="What is the tone?")],
        gui_overlay=None,
    )

    assert result.assistant == "anchored answer"
    assert isinstance(result.provider, str)
    assert result.model
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 20
    assert result.total_tokens == 30
    assert result.scrape_bundle_chars > 500
    assert result.estimated_scrape_bundle_tokens == result.scrape_bundle_chars // 4
    assert result.estimated_request_prompt_tokens >= result.estimated_scrape_bundle_tokens
    assert result.llm_latency_ms >= 0

    mock_backend.ensure_ready.assert_awaited_once()
    kwargs = mock_backend.chat_messages.await_args.kwargs
    assert kwargs["json_format"] is False
    msgs = kwargs["messages"]
    assert msgs[0]["role"] == "user"
    assert "## video.json" in msgs[0]["content"]
    assert msgs[1]["role"] == "assistant"
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"] == "What is the tone?"


@pytest.mark.asyncio
async def test_run_analytics_llm_chat_hybrid_rag_priming(
    monkeypatch: pytest.MonkeyPatch, analytics_output_chat: Path
) -> None:
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_OLLAMA_ENABLED", "true")
    monkeypatch.setenv("YOUTUBE_SCRAPE_ANALYTICS_RAG_ENABLED", "true")

    async def fake_hybrid(*_a: object, **_k: object):
        from youtube_scrape.application.analytics_scrape_context_pack import ScrapeContextPack

        return (
            ScrapeContextPack(
                text="# Scraped data (retrieval-assisted)\n\nhello-rag",
                warnings=["rag-warning"],
            ),
            {
                "analytics_rag_mode": "hybrid",
                "analytics_rag_chunks_used": 2,
                "analytics_rag_index_build_ms": 9,
                "analytics_rag_embed_ms": 3,
            },
        )

    monkeypatch.setattr(
        "youtube_scrape.application.analytics_llm_chat.try_resolve_hybrid_context_pack",
        fake_hybrid,
    )
    mock_backend = AsyncMock()

    def fake_builder(_settings: object) -> AsyncMock:
        return mock_backend

    monkeypatch.setattr("youtube_scrape.application.analytics_llm_chat.build_analytics_llm", fake_builder)
    from youtube_scrape.adapters.llm_chat_types import LlmChatResult

    mock_backend.chat_messages = AsyncMock(
        return_value=LlmChatResult(
            content="ok",
            prompt_tokens=1,
            completion_tokens=2,
            total_tokens=3,
        )
    )

    result = await run_analytics_llm_chat(
        analytics_output_chat,
        messages=[AnalyticsChatMessage(role="user", content="Q?")],
        gui_overlay=None,
    )
    assert "retrieval-assisted" in mock_backend.chat_messages.await_args.kwargs["messages"][0]["content"]
    assert result.analytics_rag_mode == "hybrid"
    assert result.analytics_rag_chunks_used == 2
    assert result.analytics_rag_index_build_ms == 9
    assert result.analytics_rag_embed_ms == 3
    assert "rag-warning" in result.warnings


@pytest.mark.asyncio
async def test_run_analytics_llm_chat_rejects_bad_alternation(analytics_output_chat: Path) -> None:
    with pytest.raises(ValueError, match="must be"):
        await run_analytics_llm_chat(
            analytics_output_chat,
            messages=[AnalyticsChatMessage(role="assistant", content="illegal lead")],
        )


def test_comments_digest_substitution_when_json_too_large(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    sub = tmp_path / "huge_comments"
    sub.mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "video.json", sub / "video.json")

    rows = []
    for i in range(800):
        rows.append(
            {
                "comment_id": f"c{i}",
                "author": "a",
                "text": "body" + ("x" * 240),
                "like_count": i % 44,
                "is_reply": False,
                "replies": [],
            }
        )
    env = {
        "schema_version": "1",
        "kind": "comments",
        "data": {"video_id": "vid", "comments": rows},
    }
    (sub / "comments.json").write_text(json.dumps(env), encoding="utf-8")

    root = resolve_output_dir_for_refresh(str(sub), [tmp_path.resolve()])
    pack = build_scrape_context_pack(root, max_chars=5_500)
    assert any("digest" in w.lower() for w in pack.warnings)


def test_openai_compat_usage_sums_prompt_and_completion_when_total_missing() -> None:
    from youtube_scrape.adapters.llm_usage_extract import openai_compat_usage_counts

    pt, ct, tt = openai_compat_usage_counts({"usage": {"prompt_tokens": 2, "completion_tokens": 5}})
    assert (pt, ct, tt) == (2, 5, 7)
