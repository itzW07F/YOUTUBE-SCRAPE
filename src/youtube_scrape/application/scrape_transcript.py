"""Application service: download and normalize captions."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree.ElementTree import ParseError

from camoufox.async_api import AsyncCamoufox

from youtube_scrape.adapters.browser_playwright import CamoufoxBrowserSession
from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.domain.captions_convert import (
    timedtext_json3_to_plain,
    timedtext_xml_to_plain,
    timedtext_xml_to_webvtt,
)
from youtube_scrape.domain.json_extract import extract_yt_initial_data, extract_yt_initial_player_response
from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.domain.player_parser import parse_caption_tracks, parse_video_metadata
from youtube_scrape.domain.ports import BrowserSession, HttpClient
from youtube_scrape.domain.youtube_url import watch_url
from youtube_scrape.exceptions import ExtractionError, NavigationError
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)

_JS_TIMEDTEXT_FETCH = """
async (url) => {
    const response = await fetch(url, { credentials: 'include' });
    if (!response.ok) {
        throw new Error('timedtext_fetch_status_' + response.status);
    }
    return await response.text();
}
"""


class ScrapeTranscriptService:
    """Fetch timedtext for the requested caption track."""

    def __init__(self, *, browser: BrowserSession, http: HttpClient, settings: Settings) -> None:
        self._browser = browser
        self._http = http
        self._settings = settings

    async def _fetch_nonempty_text(self, watch_page_url: str, resource_url: str) -> str:
        """Prefer browser-context GET (cookies), then plain HTTP fallback."""
        text = await self._browser.fetch_text_in_watch_context(watch_page_url, resource_url)
        if text.strip():
            return text
        return await self._http.get_text(resource_url)

    async def _caption_xml_body(self, watch_page_url: str, base_url: str) -> str:
        sep = "&" if "?" in base_url else "?"
        candidates: list[str] = []
        if "fmt=" not in base_url:
            candidates.append(f"{base_url}{sep}fmt=xml3")
        candidates.append(base_url)
        for candidate in candidates:
            text = await self._fetch_nonempty_text(watch_page_url, candidate)
            if text.strip():
                return text
        msg = "Timedtext endpoints returned empty bodies"
        raise ExtractionError(msg, details="empty_timedtext")

    async def _caption_plain_via_json3(self, watch_page_url: str, base_url: str) -> str:
        sep = "&" if "?" in base_url else "?"
        candidates: list[str] = []
        if "fmt=" not in base_url:
            candidates.extend(
                [
                    f"{base_url}{sep}fmt=json3",
                    f"{base_url}{sep}fmt=srv3",
                ]
            )
        candidates.append(base_url)
        for candidate in candidates:
            raw = await self._fetch_nonempty_text(watch_page_url, candidate)
            if not raw.strip():
                continue
            if raw.lstrip().startswith("<"):
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict) or "events" not in data:
                continue
            text = timedtext_json3_to_plain(data)
            if text:
                return text
        msg = "Could not parse srv3/JSON3 caption payload"
        raise ExtractionError(msg, details="caption_json3_failed")

    async def _page_try_fetch_timedtext(self, page: Any, url: str) -> str:
        """Run in-page fetch for one timedtext URL (same tab as watch page)."""
        try:
            return str(await page.evaluate(_JS_TIMEDTEXT_FETCH, url))
        except Exception:
            return ""

    @staticmethod
    def _timedtext_url_set_params(url: str, updates: dict[str, str]) -> str:
        parts = urlparse(url)
        merged = dict(parse_qsl(parts.query, keep_blank_values=True))
        merged.update(updates)
        new_query = urlencode(list(merged.items()))
        return urlunparse(parts._replace(query=new_query))

    async def _stimulate_timedtext_requests(self, page: Any) -> None:
        """Nudge the watch UI so the player issues timedtext calls (often includes ``pot``)."""
        try:
            await page.keyboard.press("c")
        except Exception:
            log.debug("caption_key_press_failed", exc_info=True)
        await asyncio.sleep(0.4)
        try:
            await page.evaluate(
                """() => {
                    const byAria = (s) => document.querySelector(`[aria-label="${s}"]`);
                    const show = byAria("Show transcript")
                        || [...document.querySelectorAll("button")].find((b) =>
                            /transcript/i.test(b.getAttribute("aria-label") || ""));
                    if (show) {
                        show.click();
                        return;
                    }
                    const panelBtn = document.querySelector(
                        "button.yt-spec-button-shape-next[aria-label*='Transcript']"
                    );
                    if (panelBtn) panelBtn.click();
                }"""
            )
        except Exception:
            log.debug("transcript_panel_click_failed", exc_info=True)

    def _body_from_network_timedtext(
        self,
        by_url: dict[str, str],
        *,
        language: str | None,
        fmt: Literal["txt", "vtt", "json"],
    ) -> Any | None:
        """If the player already fetched captions, reuse the richest captured payload."""
        json_texts: list[str] = []
        xml_texts: list[str] = []
        for url, text in by_url.items():
            if language and f"lang={language}" not in url:
                continue
            raw = text.strip()
            if not raw:
                continue
            if raw.startswith("{") and '"events"' in raw[:8000]:
                json_texts.append(raw)
            elif raw.startswith("<") or raw.startswith("<?xml"):
                xml_texts.append(raw)
        if fmt == "json":
            for js in json_texts:
                try:
                    return json.loads(js)
                except json.JSONDecodeError:
                    continue
            return None
        if fmt == "txt":
            for js in json_texts:
                try:
                    data = json.loads(js)
                except json.JSONDecodeError:
                    continue
                plain = timedtext_json3_to_plain(data) if isinstance(data, dict) else ""
                if str(plain).strip():
                    return plain
            for xml in xml_texts:
                try:
                    plain = timedtext_xml_to_plain(xml)
                except ParseError:
                    continue
                if str(plain).strip():
                    return plain
            return None
        for xml in xml_texts:
            try:
                return timedtext_xml_to_webvtt(xml)
            except ParseError:
                continue
        return None

    async def _scrape_transcript_camoufox_one_tab(
        self,
        watch_page_url: str,
        *,
        language: str | None,
        fmt: Literal["txt", "vtt", "json"],
    ) -> ResultEnvelope:
        """Load watch page once; reuse player timedtext traffic (PO token) where required."""
        cam = cast(CamoufoxBrowserSession, self._browser)
        kwargs = cam.camoufox_launch_kwargs()
        try:
            async with AsyncCamoufox(**kwargs) as browser:  # type: ignore[no-untyped-call]
                page = await browser.new_page()
                timedtext_by_url: dict[str, str] = {}
                loop = asyncio.get_running_loop()

                async def _grab_timedtext(response: Any) -> None:
                    try:
                        url = response.url
                        if "youtube.com/api/timedtext" not in url:
                            return
                        if response.status != 200:
                            return
                        text = await response.text()
                        if not text.strip():
                            return
                        prev = timedtext_by_url.get(url)
                        if prev is None or len(text) > len(prev):
                            timedtext_by_url[url] = text
                    except Exception:
                        return

                def _on_response(response: Any) -> None:
                    loop.create_task(_grab_timedtext(response))

                page.on("response", _on_response)
                try:
                    await page.goto(
                        watch_page_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._settings.browser_timeout_s * 1000),
                    )
                    await CamoufoxBrowserSession(self._settings)._post_goto_settle(page)
                    await asyncio.sleep(6.0)
                    await self._stimulate_timedtext_requests(page)
                    await asyncio.sleep(5.0)
                    await asyncio.sleep(1.5)
                    html = await page.content()
                    player = extract_yt_initial_player_response(html)
                    try:
                        _initial = extract_yt_initial_data(html)
                    except ExtractionError:
                        _initial = {}
                    _ = _initial
                    meta = parse_video_metadata(player)
                    tracks = parse_caption_tracks(player)
                    if not tracks:
                        msg = "No caption tracks available for this video"
                        raise ExtractionError(msg, details="no_caption_tracks")
                    chosen = None
                    if language:
                        for t in tracks:
                            if t.language_code == language:
                                chosen = t
                                break
                        if chosen is None:
                            msg = f"No caption track for language={language!r}"
                            raise ExtractionError(msg, details="language_not_found")
                    else:
                        chosen = tracks[0]
                    caption_url = str(chosen.base_url)
                    sep = "&" if "?" in caption_url else "?"

                    net_body = self._body_from_network_timedtext(
                        timedtext_by_url,
                        language=language,
                        fmt=fmt,
                    )
                    if net_body is not None:
                        body: str | dict[str, Any] = net_body
                    else:
                        pot_templates = sorted(
                            (u for u in timedtext_by_url if "pot=" in u),
                            key=len,
                            reverse=True,
                        )
                        body = None  # type: ignore[assignment]
                        if fmt == "json":
                            tried: list[str] = []
                            body_dict: dict[str, Any] | None = None
                            for tmpl in pot_templates:
                                for u in (
                                    self._timedtext_url_set_params(tmpl, {"fmt": "json3"}),
                                    tmpl,
                                ):
                                    if u in tried:
                                        continue
                                    tried.append(u)
                                    raw = await self._page_try_fetch_timedtext(page, u)
                                    if not raw.strip():
                                        continue
                                    try:
                                        parsed = json.loads(raw)
                                    except json.JSONDecodeError:
                                        continue
                                    if isinstance(parsed, dict):
                                        body_dict = parsed
                                        break
                                if body_dict is not None:
                                    break
                            if body_dict is not None:
                                body = body_dict
                            elif not isinstance(body, dict):
                                jurl = f"{caption_url}{sep}fmt=json3" if "fmt=" not in caption_url else caption_url
                                raw = await self._page_try_fetch_timedtext(page, jurl)
                                if not raw.strip():
                                    raw = await self._http.get_text(jurl)
                                if not raw.strip():
                                    msg = "Timedtext JSON endpoint returned an empty body"
                                    raise ExtractionError(msg, details="empty_timedtext_json")
                                body = json.loads(raw)
                        elif fmt == "txt":
                            body_str: str = ""
                            for tmpl in pot_templates:
                                for u in (
                                    self._timedtext_url_set_params(tmpl, {"fmt": "xml3"}),
                                    self._timedtext_url_set_params(tmpl, {"fmt": "json3"}),
                                    tmpl,
                                ):
                                    raw = await self._page_try_fetch_timedtext(page, u)
                                    if not raw.strip():
                                        continue
                                    if raw.lstrip().startswith("<"):
                                        try:
                                            body_str = timedtext_xml_to_plain(raw)
                                        except ParseError:
                                            body_str = ""
                                        if body_str.strip():
                                            break
                                    try:
                                        data = json.loads(raw)
                                    except json.JSONDecodeError:
                                        continue
                                    if isinstance(data, dict) and "events" in data:
                                        body_str = timedtext_json3_to_plain(data)
                                        if body_str.strip():
                                            break
                                if body_str.strip():
                                    break
                            if not body_str.strip():
                                xml_candidates: list[str] = []
                                if "fmt=" not in caption_url:
                                    xml_candidates.append(f"{caption_url}{sep}fmt=xml3")
                                xml_candidates.append(caption_url)
                                for u in xml_candidates:
                                    raw = await self._page_try_fetch_timedtext(page, u)
                                    if not raw.strip() or not raw.lstrip().startswith("<"):
                                        continue
                                    try:
                                        body_str = timedtext_xml_to_plain(raw)
                                    except ParseError:
                                        body_str = ""
                                    if body_str.strip():
                                        break
                                if not body_str.strip():
                                    json_candidates: list[str] = []
                                    if "fmt=" not in caption_url:
                                        json_candidates.extend(
                                            [
                                                f"{caption_url}{sep}fmt=json3",
                                                f"{caption_url}{sep}fmt=srv3",
                                            ]
                                        )
                                    json_candidates.append(caption_url)
                                    for u in json_candidates:
                                        raw = await self._page_try_fetch_timedtext(page, u)
                                        if not raw.strip() or raw.lstrip().startswith("<"):
                                            continue
                                        try:
                                            data = json.loads(raw)
                                        except json.JSONDecodeError:
                                            continue
                                        if isinstance(data, dict) and "events" in data:
                                            body_str = timedtext_json3_to_plain(data)
                                            if body_str.strip():
                                                break
                                if not body_str.strip():
                                    msg = "Could not load transcript text (XML or JSON3)"
                                    raise ExtractionError(msg, details="empty_transcript_one_tab")
                            body = body_str
                        else:
                            raw = ""
                            for tmpl in pot_templates:
                                for u in (
                                    self._timedtext_url_set_params(tmpl, {"fmt": "xml3"}),
                                    tmpl,
                                ):
                                    raw = await self._page_try_fetch_timedtext(page, u)
                                    if raw.strip().startswith("<") or raw.strip().startswith("<?xml"):
                                        break
                                else:
                                    continue
                                break
                            if not raw.strip() or not raw.lstrip().startswith("<"):
                                xml_candidates = []
                                if "fmt=" not in caption_url:
                                    xml_candidates.append(f"{caption_url}{sep}fmt=xml3")
                                xml_candidates.append(caption_url)
                                for u in xml_candidates:
                                    raw = await self._page_try_fetch_timedtext(page, u)
                                    if raw.strip().startswith("<") or raw.strip().startswith("<?xml"):
                                        break
                            if not raw.strip():
                                msg = "No XML caption payload for WebVTT"
                                raise ExtractionError(msg, details="empty_timedtext_vtt")
                            try:
                                body = timedtext_xml_to_webvtt(raw)
                            except ParseError as exc:
                                msg = "Caption response was not parseable as XML for WebVTT"
                                raise ExtractionError(msg, details=str(exc)) from exc

                    data = {
                        "video_id": meta.video_id,
                        "language": chosen.language_code,
                        "format": fmt,
                        "body": body,
                    }
                    return make_envelope(settings=self._settings, kind="transcript", data=data)
                finally:
                    try:
                        page.remove_listener("response", _on_response)
                    except Exception:
                        pass
        except ExtractionError:
            raise
        except Exception as exc:
            msg = "Camoufox transcript session failed"
            raise NavigationError(msg, details=str(exc)) from exc

    async def _scrape_transcript_legacy(
        self,
        watch_page_url: str,
        *,
        language: str | None,
        fmt: Literal["txt", "vtt", "json"],
    ) -> ResultEnvelope:
        """Two-session path for non-Camoufox browser stubs."""
        log.info("scrape_transcript_legacy", extra={"url": watch_page_url, "language": language, "fmt": fmt})
        player, _initial, _html = await self._browser.extract_watch_payload(
            watch_page_url,
            hydrate_for_comments=False,
        )
        meta = parse_video_metadata(player)
        tracks = parse_caption_tracks(player)
        if not tracks:
            msg = "No caption tracks available for this video"
            raise ExtractionError(msg, details="no_caption_tracks")
        chosen = None
        if language:
            for t in tracks:
                if t.language_code == language:
                    chosen = t
                    break
            if chosen is None:
                msg = f"No caption track for language={language!r}"
                raise ExtractionError(msg, details="language_not_found")
        else:
            chosen = tracks[0]
        caption_url = str(chosen.base_url)
        sep = "&" if "?" in caption_url else "?"
        if fmt == "json":
            caption_json = f"{caption_url}{sep}fmt=json3" if "fmt=" not in caption_url else caption_url
            raw = await self._fetch_nonempty_text(watch_page_url, caption_json)
            if not raw.strip():
                msg = "Timedtext JSON endpoint returned an empty body"
                raise ExtractionError(msg, details="empty_timedtext_json")
            body: str | dict[str, Any] = json.loads(raw)
        elif fmt == "txt":
            try:
                xml_text = await self._caption_xml_body(watch_page_url, caption_url)
                body = timedtext_xml_to_plain(xml_text)
            except (ExtractionError, ParseError):
                body = ""
            if not str(body).strip():
                body = await self._caption_plain_via_json3(watch_page_url, caption_url)
        else:
            xml_text = await self._caption_xml_body(watch_page_url, caption_url)
            try:
                body = timedtext_xml_to_webvtt(xml_text)
            except ParseError as exc:
                msg = "Caption response was not parseable as XML for WebVTT"
                raise ExtractionError(msg, details=str(exc)) from exc
        data = {
            "video_id": meta.video_id,
            "language": chosen.language_code,
            "format": fmt,
            "body": body,
        }
        return make_envelope(settings=self._settings, kind="transcript", data=data)

    async def scrape(
        self,
        url_or_id: str,
        *,
        language: str | None,
        fmt: Literal["txt", "vtt", "json"],
    ) -> ResultEnvelope:
        watch_page_url = watch_url(url_or_id)
        log.info("scrape_transcript_start", extra={"url": watch_page_url, "language": language, "fmt": fmt})
        if isinstance(self._browser, CamoufoxBrowserSession):
            return await self._scrape_transcript_camoufox_one_tab(
                watch_page_url,
                language=language,
                fmt=fmt,
            )
        return await self._scrape_transcript_legacy(
            watch_page_url,
            language=language,
            fmt=fmt,
        )
