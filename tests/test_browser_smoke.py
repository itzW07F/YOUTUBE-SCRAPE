import os

import pytest

pytestmark = pytest.mark.browser


@pytest.mark.asyncio
async def test_smoke_watch_page_load() -> None:
    if os.environ.get("RUN_BROWSER_TESTS") != "1":
        pytest.skip("Set RUN_BROWSER_TESTS=1 to run browser smoke tests.")
    from youtube_scrape.adapters.browser_playwright import CamoufoxBrowserSession
    from youtube_scrape.settings import Settings

    settings = Settings(headless=True, browser_timeout_s=60.0)
    browser = CamoufoxBrowserSession(settings)
    try:
        player, initial, html = await browser.extract_watch_payload("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    finally:
        await browser.aclose()
    assert "videoDetails" in player
    assert isinstance(html, str)
    assert isinstance(initial, dict)
