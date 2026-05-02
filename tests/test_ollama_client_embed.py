"""Unit coverage for adaptive Ollama embedding requests (/api/embed + CPU fallback)."""

from __future__ import annotations

from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest

from youtube_scrape.adapters.ollama_client import OllamaHttpError, ollama_embed_prompt


@pytest.mark.asyncio
async def test_ollama_embed_prefers_api_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, dict]] = []

    async def fake_o_post(
        *,
        client: AsyncMock,
        url: str,
        payload: dict,
    ):
        posted.append((url, dict(payload)))
        return 200, {"embeddings": [[0.1, -0.2, 0.3]]}, ""

    monkeypatch.setattr(
        "youtube_scrape.adapters.ollama_client._ollama_post_embedding_json",
        fake_o_post,
    )

    v = await ollama_embed_prompt(
        base_url="http://127.0.0.1:11434",
        model="nomic-test",
        prompt="hello",
        timeout_s=30.0,
        client=AsyncMock(),
    )
    assert len(v) == 3
    assert v[0] == pytest.approx(0.1)
    assert "/api/embed" in posted[0][0]
    assert posted[0][1].get("input") == "hello"


@pytest.mark.asyncio
async def test_ollama_embed_retries_cpu_when_gpu_reports_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seq = iter(
        [
            (500, {}, 'model exists but failed to load on GPU'),
            (200, {"embeddings": [[0.0, 1.0, 2.5]]}, ""),
        ]
    )

    async def fake_o_post(**kwargs):
        _ = kwargs
        return next(seq)

    monkeypatch.setattr(
        "youtube_scrape.adapters.ollama_client._ollama_post_embedding_json",
        fake_o_post,
    )

    v = await ollama_embed_prompt(
        base_url="http://localhost:11434/",
        model="nomic-test",
        prompt="hi",
        timeout_s=30.0,
        client=AsyncMock(),
    )
    assert v[1] == pytest.approx(1.0)
    assert v[2] == pytest.approx(2.5)


@pytest.mark.asyncio
async def test_ollama_embed_falls_back_to_legacy_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    async def fake_o_post(
        *,
        client: AsyncMock,
        url: str,
        payload: dict,
    ):
        path = urlparse(url).path.rstrip("/")
        urls.append(url)
        if path.endswith("/embeddings"):
            return 200, {"embedding": [4.0, 5.0]}, ""
        if path.endswith("/embed"):
            return 404, {}, "no such endpoint on this daemon"
        raise AssertionError(f"unexpected embedding URL path: {url!r}")
    monkeypatch.setattr(
        "youtube_scrape.adapters.ollama_client._ollama_post_embedding_json",
        fake_o_post,
    )

    v = await ollama_embed_prompt(
        base_url="127.0.0.1:11434",
        model="m",
        prompt="text",
        timeout_s=20.0,
        client=AsyncMock(),
    )
    assert v == [pytest.approx(4.0), pytest.approx(5.0)]
    assert urls[0].endswith("/api/embed")
    assert urls[-1].endswith("/api/embeddings")


@pytest.mark.asyncio
async def test_ollama_embed_pull_missing_raises_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_o_post(**kwargs):
        _ = kwargs
        return (
            404,
            {},
            'model "nomic-test:latest" not found, try pulling it first',
        )

    monkeypatch.setattr(
        "youtube_scrape.adapters.ollama_client._ollama_post_embedding_json",
        fake_o_post,
    )

    with pytest.raises(OllamaHttpError) as exc_info:
        await ollama_embed_prompt(
            base_url="http://localhost:11434",
            model="nomic-test:latest",
            prompt="?",
            timeout_s=5.0,
            client=AsyncMock(),
        )
    msg = str(exc_info.value).lower()
    assert "pull" in msg
    assert "nomic-test" in msg
