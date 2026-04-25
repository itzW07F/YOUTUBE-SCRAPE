import json
from pathlib import Path
from typing import Any

import pytest

from youtube_scrape.adapters.filesystem import LocalFileSink
from youtube_scrape.application.scrape_thumbnails import ScrapeThumbnailsService
from youtube_scrape.domain.ports import BrowserSession
from youtube_scrape.settings import Settings


class _StubHttp:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def get_text(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        raise NotImplementedError

    async def get_bytes(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> bytes:
        self.urls.append(url)
        _ = headers
        _ = max_bytes
        return b"fake-image"

    async def post_json(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class _StubBrowser:
    def __init__(self, player: dict[str, Any]) -> None:
        self._player = player

    async def extract_watch_payload(self, watch_url: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        _ = watch_url
        return self._player, {}, "<html></html>"

    async def fetch_text_in_watch_context(self, watch_url: str, resource_url: str) -> str:
        _ = (watch_url, resource_url)
        return ""


@pytest.mark.asyncio
async def test_scrape_thumbnails_writes_files(tmp_path: Path) -> None:
    raw = Path(__file__).parent / "fixtures" / "player_response_min.json"
    player = json.loads(raw.read_text(encoding="utf-8"))
    settings = Settings()
    http = _StubHttp()
    files = LocalFileSink()
    browser: BrowserSession = _StubBrowser(player)  # type: ignore[assignment]
    svc = ScrapeThumbnailsService(browser=browser, http=http, files=files, settings=settings)
    out_dir = tmp_path / "thumbs"
    env = await svc.scrape("dQw4w9WgXcQ", out_dir=out_dir, max_variants=2)
    assert env.kind == "thumbnails"
    assert env.data["count"] == 2
    paths = [Path(str(s["path"])) for s in env.data["saved"]]  # type: ignore[index]
    assert all(p.exists() for p in paths)
    assert len(http.urls) == 2
