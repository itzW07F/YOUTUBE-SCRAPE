"""Camoufox + Playwright browser adapter."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, cast

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Page, Route

from youtube_scrape.application.network_debug import NetworkDebugLog, url_preview
from youtube_scrape.domain.dash_init import is_dash_init_fmp4, itag_from_videoplayback_url
from youtube_scrape.domain.json_extract import (
    extract_yt_initial_data,
    extract_yt_initial_player_response,
)
from youtube_scrape.domain.ports import BrowserSession
from youtube_scrape.exceptions import ExtractionError, NavigationError
from youtube_scrape.settings import Settings

# Match ``_GOOGLEVIDEO_HEADERS`` in ``download_media`` so Playwright APIRequest is less likely to get 403.
_CHROME_MEDIA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _is_googlevideo_host_url(url: str) -> bool:
    u = url.lower()
    return "googlevideo.com" in u or "googleusercontent.com" in u


log = logging.getLogger(__name__)

_PROTOBUFISH_FIRST_BYTES = frozenset(
    {0x08, 0x0A, 0x12, 0x1A, 0x22, 0x2A, 0x32, 0x3A, 0x42, 0x4A},
)


def _protobuf_like_lead(body: bytes) -> bool:
    """Heuristic: many YouTube protobuf payloads start with low protobuf wire-key bytes."""
    if len(body) < 1:
        return False
    return body[0] in _PROTOBUFISH_FIRST_BYTES


def _find_isobmff_root(body: bytes, *, scan: int = 524_288) -> int | None:
    """Return byte offset of a top-level ISO BMFF box (``....ftyp``), or ``None``.

    YouTube may wrap media in ``application/vnd.yt-ump`` so ``ftyp`` is not at file offset 4; scan the
    early prefix for a plausible ``[size big-endian][b'ftyp']`` pair.
    """
    lim = min(len(body), scan)
    if lim < 8:
        return None
    pos = 0
    while pos + 8 <= lim:
        j = body.find(b"ftyp", pos, lim - 4)
        if j < 4:
            return None
        i = j - 4
        sz = int.from_bytes(body[i : i + 4], "big")
        if 8 <= sz <= min(16_777_216, len(body) - i):
            return i
        pos = j + 1
    return None


def _iso_bmff_moof_before_mdat(body: bytes, *, scan: int = 2_097_152) -> bool:
    """True when a top-level ``moof`` appears before the first ``mdat`` — typical DASH segment layout.

    Classic **progressive** (muxed itag 18) is usually ``ftyp`` → ``moov`` → ``mdat`` with no ``moof``.
    """
    n = min(len(body), scan)
    if n < 8:
        return False
    moof = body.find(b"moof", 0, n)
    if moof < 0:
        return False
    mdat = body.find(b"mdat", 0, n)
    if mdat < 0:
        return True
    return moof < mdat


def _bytes_ok_for_progressive_playback(data: bytes) -> bool:
    """True when we can locate a plausible ISO BMFF ``ftyp`` (possibly after UMP prefix)."""
    if len(data) < 12:
        return False
    if data[4:8] == b"ftyp":
        b = data
    else:
        r = _find_isobmff_root(data)
        if r is None:
            return False
        b = data[r:]
    return len(b) >= 12 and b[4:8] == b"ftyp"


def _guess_mp4_codec_hint(data: bytes) -> str | None:
    """Cheap FourCC-ish hint for envelope metadata (``av01`` / ``avc1`` / …)."""
    scan = min(len(data), 2_097_152)
    blob = data[:scan]
    if b"av01" in blob or b"AV01" in blob:
        return "av01"
    if b"avc1" in blob or b"AVC1" in blob or b"avc3" in blob:
        return "avc1"
    if b"vp09" in blob or b"VP09" in blob:
        return "vp09"
    return None


def _isobmff_dash_profile(body: bytes) -> bool:
    """True when the first ISO BMFF ``ftyp`` uses a DASH-style major brand (``dash`` / ``msdh``).

    Those init segments are valid for adaptive playback but are a poor standalone file when the
    capture is only a short prefix; prefer ``mp42``/``isom`` progressive-style brands when ranking.
    """
    if len(body) < 12:
        return False
    if body[4:8] == b"ftyp":
        off = 0
    else:
        r = _find_isobmff_root(body)
        if r is None:
            return False
        off = r
    if len(body) < off + 12:
        return False
    frag = body[off : off + 12]
    if frag[4:8] != b"ftyp":
        return False
    major = frag[8:12]
    return major in (b"dash", b"msdh")


def _media_request_timeout_ms(settings: Settings) -> int:
    return int(max(settings.browser_timeout_s, settings.media_download_timeout_s) * 1000)


def _looks_like_downloadable_media(body: bytes) -> bool:
    """True for ISO BMFF or WebM/EBML (common for adaptive audio)."""
    if _bytes_look_like_mp4_head(body):
        return True
    if len(body) >= 4 and body[0:4] == b"\x1a\x45\xdf\xa3":
        return True
    return False


def _bytes_look_like_mp4_head(data: bytes) -> bool:
    """True if bytes start with (or quickly contain) an ISO BMFF ``ftyp`` (progressive head)."""
    if len(data) < 8:
        return False
    if data[4:8] == b"ftyp":
        return True
    off = _find_isobmff_root(data)
    if off is not None:
        return True
    return b"ftyp" in data[: min(len(data), 16_384)]


def _mp4_init_box_score(body: bytes) -> int:
    """Prefer a real ``ftyp`` box at BMFF offset 4; fall back to ``ftyp`` anywhere in the early prefix."""
    if len(body) >= 8 and body[4:8] == b"ftyp":
        return 2
    scan = min(len(body), 8192)
    return 1 if scan >= 8 and b"ftyp" in body[:scan] else 0


def _playback_capture_rank(
    url: str,
    body: bytes,
    prefer_itag: int | None,
    *,
    starts_at_file_origin: int,
    not_xhr_like: int,
    content_type_is_video: int,
    media_resource_type: int,
) -> tuple[int, int, int, int, int, int, int, int, int, int, int, int]:
    """Score a captured body for ``max()`` comparison (larger tuple is better).

    Without this, the largest ``videoplayback`` chunk is often VP9/WebM, a mid-file range, or
    non-media payloads that still match the hostname/path filter.
    """
    u = url.lower()
    not_pbish = 0 if _protobuf_like_lead(body) else 1
    not_dash = 0 if _isobmff_dash_profile(body) else 1
    no_moof_before_mdat = 0 if _iso_bmff_moof_before_mdat(body) else 1
    box = _mp4_init_box_score(body)
    itag_ok = 0
    if prefer_itag is not None:
        needle = str(prefer_itag)
        if f"itag={needle}" in u or f"itag%3d{needle}" in u:
            itag_ok = 1
    mp4_hint = 0
    if "video%2fmp4" in u or "mime=video/mp4" in u:
        mp4_hint = 1
    # Prefer containers other than WebM when everything else ties (VP9 chunks can be huge).
    not_webm = 0 if ("video%2fwebm" in u or "mime=video/webm" in u) else 1
    return (
        not_pbish,
        not_dash,
        no_moof_before_mdat,
        media_resource_type,
        box,
        content_type_is_video,
        not_xhr_like,
        starts_at_file_origin,
        itag_ok,
        mp4_hint,
        not_webm,
        len(body),
    )


_VIDEOPLAYBACK_ROUTE_RE = re.compile(
    r"https://[\w.-]*(?:googlevideo\.com|googleusercontent\.com)/videoplayback\?.*",
    re.IGNORECASE,
)


def _parse_content_range_header(
    cr_raw: str | None,
    body_len: int,
    *,
    status: int,
) -> tuple[int, int, int | None]:
    """Parse ``Content-Range`` (or infer from status). Returns ``(start, end_inclusive, total_or_none)``."""
    if body_len <= 0:
        return 0, -1, None
    s = (cr_raw or "").strip()
    if not s:
        if status == 200:
            return 0, body_len - 1, body_len
        return 0, body_len - 1, None
    sl = s.lower()
    if not sl.startswith("bytes "):
        return 0, body_len - 1, body_len if status == 200 else None
    rest = s[6:].strip()
    if "/" not in rest:
        return 0, body_len - 1, body_len if status == 200 else None
    range_part, total_part = rest.rsplit("/", 1)
    total_part = total_part.strip()
    total_out: int | None = None
    if total_part != "*":
        try:
            total_out = int(total_part)
        except ValueError:
            total_out = None
    range_part = range_part.strip()
    if range_part == "*":
        return 0, -1, total_out
    if "-" not in range_part:
        return 0, body_len - 1, total_out
    a, b = range_part.split("-", 1)
    try:
        start = int(a.strip())
        end = int(b.strip())
    except ValueError:
        return 0, body_len - 1, total_out
    return start, end, total_out


@dataclass
class MediaRouteSnifferState:
    """Mutable state for :meth:`CamoufoxBrowserSession.open_watch_page_with_media_route_capture`."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    best: bytearray = field(default_factory=bytearray)
    best_rank: tuple[int, ...] | None = None
    prefer_itag: int | None = None
    require_clen: str | None = None
    max_capture_bytes: int | None = None
    range_parts: dict[int, tuple[int, bytes]] = field(default_factory=dict)
    range_total: int | None = None
    # DASH init fMP4 (ftyp+moov, no top mdat) keyed by itag= from the videoplayback URL.
    dash_init_by_itag: dict[int, bytes] = field(default_factory=dict)
    # When itag= cannot be read from a signed/encoded URL, the smallest init-only blob (best-effort).
    dash_init_unkeyed: bytes | None = None
    debug_log: NetworkDebugLog | None = None
    # Accumulate all DASH fragments (moof+mdat) for full video assembly
    all_fragments: bytearray = field(default_factory=bytearray)
    fragments_count: int = 0

    def add_fragment(self, body: bytes) -> None:
        """Add a DASH fragment to the accumulated collection.
        
        Deduplicates fragments based on moof sequence number to avoid
        storing the same fragment multiple times from different network responses.
        """
        import struct
        
        if not body or len(body) < 100:
            return
            
        # Look for moof box to extract sequence number
        seq_num = None
        offset = 0
        while offset < len(body) - 8:
            size = int.from_bytes(body[offset:offset+4], 'big')
            box_type = body[offset+4:offset+8]
            
            if box_type == b'moof':
                # Find mfhd inside moof
                moof_end = offset + size
                inner = offset + 8
                while inner < moof_end - 8:
                    inner_size = int.from_bytes(body[inner:inner+4], 'big')
                    inner_type = body[inner+4:inner+8]
                    if inner_type == b'mfhd' and inner + 16 <= moof_end:
                        # mfhd: version(1) + flags(3) + seq_num(4)
                        seq_num = struct.unpack('>I', body[inner+12:inner+16])[0]
                        break
                    if inner_size < 8:
                        inner += 1
                    else:
                        inner += inner_size
                break
                
            if box_type == b'mdat':
                # Stop at mdat, moof should come before it
                break
            if size < 8 or size > 100_000_000:
                offset += 1
            else:
                offset += size
        
        # If we found a sequence number, check for duplicates
        if seq_num is not None:
            # Store fragments in a dict by sequence number to deduplicate
            if not hasattr(self, '_fragments_by_seq'):
                self._fragments_by_seq: dict[int, bytes] = {}
            
            # Only add if we haven't seen this sequence number, or if this one is larger
            existing = self._fragments_by_seq.get(seq_num)
            if existing is None or len(body) > len(existing):
                self._fragments_by_seq[seq_num] = bytes(body)
                # Rebuild all_fragments from sorted sequence numbers
                self.all_fragments = bytearray()
                for seq in sorted(self._fragments_by_seq.keys()):
                    self.all_fragments.extend(self._fragments_by_seq[seq])
                self.fragments_count = len(self._fragments_by_seq)
        else:
            # No sequence number found, just append (init segment, etc.)
            self.all_fragments.extend(body)
            self.fragments_count += 1

    def record_dash_init(self, full_body: bytes, request_url: str) -> None:
        """Store a DASH init segment when the body is init-only, keyed by ``itag=`` in ``request_url``."""
        if not full_body or len(full_body) < 32:
            return
        off = _find_isobmff_root(full_body)
        raw = full_body[off:] if off is not None else full_body
        if not is_dash_init_fmp4(raw):
            return
        it = itag_from_videoplayback_url(request_url)
        if it is not None:
            cur = self.dash_init_by_itag.get(it)
            if cur is None or len(raw) > len(cur):
                self.dash_init_by_itag[it] = bytes(raw)
            return
        uk = self.dash_init_unkeyed
        if uk is None or len(raw) < len(uk):
            self.dash_init_unkeyed = bytes(raw)

    def add_range_part(self, start: int, end: int, body: bytes, total: int | None) -> None:
        """Record one HTTP byte-range slice (wire bytes, not BMFF-trimmed)."""
        if end < start or not body:
            return
        if total is not None and total > 0:
            self.range_total = total if self.range_total is None else max(self.range_total, total)
        span = end - start + 1
        wire = body if len(body) == span else body[:span]
        if len(wire) != span:
            return
        prev = self.range_parts.get(start)
        if prev is None or len(wire) > len(prev[1]):
            self.range_parts[start] = (end, wire)

    def try_merge_byte_range_assembly(self) -> bytes | None:
        """If we captured every byte ``0 .. total-1`` via Range responses, return one contiguous blob."""
        total = self.range_total
        if total is None or total <= 0 or not self.range_parts:
            return None
        out = bytearray()
        pos = 0
        for s in sorted(self.range_parts):
            e, b = self.range_parts[s]
            if e < pos:
                continue
            if s > pos:
                return None
            if s < pos:
                b = b[pos - s :]
                s = pos
            if len(b) != e - s + 1:
                return None
            if s != pos:
                return None
            out.extend(b)
            pos = e + 1
        if pos != total:
            return None
        return bytes(out)


class CamoufoxBrowserSession(BrowserSession):
    """Camoufox + Playwright: ephemeral launch by default, or one reused browser when configured."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reuse_lock = asyncio.Lock()
        self._reuse_cm: Any = None
        self._reuse_browser: Any = None

    def camoufox_launch_kwargs(self) -> dict[str, Any]:
        """Expose launch kwargs for callers that need a matching Camoufox session (e.g. transcript)."""
        return self._launch_kwargs()

    async def _post_goto_settle(self, page: Page) -> None:
        """Scroll the watch page so lazy panels (especially comments) hydrate before ``page.content()``."""
        if self._settings.page_settle_after_load_ms <= 0:
            return
        timeout_ms = min(self._settings.page_settle_after_load_ms, 30_000)
        deadline = time.monotonic() + timeout_ms / 1000.0

        async def _remaining_s() -> float:
            return max(0.0, deadline - time.monotonic())

        try:
            await page.wait_for_selector(
                "ytd-comments-section-renderer",
                timeout=min(12_000, timeout_ms),
            )
        except Exception:
            log.debug("comments_section_wait_timeout", exc_info=True)

        while await _remaining_s() > 0.45:
            try:
                n = await page.evaluate(
                    "() => document.querySelectorAll('ytd-comment-thread-renderer').length",
                )
            except Exception:
                n = 0
            if isinstance(n, int) and n > 0:
                break
            await page.evaluate(
                "() => window.scrollBy(0, Math.min(window.innerHeight * 0.88, 960))",
            )
            await asyncio.sleep(0.42)

        try:
            await page.locator("ytd-comments-section-renderer").first.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            log.debug("comments_section_scroll_into_view_failed", exc_info=True)

        tail = min(1.8, await _remaining_s())
        if tail > 0:
            await asyncio.sleep(tail)

    def _launch_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"headless": self._settings.headless}
        if self._settings.camoufox_humanize:
            kwargs["humanize"] = True
        if self._settings.proxy_server:
            kwargs["proxy"] = {"server": str(self._settings.proxy_server)}
        if self._settings.user_data_dir is not None:
            kwargs["persistent_context"] = True
            kwargs["user_data_dir"] = str(self._settings.user_data_dir)
        return kwargs

    async def _maybe_dismiss_youtube_consent(self, page: Page) -> None:
        """Best-effort dismiss EU/UK consent walls so the player can load media."""
        deadline = time.monotonic() + 4.0
        selectors = (
            'button:has-text("Accept all")',
            'button:has-text("Accept all cookies")',
            'tp-yt-paper-button:has-text("Accept all")',
            "button[aria-label*='Accept the use of cookies' i]",
        )
        while time.monotonic() < deadline:
            clicked = False
            for sel in selectors:
                loc = page.locator(sel).first
                try:
                    if await loc.count() == 0:
                        continue
                    if not await loc.is_visible():
                        continue
                    await loc.click(timeout=2_500)
                    log.info("youtube_consent_dismiss_clicked", extra={"selector": sel[:80]})
                    clicked = True
                    await asyncio.sleep(0.6)
                    break
                except Exception:
                    continue
            if not clicked:
                break

    async def _after_youtube_watch_goto(self, page: Page) -> None:
        """Let the watch SPA reach ``load`` so the player shell exists before skip/capture."""
        try:
            await page.wait_for_load_state("load", timeout=28_000)
        except Exception:
            log.debug("watch_after_goto_load_timeout", exc_info=True)

    async def reload_watch_page_for_capture(self, page: Page, watch_url: str) -> None:
        """``goto`` again + load/skip so a failed capture retry gets a fresh player / cookies."""
        await page.goto(
            watch_url,
            wait_until="domcontentloaded",
            timeout=int(self._settings.browser_timeout_s * 1000),
        )
        await self._after_youtube_watch_goto(page)
        await self._maybe_skip_youtube_preroll_ads(
            page,
            total_budget_s=min(28.0, self._settings.youtube_preroll_ad_skip_budget_s),
        )

    async def _maybe_skip_youtube_preroll_ads(self, page: Page, *, total_budget_s: float) -> None:
        """Detect skippable preroll and click Skip (Camoufox ``humanize`` moves the real pointer)."""
        if total_budget_s <= 0:
            return
        await self._maybe_dismiss_youtube_consent(page)
        deadline = time.monotonic() + total_budget_s
        selectors = (
            "button.ytp-ad-skip-button",
            ".ytp-ad-skip-button-modern",
            "button.ytp-skip-ad-button",
        )
        idle_rounds = 0
        try:
            await page.wait_for_selector("ytd-player, .html5-video-player", timeout=12_000)
        except Exception:
            log.debug("youtube_ad_skip_player_wait_timeout", exc_info=True)
        while time.monotonic() < deadline:
            clicked = False
            for sel in selectors:
                loc = page.locator(sel).first
                try:
                    if await loc.count() == 0:
                        continue
                    if not await loc.is_visible():
                        continue
                    await loc.click(timeout=4_000)
                    log.info("youtube_preroll_skip_clicked", extra={"selector": sel})
                    clicked = True
                    idle_rounds = 0
                    await asyncio.sleep(0.55)
                    break
                except Exception:
                    log.debug("youtube_preroll_skip_click_try", exc_info=True)
                    continue
            if not clicked:
                idle_rounds += 1
                if idle_rounds >= 10:
                    break
                await asyncio.sleep(0.38)

    async def _ensure_persistent_browser(self) -> None:
        async with self._reuse_lock:
            if self._reuse_browser is not None:
                return
            cm = AsyncCamoufox(**self._launch_kwargs())  # type: ignore[no-untyped-call]
            self._reuse_browser = await cm.__aenter__()
            self._reuse_cm = cm
            log.info("camoufox_reuse_browser_started")

    async def aclose(self) -> None:
        """Close the reused Camoufox instance when ``browser_reuse_context`` is enabled."""
        async with self._reuse_lock:
            if self._reuse_cm is None:
                return
            cm = self._reuse_cm
            self._reuse_cm = None
            self._reuse_browser = None
            await cm.__aexit__(None, None, None)
        log.info("camoufox_reuse_browser_closed")

    @asynccontextmanager
    async def _camoufox(self) -> AsyncIterator[Any]:
        if not self._settings.browser_reuse_context:
            async with AsyncCamoufox(**self._launch_kwargs()) as browser:  # type: ignore[no-untyped-call]
                yield browser
            return
        await self._ensure_persistent_browser()
        if self._reuse_browser is None:
            msg = "Camoufox reuse browser missing after _ensure_persistent_browser"
            raise NavigationError(msg, details="internal")
        yield self._reuse_browser

    @asynccontextmanager
    async def open_watch_page(self, watch_url: str) -> AsyncIterator[Page]:
        """Open **one** watch tab (goto + settle); yields the ``Page``; closes it on exit.

        Use this when you need HTML extraction and later in-page media work without a second
        ``goto``/window (e.g. experimental progressive download after a failed plain HTTP GET).
        """
        last_error: Exception | None = None
        for attempt in range(self._settings.max_navigation_retries):
            try:
                async with self._camoufox() as browser:
                    page = await browser.new_page()
                    try:
                        await page.goto(
                            watch_url,
                            wait_until="domcontentloaded",
                            timeout=int(self._settings.browser_timeout_s * 1000),
                        )
                        await self._after_youtube_watch_goto(page)
                        await self._maybe_skip_youtube_preroll_ads(
                            page,
                            total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                        )
                        await self._post_goto_settle(page)
                        yield page
                        return
                    finally:
                        try:
                            await page.close()
                        except Exception:
                            log.debug("open_watch_page_close_failed", exc_info=True)
            except (NavigationError, ExtractionError, TimeoutError) as exc:
                last_error = exc
                log.warning(
                    "open_watch_page_failed",
                    extra={"url": watch_url, "attempt": attempt, "error": str(exc)},
                )
                if attempt + 1 == self._settings.max_navigation_retries:
                    break
                await asyncio.sleep(self._settings.navigation_backoff_s * (attempt + 1))
        msg = f"Failed to open watch page after retries: {watch_url}"
        raise NavigationError(msg, details=str(last_error))

    def _media_route_sniffer_handler(self, state: MediaRouteSnifferState) -> Callable[[Route], Awaitable[None]]:
        """Use ``route.fetch`` then ``fulfill`` — same TLS/session bytes as the player (in-process mini-proxy)."""

        min_body = 512

        async def handler(route: Route) -> None:
            req = route.request
            u = req.url
            if "googlevideo.com" not in u.lower() and "googleusercontent.com" not in u.lower():
                await route.continue_()
                return
            if "videoplayback" not in u:
                await route.continue_()
                return
            rt = str(getattr(req, "resource_type", "") or "").lower()
            if rt in ("websocket", "eventsource"):
                await route.continue_()
                return
            rclen = state.require_clen
            if rclen is not None and str(rclen).strip():
                cl = str(rclen).strip()
                ul = u.lower()
                if f"clen={cl}" not in ul and f"clen%3d{cl}" not in ul:
                    await route.continue_()
                    return
            try:
                resp = await route.fetch()
            except Exception as exc:
                if state.debug_log is not None:
                    state.debug_log.add(
                        "media_route_fetch_ex", url=url_preview(u), error_type=type(exc).__name__, detail=str(exc)[:400]
                    )
                log.debug("media_route_sniffer_fetch_failed", exc_info=True)
                await route.continue_()
                return
            st = int(resp.status)
            if st not in (200, 206):
                if state.debug_log is not None:
                    state.debug_log.add("media_route_non_ok", status=st, url=url_preview(u), resource_type=rt)
                await route.continue_()
                return
            try:
                full_body = await resp.body()
            except Exception:
                log.debug("media_route_sniffer_body_failed", exc_info=True)
                await route.continue_()
                return
            state.record_dash_init(full_body, u)
            hdrs = dict(resp.headers)
            ct = str(hdrs.get("content-type") or hdrs.get("Content-Type") or "").lower()

            # Accumulate ALL video/media responses for fragment assembly
            # Do this before any filtering so we capture UMP fragments too
            if len(full_body) > 1000 and ("video/" in ct or "vnd.yt-ump" in ct or "octet-stream" in ct):
                async with state.lock:
                    # Trim any BMFF offset for consistent accumulation
                    body_for_frag = full_body
                    mp4_off = _find_isobmff_root(body_for_frag)
                    if mp4_off is not None:
                        body_for_frag = body_for_frag[mp4_off:]
                    state.add_fragment(body_for_frag)

            if len(full_body) > 200_000_000:
                await route.fulfill(status=st, headers=hdrs, body=full_body)
                return
            if ct and any(
                bad in ct
                for bad in (
                    "application/json",
                    "text/html",
                    "javascript",
                    "image/",
                    "protobuf",
                    "x-protobuf",
                )
            ):
                await route.fulfill(status=st, headers=hdrs, body=full_body)
                return
            body = full_body
            mp4_off = _find_isobmff_root(body)
            if mp4_off is not None:
                body = body[mp4_off:]
            if len(body) < min_body:
                await route.fulfill(status=st, headers=hdrs, body=full_body)
                return
            strict_prefix = (len(body) >= 8 and body[4:8] == b"ftyp") or (b"ftyp" in body[:64])
            if _protobuf_like_lead(body) and not strict_prefix:
                await route.fulfill(status=st, headers=hdrs, body=full_body)
                return
            if state.require_clen is None:
                if not strict_prefix:
                    await route.fulfill(status=st, headers=hdrs, body=full_body)
                    return
            elif not strict_prefix and "video/" not in ct and "vnd.yt-ump" not in ct:
                await route.fulfill(status=st, headers=hdrs, body=full_body)
                return
            video_ct = 0
            if "video/" in ct:
                video_ct = 2
            elif "octet-stream" in ct and "video%2fmp4" in u.lower():
                video_ct = 1
            elif "vnd.yt-ump" in ct:
                video_ct = 1
            cr = str(hdrs.get("content-range") or hdrs.get("Content-Range") or "")
            cr_l = cr.lower()
            starts_at_origin = 0
            if st == 200:
                starts_at_origin = 1
            elif cr_l.startswith("bytes 0-") or cr_l.startswith("bytes 0/"):
                starts_at_origin = 1
            cap = (
                state.max_capture_bytes
                if (state.max_capture_bytes is not None and state.max_capture_bytes > 0)
                else len(body)
            )
            slice_end = min(len(body), cap)
            chunk = body[:slice_end]
            not_xhr = 0 if rt == "xhr" else 1
            media_rt = 1 if rt == "media" else 0
            rank = _playback_capture_rank(
                u,
                body,
                state.prefer_itag,
                starts_at_file_origin=starts_at_origin,
                not_xhr_like=not_xhr,
                content_type_is_video=video_ct,
                media_resource_type=media_rt,
            )
            if state.debug_log is not None:
                state.debug_log.add(
                    "media_route",
                    status=st,
                    url=url_preview(u),
                    resource_type=rt,
                    content_type=ct,
                    content_range=cr,
                    body_len=len(full_body),
                    rank=str(rank)[:200],
                )
            start_b, end_b, tot = _parse_content_range_header(cr, len(full_body), status=st)
            async with state.lock:
                if end_b >= start_b >= 0:
                    span = end_b - start_b + 1
                    if len(full_body) >= span:
                        state.add_range_part(start_b, end_b, full_body[:span], tot)
                # Update best single response (for fallback)
                if state.best_rank is None or rank > state.best_rank:
                    state.best_rank = rank
                    state.best[:] = chunk
            await route.fulfill(status=st, headers=hdrs, body=full_body)

        return handler

    @asynccontextmanager
    async def open_watch_page_with_media_route_capture(
        self,
        watch_url: str,
        *,
        max_capture_bytes: int | None = None,
        network_debug_log: NetworkDebugLog | None = None,
    ) -> AsyncIterator[tuple[Page, MediaRouteSnifferState]]:
        """Like :meth:`open_watch_page` but installs a ``videoplayback`` **route sniffer** before navigation.

        The handler uses ``route.fetch()`` (same session as the document) then ``route.fulfill`` so the player
        still receives bytes while we rank-copy candidates into ``MediaRouteSnifferState.best``.

        When ``network_debug_log`` is set, route and capture events are appended for diagnostics.
        """
        state = MediaRouteSnifferState(max_capture_bytes=max_capture_bytes, debug_log=network_debug_log)
        sniffer = self._media_route_sniffer_handler(state)
        last_error: Exception | None = None
        for attempt in range(self._settings.max_navigation_retries):
            try:
                async with self._camoufox() as browser:
                    page = await browser.new_page()
                    await page.route(_VIDEOPLAYBACK_ROUTE_RE, sniffer)
                    try:
                        await page.goto(
                            watch_url,
                            wait_until="domcontentloaded",
                            timeout=int(self._settings.browser_timeout_s * 1000),
                        )
                        await self._after_youtube_watch_goto(page)
                        await self._maybe_skip_youtube_preroll_ads(
                            page,
                            total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                        )
                        await self._post_goto_settle(page)
                        yield page, state
                        return
                    finally:
                        try:
                            await page.unroute(_VIDEOPLAYBACK_ROUTE_RE, sniffer)
                        except Exception:
                            log.debug("media_route_sniffer_unroute_failed", exc_info=True)
                        try:
                            await page.close()
                        except Exception:
                            log.debug("open_watch_page_sniffer_close_failed", exc_info=True)
            except (NavigationError, ExtractionError, TimeoutError) as exc:
                last_error = exc
                log.warning(
                    "open_watch_page_sniffer_failed",
                    extra={"url": watch_url, "attempt": attempt, "error": str(exc)},
                )
                if attempt + 1 == self._settings.max_navigation_retries:
                    break
                await asyncio.sleep(self._settings.navigation_backoff_s * (attempt + 1))
        msg = f"Failed to open watch page (sniffer) after retries: {watch_url}"
        raise NavigationError(msg, details=str(last_error))

    async def fetch_text_in_watch_context(self, watch_url: str, resource_url: str) -> str:
        """Load the watch page then GET a URL with Playwright (inherits session cookies)."""
        try:
            async with self._camoufox() as browser:
                page = await browser.new_page()
                try:
                    await page.goto(
                        watch_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._settings.browser_timeout_s * 1000),
                    )
                    await self._after_youtube_watch_goto(page)
                    await self._maybe_skip_youtube_preroll_ads(
                        page,
                        total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                    )
                    await self._post_goto_settle(page)
                    # In-page fetch: match watch origin cookies (plain APIRequest GET often returns empty timedtext).
                    js = """
                    async (url) => {
                        const response = await fetch(url, { credentials: 'include' });
                        if (!response.ok) {
                            throw new Error('timedtext_fetch_status_' + response.status);
                        }
                        return await response.text();
                    }
                    """
                    try:
                        return str(await page.evaluate(js, resource_url))
                    except Exception as exc:
                        msg = "In-page fetch for timedtext failed"
                        raise NavigationError(msg, details=str(exc)) from exc
                finally:
                    with suppress(Exception):
                        await page.close()
        except NavigationError:
            raise
        except Exception as exc:  # pragma: no cover - browser dependent
            msg = "fetch_text_in_watch_context failed"
            raise NavigationError(msg, details=str(exc)) from exc

    async def _assign_progressive_video_src(self, page: Page, media_url: str) -> None:
        """Point the watch page ``<video>`` at the plain progressive ``googlevideo`` URL (best-effort)."""
        try:
            await page.wait_for_selector("video", timeout=12_000)
        except Exception:
            log.debug("video_element_wait_timeout", exc_info=True)
        try:
            await page.evaluate(
                """async (mediaUrl) => {
                    const v = document.querySelector('video');
                    if (!v || !mediaUrl) return;
                    try {
                        v.pause();
                        try { v.crossOrigin = 'anonymous'; } catch (e) {}
                        for (const s of v.querySelectorAll('source')) { s.remove(); }
                        v.removeAttribute('src');
                        v.src = mediaUrl;
                        v.load();
                        v.muted = true;
                        await v.play().catch(() => {});
                    } catch (e) {}
                }""",
                media_url,
            )
        except Exception:
            log.debug("video_progressive_src_assign_failed", exc_info=True)

    async def _click_youtube_large_play_if_present(self, page: Page) -> None:
        """Use a real click so autoplay policies treat playback as user-gestured when possible."""
        for sel in (
            "button.ytp-large-play-button",
            ".ytp-large-play-button",
            ".html5-video-player .ytp-play-button",
        ):
            loc = page.locator(sel).first
            try:
                if await loc.count() == 0:
                    continue
                if not await loc.is_visible():
                    continue
                await loc.click(timeout=5_000)
                await asyncio.sleep(0.45)
                return
            except Exception:
                log.debug("youtube_large_play_click_try", exc_info=True)
                continue

    async def _prime_video_for_media_capture(self, page: Page) -> None:
        """Start the HTML5 player so the page issues real ``videoplayback`` requests."""
        prime_budget = min(22.0, max(0.0, self._settings.youtube_preroll_ad_skip_budget_s))
        await self._maybe_skip_youtube_preroll_ads(page, total_budget_s=prime_budget)
        await self._click_youtube_large_play_if_present(page)
        try:
            await page.wait_for_selector("video", timeout=12_000)
        except Exception:
            log.debug("video_element_wait_timeout", exc_info=True)
        await self._click_youtube_large_play_if_present(page)
        try:
            await page.evaluate(
                """() => {
                    const v = document.querySelector('video');
                    if (!v) return;
                    try { v.muted = true; } catch (e) {}
                    if (v.paused) {
                        v.play().catch(() => {});
                    }
                }""",
            )
        except Exception:
            log.debug("video_play_eval_failed", exc_info=True)
        await asyncio.sleep(4.0)

    async def _seek_video_to_trigger_fragments(self, page: Page, duration_seconds: float) -> None:
        """Seek to different positions in video to trigger fragment downloads.

        YouTube's DASH player loads fragments on-demand. By seeking to different
        positions, we trigger the player to request more fragments.
        """
        if duration_seconds <= 0:
            return

        # More granular seeking to capture more fragments
        # Start with early positions (init fragments), then spread out
        # Use more positions for longer videos
        num_positions = min(20, max(10, int(duration_seconds / 10)))  # ~1 position per 10 seconds
        seek_positions = [i / (num_positions - 1) for i in range(num_positions)]

        for pos in seek_positions:
            time = duration_seconds * pos
            try:
                # Seek and wait for network activity to settle
                await page.evaluate(
                    f"""() => {{
                        const v = document.querySelector('video');
                        if (v) {{
                            // Clear buffer to force new fragment fetch
                            try {{
                                if (v.buffered && v.buffered.length > 0) {{
                                    // This forces the player to re-fetch
                                    v.load();
                                }}
                            }} catch(e) {{}}
                            v.currentTime = {time};
                        }}
                    }}"""
                )
                log.info("video_seek", extra={"position": round(pos, 2), "time": round(time, 1)})
                # Wait longer for fragment to load
                await asyncio.sleep(3.0)
            except Exception as e:
                log.debug("video_seek_failed", extra={"error": str(e)})

    async def _collect_videoplayback_bytes_on_loaded_page(
        self,
        page: Page,
        *,
        listen_timeout_s: float | None,
        max_bytes: int | None,
        min_body: int,
        prefer_itag: int | None,
        require_url_substrings: tuple[str, ...] | None,
        require_clen: str | None,
        pre_listen_settle_s: float = 0.0,
        mid_phase: Callable[[Page], Awaitable[None]] | None = None,
        direct_results: dict[str, bytes] | None = None,
        progressive_media_url: str | None = None,
        network_debug_log: NetworkDebugLog | None = None,
        dash_state: "MediaRouteSnifferState | None" = None,
    ) -> tuple[bytes, str]:
        listen_s = listen_timeout_s if listen_timeout_s is not None else max(14.0, self._settings.browser_timeout_s * 0.35)
        if not self._settings.headless:
            listen_s = max(listen_s, 26.0)
        best = bytearray()
        best_rank: tuple[int, ...] | None = None
        lock = asyncio.Lock()
        loop = asyncio.get_running_loop()
        handler_tasks: set[asyncio.Task[Any]] = set()

        def _track(t: asyncio.Task[Any]) -> None:
            handler_tasks.add(t)

            def _done(_: asyncio.Future[Any]) -> None:
                handler_tasks.discard(t)

            t.add_done_callback(_done)

        async def _on_response(response: Any) -> None:
            nonlocal best_rank
            try:
                u = str(response.url or "")
                status = int(response.status)
                if "videoplayback" in u and _is_googlevideo_host_url(u) and network_debug_log and status not in (200, 206):
                    req0 = getattr(response, "request", None)
                    rt0 = str(getattr(req0, "resource_type", "") or "").lower()
                    network_debug_log.add(
                        "response_listener_error", status=status, url=url_preview(u), resource_type=rt0
                    )
                if status not in (200, 206):
                    return
                if not _is_googlevideo_host_url(u):
                    return
                if "videoplayback" not in u:
                    return
                req = getattr(response, "request", None)
                rt = str(getattr(req, "resource_type", "") or "").lower()
                # ``fetch`` is kept: some Firefox builds tag media ``videoplayback`` as ``fetch``, not ``media``.
                if rt in ("websocket", "eventsource"):
                    return
                if require_url_substrings:
                    ul = u.lower()
                    if not any(part.lower() in ul for part in require_url_substrings):
                        return
                if require_clen is not None:
                    cl = str(require_clen).strip()
                    if cl:
                        ul = u.lower()
                        if f"clen={cl}" not in ul and f"clen%3d{cl}" not in ul:
                            return
                hdrs = getattr(response, "headers", {}) or {}
                ct = str(hdrs.get("content-type") or hdrs.get("Content-Type") or "").lower()
                if ct and any(
                    bad in ct
                    for bad in (
                        "application/json",
                        "text/html",
                        "javascript",
                        "image/",
                        "protobuf",
                        "x-protobuf",
                    )
                ):
                    return
                body = await response.body()
                if len(body) > 200_000_000:
                    return
                if dash_state is not None:
                    dash_state.record_dash_init(body, u)
                mp4_off = _find_isobmff_root(body)
                if mp4_off is not None:
                    body = body[mp4_off:]
                if len(body) < min_body:
                    return
                strict_prefix = (len(body) >= 8 and body[4:8] == b"ftyp") or (b"ftyp" in body[:64])
                if _protobuf_like_lead(body) and not strict_prefix:
                    return
                if require_clen is None:
                    if not strict_prefix:
                        return
                elif not strict_prefix and "video/" not in ct and "vnd.yt-ump" not in ct:
                    return
                video_ct = 0
                if "video/" in ct:
                    video_ct = 2
                elif "octet-stream" in ct and "video%2fmp4" in u.lower():
                    video_ct = 1
                elif "vnd.yt-ump" in ct:
                    video_ct = 1
                cr = str(hdrs.get("content-range") or hdrs.get("Content-Range") or "")
                cr_l = cr.lower()
                starts_at_origin = 0
                if status == 200:
                    starts_at_origin = 1
                elif cr_l.startswith("bytes 0-") or cr_l.startswith("bytes 0/"):
                    starts_at_origin = 1
                cap = max_bytes if (max_bytes is not None and max_bytes > 0) else len(body)
                slice_end = min(len(body), cap)
                chunk = body[:slice_end]
                not_xhr = 0 if rt == "xhr" else 1
                media_rt = 1 if rt == "media" else 0
                rank = _playback_capture_rank(
                    u,
                    body,
                    prefer_itag,
                    starts_at_file_origin=starts_at_origin,
                    not_xhr_like=not_xhr,
                    content_type_is_video=video_ct,
                    media_resource_type=media_rt,
                )
                async with lock:
                    if best_rank is None or rank > best_rank:
                        best_rank = rank
                        best[:] = chunk
                        if network_debug_log is not None:
                            network_debug_log.add(
                                "response_listener_best",
                                status=status,
                                url=url_preview(u),
                                chunk_len=len(chunk),
                                resource_type=rt,
                                content_type=ct,
                                content_range=cr,
                            )
            except Exception:
                log.debug("videoplayback_capture_skip", exc_info=True)

        def _hook(response: Any) -> None:
            t = loop.create_task(_on_response(response))
            _track(t)

        page.on("response", _hook)
        try:
            if pre_listen_settle_s > 0:
                await asyncio.sleep(pre_listen_settle_s)
            if progressive_media_url:
                await self._assign_progressive_video_src(page, progressive_media_url)
                await asyncio.sleep(2.2)
            if mid_phase is not None:
                await mid_phase(page)
            await self._prime_video_for_media_capture(page)

            # Seek through video to trigger more fragment downloads
            # This is especially important for DASH streams where fragments are loaded on-demand
            try:
                # Try to get video duration and seek to different positions
                duration = await page.evaluate("""() => {
                    const v = document.querySelector('video');
                    return v ? v.duration : 0;
                }""")
                if isinstance(duration, (int, float)) and duration > 0:
                    log.info("video_capture_seeking", extra={"duration": duration})
                    await self._seek_video_to_trigger_fragments(page, float(duration))
            except Exception as e:
                log.debug("video_seek_during_capture_failed", extra={"error": str(e)})

            await asyncio.sleep(listen_s)
        finally:
            try:
                page.remove_listener("response", _hook)
            except Exception:
                pass
            if handler_tasks:
                await asyncio.wait(handler_tasks, timeout=max(45.0, self._settings.browser_timeout_s))

        if direct_results:
            cg = direct_results.get("context_get")
            if isinstance(cg, (bytes, bytearray)) and _looks_like_downloadable_media(bytes(cg)):
                return bytes(cg), "context_get"
            pf = direct_results.get("page_fetch")
            if isinstance(pf, (bytes, bytearray)) and _looks_like_downloadable_media(bytes(pf)):
                return bytes(pf), "page_fetch"
        if len(best) >= min_body:
            return bytes(best), "playback_capture"
        msg = "No videoplayback response captured from watch session"
        raise NavigationError(msg, details=f"best_len={len(best)}")

    async def capture_videoplayback_bytes_from_watch(
        self,
        watch_url: str,
        *,
        max_bytes: int | None,
        listen_timeout_s: float | None = None,
        min_body: int = 10_240,
        prefer_itag: int | None = None,
        require_url_substrings: tuple[str, ...] | None = None,
        require_clen: str | None = None,
    ) -> bytes:
        """Collect bytes from a ``googlevideo.com/videoplayback`` response fired by the real player.

        Mirrors Playwright’s network monitoring pattern (``page.on("response", ...)``) described in the
        `network guide <https://playwright.dev/python/docs/network>`_: inspect responses from the real
        page, score candidates, and prefer ``Request.resource_type`` ``media`` over ``xhr``/``fetch``.

        Plain GETs to ``streamingData`` URLs often return 403 (GVS / PO binding). The embedded player
        requests URLs that succeed in the same browser context; we pick the best-ranked response body.

        ``require_url_substrings`` drops unrelated ``videoplayback`` traffic when the URL matches at
        least one substring (case-insensitive).

        ``require_clen`` (``clen`` query value from the chosen progressive format) ties the capture to
        the same media object the player metadata advertises, avoiding unrelated adaptive segments.
        """
        try:
            async with self._camoufox() as browser:
                page = await browser.new_page()
                try:
                    await page.goto(
                        watch_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._settings.browser_timeout_s * 1000),
                    )
                    await self._after_youtube_watch_goto(page)
                    await self._maybe_skip_youtube_preroll_ads(
                        page,
                        total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                    )
                    data, _ = await self._collect_videoplayback_bytes_on_loaded_page(
                        page,
                        listen_timeout_s=listen_timeout_s,
                        max_bytes=max_bytes,
                        min_body=min_body,
                        prefer_itag=prefer_itag,
                        require_url_substrings=require_url_substrings,
                        require_clen=require_clen,
                    )
                    return data
                finally:
                    try:
                        await page.close()
                    except Exception:
                        log.debug("videoplayback_page_close_failed", exc_info=True)
        except NavigationError:
            raise
        except Exception as exc:  # pragma: no cover - browser dependent
            msg = "capture_videoplayback_bytes_from_watch failed"
            raise NavigationError(msg, details=str(exc)) from exc

    async def try_googlevideo_progressive_on_loaded_page(
        self,
        page: Page,
        watch_url: str,
        media_url: str,
        *,
        max_bytes: int | None,
        prefer_itag: int | None,
        listen_capture_s: float,
        require_clen: str | None,
        network_debug_log: NetworkDebugLog | None = None,
        dash_sniffer_state: "MediaRouteSnifferState | None" = None,
    ) -> tuple[bytes, str]:
        """Run context GET, in-page ``fetch``, and playback capture on an **already loaded** watch page.

        Does not ``goto`` or close ``page`` — callers use :meth:`open_watch_page` for a single tab.
        """
        _ = require_clen
        listen_eff = float(listen_capture_s)
        if max_bytes is None:
            listen_eff = max(listen_eff, 55.0)
        if not self._settings.headless:
            listen_eff = max(listen_eff, 45.0 if max_bytes is None else 38.0)
        pre_listen = (
            (14.0 if not self._settings.headless else 8.5)
            if max_bytes is None
            else (7.5 if not self._settings.headless else 4.5)
        )
        js = """
        async ({ url, maxBytes }) => {
            const headers = { Accept: '*/*' };
            if (maxBytes > 0) {
                headers['Range'] = 'bytes=0-' + String(maxBytes - 1);
            }
            const response = await fetch(url, { credentials: 'include', headers });
            if (!response.ok && response.status !== 206) {
                throw new Error('media_fetch_status_' + response.status);
            }
            const buf = await response.arrayBuffer();
            return Array.from(new Uint8Array(buf));
        }
        """

        direct_results: dict[str, bytes] = {}

        async def _mid_phase(p: Page) -> None:
            murl = (media_url or "").strip()
            if not murl:
                return
            gv_mid = _is_googlevideo_host_url(murl)
            if gv_mid:
                ua_mid = _CHROME_MEDIA_UA
            else:
                try:
                    ua_mid = str(await p.evaluate("() => navigator.userAgent"))
                except Exception:
                    ua_mid = _CHROME_MEDIA_UA
            req_headers: dict[str, str] = {
                "Referer": watch_url,
                "User-Agent": ua_mid,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
            }
            if gv_mid:
                req_headers["Origin"] = "https://www.youtube.com"
            if max_bytes is not None and max_bytes > 0:
                req_headers["Range"] = f"bytes=0-{max_bytes - 1}"
            resp = await p.context.request.get(
                murl,
                headers=req_headers,
                timeout=_media_request_timeout_ms(self._settings),
            )
            st_get = int(resp.status)
            if network_debug_log is not None:
                network_debug_log.add("try_gv_context_get", status=st_get, url=url_preview(murl))
            if st_get in (200, 206):
                body = await resp.body()
                if max_bytes is not None and max_bytes > 0 and len(body) > max_bytes:
                    body = body[:max_bytes]
                if _looks_like_downloadable_media(body):
                    direct_results["context_get"] = body
            cap = int(max_bytes) if (max_bytes is not None and max_bytes > 0) else 0
            try:
                raw = await p.evaluate(js, {"url": murl, "maxBytes": cap})
                if isinstance(raw, list):
                    out = bytes(raw)
                    if cap > 0 and len(out) > cap:
                        out = out[:cap]
                    if _looks_like_downloadable_media(out):
                        if network_debug_log is not None:
                            network_debug_log.add("try_gv_page_fetch", bytes_len=len(out))
                        direct_results["page_fetch"] = out
            except Exception as fe:
                if network_debug_log is not None:
                    network_debug_log.add(
                        "try_gv_page_fetch_ex", error_type=type(fe).__name__, detail=str(fe)[:500]
                    )
                log.debug("one_tab_page_fetch_failed", exc_info=True)

        try:
            return await self._collect_videoplayback_bytes_on_loaded_page(
                page,
                listen_timeout_s=listen_eff,
                max_bytes=max_bytes,
                min_body=512,
                prefer_itag=prefer_itag,
                require_url_substrings=None,
                require_clen=None,
                pre_listen_settle_s=pre_listen,
                mid_phase=_mid_phase,
                direct_results=direct_results,
                progressive_media_url=media_url,
                network_debug_log=network_debug_log,
                dash_state=dash_sniffer_state,
            )
        except NavigationError:
            raise
        except Exception as exc:  # pragma: no cover - browser dependent
            msg = "try_googlevideo_progressive_on_loaded_page failed"
            raise NavigationError(msg, details=str(exc)) from exc

    async def try_googlevideo_progressive_one_tab(
        self,
        watch_url: str,
        media_url: str,
        *,
        max_bytes: int | None,
        prefer_itag: int | None,
        listen_capture_s: float,
        require_clen: str | None,
    ) -> tuple[bytes, str]:
        """One tab, one watch load: ``APIRequest`` GET, ``fetch``, then playback capture (Camoufox = Playwright).

        Prefer :meth:`open_watch_page` + :meth:`try_googlevideo_progressive_on_loaded_page` when you
        already need a watch tab for metadata (single window). See Camoufox usage:
        https://camoufox.com/python/usage.md

        ``require_clen`` is reserved for diagnostics; playback capture does not filter on it so the
        player can request variants that still match ``prefer_itag`` ranking.
        """
        try:
            async with self._camoufox() as browser:
                page = await browser.new_page()
                try:
                    await page.goto(
                        watch_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._settings.browser_timeout_s * 1000),
                    )
                    await self._after_youtube_watch_goto(page)
                    await self._maybe_skip_youtube_preroll_ads(
                        page,
                        total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                    )
                    return await self.try_googlevideo_progressive_on_loaded_page(
                        page,
                        watch_url,
                        media_url,
                        max_bytes=max_bytes,
                        prefer_itag=prefer_itag,
                        listen_capture_s=listen_capture_s,
                        require_clen=require_clen,
                    )
                finally:
                    try:
                        await page.close()
                    except Exception:
                        log.debug("one_tab_download_page_close_failed", exc_info=True)
        except NavigationError:
            raise
        except Exception as exc:  # pragma: no cover - browser dependent
            msg = "try_googlevideo_progressive_one_tab failed"
            raise NavigationError(msg, details=str(exc)) from exc

    async def fetch_bytes_in_watch_context(
        self,
        watch_url: str,
        media_url: str,
        *,
        max_bytes: int | None,
    ) -> bytes:
        """Load ``watch_url`` then GET media via the browser request context (cookies + client TLS)."""
        try:
            async with self._camoufox() as browser:
                page = await browser.new_page()
                try:
                    await page.goto(
                        watch_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._settings.browser_timeout_s * 1000),
                    )
                    await self._after_youtube_watch_goto(page)
                    await self._maybe_skip_youtube_preroll_ads(
                        page,
                        total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                    )
                    await self._post_goto_settle(page)
                    ua = await page.evaluate("() => navigator.userAgent")
                    req_headers: dict[str, str] = {
                        "Referer": watch_url,
                        "User-Agent": str(ua),
                        "Accept": "*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                    if max_bytes is not None and max_bytes > 0:
                        req_headers["Range"] = f"bytes=0-{max_bytes - 1}"
                    resp = await page.context.request.get(
                        media_url,
                        headers=req_headers,
                        timeout=_media_request_timeout_ms(self._settings),
                    )
                    if resp.status not in (200, 206):
                        msg = f"Media GET status {resp.status}"
                        raise NavigationError(msg, details=media_url[:120])
                    body = cast(bytes, await resp.body())
                    if max_bytes is not None and max_bytes > 0 and len(body) > max_bytes:
                        return body[:max_bytes]
                    return body
                finally:
                    with suppress(Exception):
                        await page.close()
        except NavigationError:
            raise
        except Exception as exc:  # pragma: no cover - browser dependent
            msg = "fetch_bytes_in_watch_context failed"
            raise NavigationError(msg, details=str(exc)) from exc

    async def fetch_media_bytes_on_page(
        self,
        page: Page,
        watch_url: str,
        media_url: str,
        *,
        max_bytes: int | None,
        network_debug_log: NetworkDebugLog | None = None,
    ) -> bytes:
        """``GET`` ``media_url`` on an already-open watch ``Page`` (full body unless ``max_bytes``).

        Google Video often rejects bare ``APIRequest`` calls without ``Origin`` and a desktop Chrome UA;
        avoid ``page.evaluate`` for UA on those hosts (navigation races). Retries alternate
        ``context.request`` and ``page.request`` (same cookie jar, slightly different plumbing).
        """
        gv = _is_googlevideo_host_url(media_url)
        if gv:
            ua = _CHROME_MEDIA_UA
        else:
            try:
                ua = str(await page.evaluate("() => navigator.userAgent"))
            except Exception:
                ua = _CHROME_MEDIA_UA
        req_headers: dict[str, str] = {
            "Referer": watch_url,
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if gv:
            req_headers["Origin"] = "https://www.youtube.com"
        if max_bytes is not None and max_bytes > 0:
            req_headers["Range"] = f"bytes=0-{max_bytes - 1}"

        timeout_ms = _media_request_timeout_ms(self._settings)
        last_nav: NavigationError | None = None
        clients: tuple[tuple[str, Any], ...] = (
            ("context", page.context.request),
            ("page", page.request),
        )
        for attempt in range(4):
            for label, api in clients:
                try:
                    resp = await api.get(media_url, headers=req_headers, timeout=timeout_ms)
                    st_r = int(resp.status)
                    if st_r not in (200, 206):
                        if network_debug_log is not None:
                            network_debug_log.add(
                                "fetch_media_bytes_on_page",
                                client=label,
                                attempt=attempt,
                                status=st_r,
                                url=url_preview(media_url),
                            )
                        last_nav = NavigationError(
                            f"Media GET status {st_r} ({label})",
                            details=media_url[:120],
                        )
                        continue
                    body = cast(bytes, await resp.body())
                    if max_bytes is not None and max_bytes > 0 and len(body) > max_bytes:
                        body = body[:max_bytes]
                    if network_debug_log is not None:
                        network_debug_log.add(
                            "fetch_media_bytes_on_page_ok",
                            client=label,
                            attempt=attempt,
                            status=st_r,
                            body_len=len(body),
                            url=url_preview(media_url),
                        )
                    log.info(
                        "fetch_media_bytes_on_page_ok",
                        extra={"bytes": len(body), "client": label, "attempt": attempt},
                    )
                    return bytes(body)
                except Exception as exc:
                    if network_debug_log is not None:
                        network_debug_log.add(
                            "fetch_media_bytes_on_page_ex",
                            client=label,
                            attempt=attempt,
                            error_type=type(exc).__name__,
                            detail=str(exc)[:400],
                        )
                    last_nav = NavigationError(
                        f"Media GET failed ({label})",
                        details=str(exc)[:400],
                    )
                    log.debug("fetch_media_bytes_try_failed", extra={"label": label, "error": str(exc)})
            await asyncio.sleep(0.5 + 0.35 * attempt)
        if network_debug_log is not None and last_nav is not None:
            network_debug_log.add("fetch_media_bytes_gave_up", detail=str(last_nav)[:500])
        raise last_nav or NavigationError("Media GET failed", details=media_url[:120])

    async def fetch_media_via_page_fetch_on_page(
        self,
        page: Page,
        watch_url: str,
        media_url: str,
        *,
        max_bytes: int | None,
    ) -> bytes:
        """Same-tab ``fetch(media_url)`` with ``credentials: 'include'`` (often succeeds when APIRequest 403s)."""
        _ = watch_url
        # Enhanced fetch with more browser-like headers
        js = """
        async ({ url, maxBytes }) => {
            const headers = {
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'identity',
                'Origin': 'https://www.youtube.com',
                'Referer': 'https://www.youtube.com/watch',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'cross-site',
                'User-Agent': navigator.userAgent
            };
            if (maxBytes > 0) {
                headers['Range'] = 'bytes=0-' + String(maxBytes - 1);
            }
            try {
                const response = await fetch(url, {
                    credentials: 'include',
                    headers: headers,
                    mode: 'cors'
                });
                if (!response.ok && response.status !== 206) {
                    throw new Error('media_fetch_status_' + response.status);
                }
                const buf = await response.arrayBuffer();
                return Array.from(new Uint8Array(buf));
            } catch (e) {
                throw new Error('fetch_error: ' + e.message);
            }
        }
        """
        cap = int(max_bytes) if (max_bytes is not None and max_bytes > 0) else 0
        raw = await page.evaluate(js, {"url": media_url, "maxBytes": cap})
        if not isinstance(raw, list):
            msg = "page fetch returned unexpected type"
            raise NavigationError(msg, details=str(type(raw)))
        out = bytes(cast(list[int], raw))
        if cap > 0 and len(out) > cap:
            out = out[:cap]
        return bytes(out)

    async def fetch_media_via_page_ranged_sequential(
        self,
        page: Page,
        watch_url: str,
        media_url: str,
        *,
        total_bytes: int,
        max_bytes: int | None = None,
        chunk_size: int = 1_048_576,
    ) -> bytes:
        """Download ``media_url`` in same-tab ``fetch`` **Range** slices (base64 per round-trip).

        A single full-body ``fetch`` would materialize tens of MB as a JS array and blow Playwright's
        IPC limits. Sequential 206/200 range responses reuse the watch **credentials** and typically
        succeed where bare ``httpx`` gets 403.
        """
        _ = watch_url
        if total_bytes <= 0:
            msg = "total_bytes must be positive for ranged page fetch"
            raise NavigationError(msg, details=str(total_bytes))
        eff_total = total_bytes
        if max_bytes is not None and max_bytes > 0:
            eff_total = min(eff_total, int(max_bytes))
        cs = max(65_536, min(int(chunk_size), 4_194_304))
        chunk_timeout_ms = int(
            min(300_000, max(60_000, self._settings.media_download_timeout_s * 400)),
        )
        js = """
        async ({ url, start, end, allowShort }) => {
            const expected = end - start + 1;
            const response = await fetch(url, {
                credentials: 'include',
                headers: {
                    Accept: '*/*',
                    Range: 'bytes=' + start + '-' + end,
                },
            });
            if (!response.ok && response.status !== 206) {
                throw new Error('media_fetch_status_' + response.status);
            }
            const buf = await response.arrayBuffer();
            let u8 = new Uint8Array(buf);
            if (u8.length !== expected) {
                if (response.status === 200 && u8.length > expected) {
                    u8 = u8.subarray(0, expected);
                } else if (allowShort && u8.length < expected && u8.length > 0) {
                    /* final Range may be shorter */
                } else if (u8.length > expected) {
                    u8 = u8.subarray(0, expected);
                } else {
                    throw new Error('media_range_len_' + u8.length + '_exp_' + expected);
                }
            }
            let binary = '';
            const CH = 0x8000;
            for (let i = 0; i < u8.length; i += CH) {
                const sub = u8.subarray(i, Math.min(i + CH, u8.length));
                binary += String.fromCharCode.apply(null, sub);
            }
            return btoa(binary);
        }
        """
        out = bytearray()
        offset = 0
        n_chunk = 0
        while offset < eff_total:
            end = min(offset + cs - 1, eff_total - 1)
            span = end - offset + 1
            allow_short = end == eff_total - 1
            try:
                b64_s = await asyncio.wait_for(
                    page.evaluate(
                        js,
                        {
                            "url": media_url,
                            "start": offset,
                            "end": end,
                            "allowShort": 1 if allow_short else 0,
                        },
                    ),
                    timeout=chunk_timeout_ms / 1000.0,
                )
            except Exception as exc:
                msg = "page ranged fetch evaluate failed"
                raise NavigationError(msg, details=f"offset={offset} err={exc!s}") from exc
            if not isinstance(b64_s, str):
                msg = "page ranged fetch returned non-string"
                raise NavigationError(msg, details=type(b64_s).__name__)
            try:
                chunk = base64.b64decode(b64_s, validate=True)
            except Exception as exc:
                msg = "page ranged fetch base64 decode failed"
                raise NavigationError(msg, details=f"offset={offset}") from exc
            if len(chunk) != span:
                if end == eff_total - 1 and len(chunk) < span and len(chunk) > 0:
                    out.extend(chunk)
                    log.info(
                        "page_ranged_last_chunk_partial",
                        extra={"offset": offset, "got": len(chunk), "expected": span},
                    )
                    break
                if len(chunk) > span:
                    chunk = chunk[:span]
                else:
                    msg = "page ranged fetch chunk size mismatch"
                    raise NavigationError(
                        msg,
                        details=f"offset={offset} got={len(chunk)} expected={span}",
                    )
            out.extend(chunk)
            offset += len(chunk)
            n_chunk += 1
            if n_chunk % 8 == 0:
                log.info(
                    "page_ranged_progress",
                    extra={"bytes": len(out), "target": eff_total, "chunks": n_chunk},
                )
            if len(chunk) < span:
                break
        return bytes(out)

    async def fetch_dash_fragments_by_sidx(
        self,
        page: Page,
        media_url: str,
        captured_init: bytes,
        *,
        max_bytes: int | None = None,
    ) -> bytes:
        """Fetch complete DASH video by requesting fragments based on sidx box.

        This uses the segment index (sidx) from captured init data to make
        range requests for each fragment, assembling a complete video file.

        Args:
            page: Playwright page with active browser session
            media_url: The deciphered googlevideo URL
            captured_init: Initial bytes containing init segment + sidx
            max_bytes: Optional maximum bytes to download

        Returns:
            Complete assembled video file
        """
        from youtube_scrape.domain.dash_assembler import (
            get_fragment_byte_ranges,
            parse_sidx_box,
            find_sidx_box,
        )
        from youtube_scrape.domain.ump_unwrap import unwrap_ump_to_fragments

        # Parse sidx to get fragment ranges
        ranges = get_fragment_byte_ranges(captured_init, base_offset=0)

        if not ranges:
            log.warning("dash_assembler_no_sidx", extra={"url": url_preview(media_url)})
            return b""

        log.info(
            "dash_assembler_fragments",
            extra={
                "fragments": len(ranges),
                "url": url_preview(media_url),
                "total_bytes": sum(r[1] - r[0] + 1 for r in ranges),
            },
        )

        # Prepare result with init segment
        result = bytearray()

        # Extract init (everything before first moof)
        # Find first moof position
        moof_pos = captured_init.find(b"moof")
        if moof_pos > 0:
            init_segment = captured_init[:moof_pos]
            result.extend(init_segment)
        else:
            result.extend(captured_init)

        # Fetch each fragment by range
        for i, (start, end) in enumerate(ranges):
            span = end - start + 1

            # Check max_bytes limit
            if max_bytes is not None and len(result) >= max_bytes:
                log.info("dash_assembler_max_bytes_reached", extra={"fragment": i})
                break

            # Calculate effective end if max_bytes is set
            eff_end = end
            if max_bytes is not None:
                remaining = max_bytes - len(result)
                if remaining <= 0:
                    break
                eff_end = min(end, start + remaining - 1)

            try:
                chunk = await self._fetch_single_range(page, media_url, start, eff_end)
                if chunk:
                    result.extend(chunk)
                    log.debug(
                        "dash_assembler_fragment_fetched",
                        extra={
                            "fragment": i,
                            "range": f"{start}-{eff_end}",
                            "bytes": len(chunk),
                        },
                    )
                else:
                    log.warning(
                        "dash_assembler_empty_fragment",
                        extra={"fragment": i, "range": f"{start}-{eff_end}"},
                    )
            except Exception as exc:
                log.warning(
                    "dash_assembler_fragment_failed",
                    extra={
                        "fragment": i,
                        "range": f"{start}-{eff_end}",
                        "error": str(exc)[:100],
                    },
                )
                # Continue with next fragment - partial video is better than nothing
                continue

        return bytes(result)

    async def _fetch_single_range(
        self,
        page: Page,
        url: str,
        start: int,
        end: int,
        timeout_s: float = 15.0,
    ) -> bytes:
        """Fetch a single byte range via in-page fetch."""
        import base64

        js = """
        async ({ url, start, end, timeoutSec }) => {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), timeoutSec * 1000);
            try {
                const response = await fetch(url, {
                    credentials: 'include',
                    signal: controller.signal,
                    headers: {
                        'Accept': '*/*',
                        'Range': 'bytes=' + start + '-' + end,
                        'Origin': 'https://www.youtube.com',
                        'Referer': 'https://www.youtube.com/watch',
                    },
                });
                clearTimeout(timeoutId);
                if (!response.ok && response.status !== 206) {
                    throw new Error('range_fetch_status_' + response.status);
                }
                const buf = await response.arrayBuffer();
                let binary = '';
                const bytes = new Uint8Array(buf);
                const len = bytes.byteLength;
                for (let i = 0; i < len; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                return btoa(binary);
            } catch (e) {
                clearTimeout(timeoutId);
                throw e;
            }
        }
        """

        try:
            result = await asyncio.wait_for(
                page.evaluate(js, {"url": url, "start": start, "end": end, "timeoutSec": timeout_s}),
                timeout=timeout_s + 5.0,  # Python-side timeout slightly longer than JS
            )
        except asyncio.TimeoutError:
            raise NavigationError(f"Range fetch timed out for bytes {start}-{end}")
        if not isinstance(result, str):
            raise NavigationError("Range fetch returned non-string")

        # Decode base64
        try:
            return base64.b64decode(result, validate=True)
        except Exception as exc:
            raise NavigationError(f"Base64 decode failed: {exc}")

    async def download_via_new_tab(
        self,
        page: Page,
        media_url: str,
        *,
        max_bytes: int | None,
    ) -> bytes:
        """Navigate to media URL in a new tab to trigger download; capture via response listener.

        This is a last-resort method when other fetch approaches fail. The browser's
        native download handling is used, which often bypasses CSP and other restrictions.
        """
        # Create a promise that resolves when we get the response
        future: asyncio.Future[bytes] = asyncio.get_event_loop().create_future()

        async def _on_response(response: Any) -> None:
            if future.done():
                return
            try:
                u = str(response.url or "")
                if "videoplayback" in u and _is_googlevideo_host_url(u):
                    body = await response.body()
                    if body and len(body) > 1000:
                        if not future.done():
                            future.set_result(bytes(body))
            except Exception:
                pass

        # Listen for responses
        page.on("response", _on_response)

        try:
            # Open media URL in new tab
            new_page = await page.context.new_page()
            try:
                # Add listener to new page too
                new_page.on("response", _on_response)

                # Navigate to media URL
                await new_page.goto(
                    media_url,
                    wait_until="networkidle",
                    timeout=30000,
                )

                # Wait for response
                try:
                    result = await asyncio.wait_for(future, timeout=30.0)
                    if max_bytes is not None and len(result) > max_bytes:
                        return result[:max_bytes]
                    return result
                except asyncio.TimeoutError:
                    raise NavigationError("No media response captured in new tab")
            finally:
                await new_page.close()
        finally:
            try:
                page.remove_listener("response", _on_response)
            except Exception:
                pass

    async def fetch_bytes_via_page_fetch(
        self,
        watch_url: str,
        media_url: str,
        *,
        max_bytes: int | None,
    ) -> bytes:
        """Same-origin ``fetch`` from the watch page (cookies); sometimes succeeds when APIRequest does not."""
        js = """
        async ({ url, maxBytes }) => {
            const headers = { Accept: '*/*' };
            if (maxBytes > 0) {
                headers['Range'] = 'bytes=0-' + String(maxBytes - 1);
            }
            const response = await fetch(url, { credentials: 'include', headers });
            if (!response.ok && response.status !== 206) {
                throw new Error('media_fetch_status_' + response.status);
            }
            const buf = await response.arrayBuffer();
            return Array.from(new Uint8Array(buf));
        }
        """
        try:
            async with self._camoufox() as browser:
                page = await browser.new_page()
                try:
                    await page.goto(
                        watch_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._settings.browser_timeout_s * 1000),
                    )
                    await self._after_youtube_watch_goto(page)
                    await self._maybe_skip_youtube_preroll_ads(
                        page,
                        total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                    )
                    await self._post_goto_settle(page)
                    cap = int(max_bytes) if (max_bytes is not None and max_bytes > 0) else 0
                    raw = await page.evaluate(js, {"url": media_url, "maxBytes": cap})
                    if not isinstance(raw, list):
                        msg = "fetch_via_page returned unexpected payload"
                        raise NavigationError(msg, details=type(raw).__name__)
                    out = bytes(raw)
                    if cap > 0 and len(out) > cap:
                        return out[:cap]
                    return out
                finally:
                    with suppress(Exception):
                        await page.close()
        except NavigationError:
            raise
        except Exception as exc:  # pragma: no cover - browser dependent
            msg = "fetch_bytes_via_page_fetch failed"
            raise NavigationError(msg, details=str(exc)) from exc

    async def extract_watch_payload(
        self,
        watch_url: str,
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        last_error: Exception | None = None
        for attempt in range(self._settings.max_navigation_retries):
            try:
                return await self._extract_once(watch_url)
            except (NavigationError, ExtractionError, TimeoutError) as exc:
                last_error = exc
                log.warning(
                    "watch_navigation_failed",
                    extra={"url": watch_url, "attempt": attempt, "error": str(exc)},
                )
                if attempt + 1 == self._settings.max_navigation_retries:
                    break
                await asyncio.sleep(self._settings.navigation_backoff_s * (attempt + 1))
        msg = f"Failed to load watch page after retries: {watch_url}"
        raise NavigationError(msg, details=str(last_error))

    async def _extract_once(self, watch_url: str) -> tuple[dict[str, Any], dict[str, Any], str]:
        try:
            async with self._camoufox() as browser:
                page = await browser.new_page()
                try:
                    await page.goto(
                        watch_url,
                        wait_until="domcontentloaded",
                        timeout=int(self._settings.browser_timeout_s * 1000),
                    )
                    await self._after_youtube_watch_goto(page)
                    await self._maybe_skip_youtube_preroll_ads(
                        page,
                        total_budget_s=self._settings.youtube_preroll_ad_skip_budget_s,
                    )
                    await self._post_goto_settle(page)
                    html = await page.content()
                finally:
                    with suppress(Exception):
                        await page.close()
        except Exception as exc:  # pragma: no cover - network/browser dependent
            msg = "Camoufox navigation raised an unexpected error"
            raise NavigationError(msg, details=str(exc)) from exc

        try:
            player = extract_yt_initial_player_response(html)
        except ExtractionError:
            raise
        try:
            initial = extract_yt_initial_data(html)
        except ExtractionError:
            initial = {}
        return player, initial, html
