"""Application service: download progressive or plain adaptive streams."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from youtube_scrape.adapters.browser_playwright import (
    CamoufoxBrowserSession,
    MediaRouteSnifferState,
    _guess_mp4_codec_hint,
    _iso_bmff_moof_before_mdat,
    _looks_like_downloadable_media,
)
from youtube_scrape.adapters.http_httpx import HttpxHttpClient
from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.application.network_debug import NetworkDebugLog, body_sha256_prefix, url_preview
from youtube_scrape.domain.format_selector import (
    select_best_audio_format,
    select_best_progressive_format,
    select_by_itag,
    select_worst_audio_format,
    select_worst_progressive_format,
)
from youtube_scrape.domain.json_extract import extract_yt_initial_data, extract_yt_initial_player_response
from youtube_scrape.domain.models import ResultEnvelope
from youtube_scrape.domain.player_parser import (
    parse_muxed_progressive_formats,
    parse_stream_formats,
    parse_video_metadata,
)
from youtube_scrape.domain.ports import BrowserSession, FileSink, HttpClient
from youtube_scrape.domain.safe_filename import safe_video_filename
from youtube_scrape.domain.js_decipher import (
    is_decipher_available,
    decipher_format_url,
    close_global_decipherer,
)
from youtube_scrape.domain.player_js_extract import (
    extract_player_js_url,
    build_decipher_js,
    cache_player,
    get_cached_player,
)
from youtube_scrape.domain.ump_unwrap import unwrap_ump_media_file
from youtube_scrape.domain.dash_assembler import (
    get_fragment_byte_ranges,
    estimate_content_length,
)
from youtube_scrape.domain.signature_cipher import (
    googlevideo_url_hint,
    is_googlevideo_media_url,
    needs_deciphering,
)
from youtube_scrape.domain.youtube_url import watch_url
from youtube_scrape.exceptions import (
    ExtractionError,
    HttpTransportError,
    NavigationError,
    UnsupportedFormatError,
    YouTubeScrapeError,
)
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)

Selection = Literal["best", "worst"] | int
StreamKind = Literal["video", "audio"]
AudioEncoding = Literal["container", "mp3"]


def _output_path_from_watch_title(
    out_dir: Path,
    player: dict[str, Any],
    *,
    stream_kind: StreamKind,
    audio_encoding: AudioEncoding,
) -> Path:
    """Build ``<dir>/<sanitized watch title>.<ext>`` from ``player`` (``videoDetails.title``)."""
    meta = parse_video_metadata(player)
    raw_title = (meta.title or "").strip()
    if not raw_title:
        msg = "Watch page did not expose a title for output naming."
        raise UnsupportedFormatError(msg, details="missing_title")
    ext = ".mp3" if audio_encoding == "mp3" else ".mp4"
    if stream_kind == "audio" and audio_encoding == "container":
        ext = ".m4a"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / safe_video_filename(raw_title, extension=ext)


def _content_length_int(chosen: dict[str, Any]) -> int | None:
    raw = chosen.get("contentLength")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().isdigit():
        return int(raw.strip(), 10)
    return None


def _clen_from_videoplayback_url(media_url: str) -> int | None:
    """``clen`` / ``size`` from a ``googlevideo`` ``videoplayback`` URL when ``streamingData`` omits length."""
    qs = parse_qs(urlparse(media_url).query)
    for key in ("clen", "size"):
        vals = qs.get(key)
        if vals and str(vals[0]).strip().isdigit():
            return int(str(vals[0]).strip(), 10)
    return None


def _mime_head(mime: str | None) -> str:
    if not isinstance(mime, str):
        return ""
    return mime.split(";", 1)[0].strip().lower()


def _choose_stream_format(
    formats: list[dict[str, Any]],
    selection: Selection,
    stream_kind: StreamKind,
) -> dict[str, Any]:
    if isinstance(selection, int):
        fmt = select_by_itag(formats, selection)
        if stream_kind == "audio":
            head = _mime_head(fmt.get("mimeType"))
            if not head.startswith("audio/"):
                msg = f"itag={selection} is not an audio-only format; use --stream video or pick an audio itag"
                raise UnsupportedFormatError(msg, details="itag_not_audio")
        return fmt
    if stream_kind == "audio":
        if selection == "best":
            return select_best_audio_format(formats)
        return select_worst_audio_format(formats)
    if selection == "best":
        return select_best_progressive_format(formats)
    return select_worst_progressive_format(formats)


def _isobmff_ftyp_prefix(data: bytes, *, scan: int = 65_536) -> bool:
    return b"ftyp" in data[:scan]


def _needs_mp4_ftyp_guard(chosen: dict[str, Any]) -> bool:
    head = _mime_head(chosen.get("mimeType"))
    return head == "video/mp4" or head == "audio/mp4"


def _try_ffmpeg_repair_fmp4_fragment(in_path: Path) -> tuple[Path | None, str]:
    """Best-effort remux; unwraps UMP first, then repairs with ffmpeg.

    Enhanced to handle YouTube's UMP-wrapped DASH fragments.
    """
    if shutil.which("ffmpeg") is None:
        return None, "ffmpeg_not_on_path"

    # First, try to unwrap UMP format if present
    from youtube_scrape.domain.ump_unwrap import unwrap_ump_media_file

    unwrapped_path = in_path.parent / f"{in_path.stem}.unwrapped{in_path.suffix}"
    unwrapped_path.unlink(missing_ok=True)

    try:
        raw_data = in_path.read_bytes()
        unwrapped = unwrap_ump_media_file(raw_data)
        if unwrapped and len(unwrapped) > len(raw_data) * 0.5:
            # Unwrapping produced valid data, use it
            unwrapped_path.write_bytes(unwrapped)
            source_for_repair = unwrapped_path
            repair_method_prefix = "ump_unwrap_"
        else:
            source_for_repair = in_path
            repair_method_prefix = ""
    except Exception as e:
        # Unwrapping failed, use original
        source_for_repair = in_path
        repair_method_prefix = ""

    out_path = in_path.parent / f"{in_path.stem}.repaired{in_path.suffix}"
    out_path.unlink(missing_ok=True)

    attempts: list[tuple[list[str], str]] = [
        # First: try copy remux (fast)
        (["-fflags", "+genpts+igndts", "-i", str(source_for_repair), "-c", "copy", "-movflags", "+faststart", str(out_path)], f"{repair_method_prefix}copy_faststart"),
        (["-fflags", "+genpts+igndts+discardcorrupt", "-i", str(source_for_repair), "-c", "copy", str(out_path)], f"{repair_method_prefix}copy_genpts_igndts"),
        # Last resort: transcode to H.264 (slow but fixes bitstream corruption)
        (["-fflags", "+genpts+igndts+discardcorrupt", "-i", str(source_for_repair), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-movflags", "+faststart", str(out_path)], f"{repair_method_prefix}transcode_h264"),
    ]
    last_err = ""
    for argv_tail, method in attempts:
        out_path.unlink(missing_ok=True)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *argv_tail]
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=300)
        last_err = (proc.stderr or proc.stdout or "")[-2000:].strip()
        if (
            proc.returncode == 0
            and out_path.is_file()
            and out_path.stat().st_size > 0
        ):
            # Cleanup temp file if we created one
            unwrapped_path.unlink(missing_ok=True)
            return out_path, method

    # Cleanup temp file
    unwrapped_path.unlink(missing_ok=True)
    return None, last_err or "ffmpeg_repair_nonzero"


def _ffmpeg_input_suffix(mime: str | None) -> str:
    head = _mime_head(mime)
    if head == "audio/webm":
        return ".webm"
    if head in ("audio/mp4", "audio/m4a"):
        return ".m4a"
    if head.startswith("audio/"):
        return ".webm"
    return ".bin"


def _read_file_prefix(path: Path, limit: int) -> bytes:
    with path.open("rb") as f:
        return f.read(limit)


def _prefix_looks_like_media(b: bytes) -> bool:
    if not b:
        return False
    return _looks_like_downloadable_media(b[: min(len(b), 131_072)])


def _nd_record_sniffer_and_spool(nd: NetworkDebugLog, output_path: Path, sniff: Any) -> None:
    mrg = sniff.try_merge_byte_range_assembly()
    d = {
        "best_len": len(bytes(sniff.best)),
        "best_prefix_sha16": body_sha256_prefix(bytes(sniff.best)[: 65_536]) if len(sniff.best) else None,
        "range_parts": len(sniff.range_parts),
        "range_total": sniff.range_total,
        "range_mergeable_full": mrg is not None and len(mrg) > 0,
        "range_merged_len": len(mrg) if mrg is not None else 0,
        "prefer_itag": sniff.prefer_itag,
        "dash_init_itag_keys": sorted(sniff.dash_init_by_itag.keys()),
        "dash_init_unkeyed_len": len(sniff.dash_init_unkeyed) if getattr(sniff, "dash_init_unkeyed", None) else 0,
    }
    nd.set_sniffer(d)
    p_spool = output_path.parent / f"{output_path.stem}.network-debug.sniffer-best.bin"
    if len(bytes(sniff.best)) > 0:
        nd.spool_bytes(p_spool, bytes(sniff.best))


def _accept_sniffer_range_merge(
    merged: bytes,
    *,
    stream_kind: StreamKind,
    chosen_mime: Any,
    content_length: int | None,
) -> bool:
    """Prefer full byte-range assembly when it looks like real media (or full-size DASH bytestream)."""
    if not _prefix_looks_like_media(merged):
        return False
    mh = _mime_head(chosen_mime if isinstance(chosen_mime, str) else None)
    if stream_kind != "video" or mh != "video/mp4":
        return True
    return not _iso_bmff_moof_before_mdat(merged) or (
        content_length is not None and len(merged) + 64_000 >= int(content_length)
    )


def _maybe_prepend_dash_init(
    data: bytes,
    sniff: MediaRouteSnifferState,
    chosen: dict[str, Any],
) -> tuple[bytes, bool]:
    """Prepend a captured DASH init segment when ``data`` is a fMP4 fragment and itag matches."""
    if not _iso_bmff_moof_before_mdat(data):
        return data, False
    byi = sniff.dash_init_by_itag
    unkeyed: bytes | None = getattr(sniff, "dash_init_unkeyed", None)
    if not byi and not unkeyed:
        return data, False
    itag: int | None = None
    raw_it = chosen.get("itag")
    if raw_it is not None:
        try:
            itag = int(str(raw_it).split(".", 1)[0], 10)
        except (TypeError, ValueError):
            itag = None
    if itag is None and sniff.prefer_itag is not None:
        itag = int(sniff.prefer_itag)
    init: bytes | None = None
    if itag is not None and itag in byi:
        init = byi[itag]
    elif len(byi) == 1:
        init = next(iter(byi.values()))
    if init is None and unkeyed is not None:
        init = unkeyed
    if not init or len(init) < 8:
        return data, False
    cap = min(len(data), 65_536)
    if data[:cap].startswith(init[: min(len(init), cap)]):
        return data, False
    return init + data, True


def _ffmpeg_encode_file_to_mp3(src_path: Path, dest: Path) -> None:
    if shutil.which("ffmpeg") is None:
        msg = "ffmpeg is not on PATH; install ffmpeg or use audio_encoding=container"
        raise YouTubeScrapeError(msg, details="ffmpeg_missing")
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(src_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(dest),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=7200,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()
        msg = "ffmpeg failed while encoding MP3"
        raise YouTubeScrapeError(msg, details=tail[:2000] if tail else "ffmpeg_nonzero")


def _ffmpeg_encode_bytes_to_mp3(src_bytes: bytes, dest: Path, input_suffix: str) -> None:
    if shutil.which("ffmpeg") is None:
        msg = "ffmpeg is not on PATH; install ffmpeg or use audio_encoding=container"
        raise YouTubeScrapeError(msg, details="ffmpeg_missing")
    with tempfile.NamedTemporaryFile(suffix=input_suffix, delete=False) as tmp:
        tmp.write(src_bytes)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-i",
                str(tmp_path),
                "-vn",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(dest),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=7200,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()
            msg = "ffmpeg failed while encoding MP3"
            raise YouTubeScrapeError(msg, details=tail[:2000] if tail else "ffmpeg_nonzero")
    finally:
        tmp_path.unlink(missing_ok=True)


_GOOGLEVIDEO_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.youtube.com/",
    "Origin": "https://www.youtube.com",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _formats_for_download_selection(
    player: dict[str, Any],
    *,
    selection: Selection,
    stream_kind: StreamKind,
) -> list[dict[str, Any]]:
    """Use muxed progressive rows for video ``best``/``worst``; full list for itag or audio."""
    if isinstance(selection, int):
        return parse_stream_formats(player)
    if stream_kind == "video":
        return parse_muxed_progressive_formats(player)
    return parse_stream_formats(player)


class DownloadMediaService:
    """Resolve a plain ``url`` from ``streamingData`` and write bytes to disk.

    .. deprecated::
        This service is DEPRECATED for video downloads. It produces ~22 second clips
        due to YouTube player buffer limitations and has UMP format corruption issues.
        Use YtDlpDownloadService (via DownloadService facade) for full video downloads.
        This class is kept only as fallback for audio/MP3 extraction.
        See ADR-0006 for details.
    """

    def __init__(
        self,
        *,
        browser: BrowserSession,
        http: HttpClient,
        files: FileSink,
        settings: Settings,
    ) -> None:
        self._browser = browser
        self._http = http
        self._files = files
        self._settings = settings

    async def download(
        self,
        url_or_id: str,
        *,
        selection: Selection,
        output_path: Path,
        experimental: bool,
        max_bytes: int | None = None,
        stream_kind: StreamKind = "video",
        audio_encoding: AudioEncoding = "container",
        derive_output_title_under_dir: Path | None = None,
        network_debug: bool = False,
    ) -> ResultEnvelope:
        """Download media when ``experimental`` is enabled.

        .. deprecated::
            Experimental browser-based download is deprecated. Use yt-dlp for video downloads.
            This method is kept only as fallback for audio/MP3 extraction.
            See ADR-0006 for details.
        """
        if not experimental:
            msg = "Video download is gated behind --experimental-download (see ADR-0004)."
            raise YouTubeScrapeError(msg, details="experimental_required")

        # DEPRECATION WARNING
        log.warning(
            "experimental_download_deprecated",
            extra={
                "message": (
                    "Experimental browser-based download is DEPRECATED and will be removed. "
                    "It produces ~22 second clips with potential playback issues. "
                    "Use yt-dlp (default) for full video downloads. "
                    "This fallback is kept only for audio/MP3 extraction. "
                    "See ADR-0006."
                ),
                "stream_kind": stream_kind,
                "audio_encoding": audio_encoding,
            },
        )
        if audio_encoding == "mp3" and stream_kind != "audio":
            msg = "MP3 output requires stream_kind=audio (strip video; use adaptive audio-only URL)."
            raise YouTubeScrapeError(msg, details="mp3_requires_audio_stream")
        url = watch_url(url_or_id)
        log.info(
            "download_media_start",
            extra={"url": url, "selection": selection, "stream_kind": stream_kind, "audio_encoding": audio_encoding},
        )
        data: bytes | None = None
        staged_media: Path | None = None
        strategy = "http"
        exc_http: HttpTransportError | None = None
        chosen: dict[str, Any]
        nd: NetworkDebugLog | None = None
        dash_init_prepended = False
        dash_init_observed = False

        if isinstance(self._browser, CamoufoxBrowserSession):
            if network_debug:
                nd = NetworkDebugLog()
            cam = self._browser
            async with cam.open_watch_page_with_media_route_capture(
                url, max_capture_bytes=max_bytes, network_debug_log=nd
            ) as (page, sniff):
                html = await page.content()
                try:
                    player = extract_yt_initial_player_response(html)
                except ExtractionError:
                    raise
                if derive_output_title_under_dir is not None:
                    output_path = _output_path_from_watch_title(
                        derive_output_title_under_dir,
                        player,
                        stream_kind=stream_kind,
                        audio_encoding=audio_encoding,
                    )
                with suppress(ExtractionError):
                    extract_yt_initial_data(html)
                formats = _formats_for_download_selection(
                    player, selection=selection, stream_kind=stream_kind
                )
                chosen = _choose_stream_format(formats, selection, stream_kind)
                cipher_playback_only = bool(chosen.get("__cipher_playback_only"))
                media_url: str = ""

                # Try Node.js deciphering if ciphered and Node.js is available
                if cipher_playback_only and is_decipher_available():
                    log.info(
                        "download_media_decipher_start",
                        extra={"itag": chosen.get("itag"), "has_cipher": True},
                    )
                    try:
                        # Extract player JS URL - try player response first, then HTML
                        player_js_url = extract_player_js_url(player)
                        if not player_js_url:
                            # Player response doesn't have it, try the HTML page
                            player_js_url = extract_player_js_url(html)

                        log.info(
                            "download_media_player_js_url",
                            extra={"player_js_url": player_js_url[:120] if player_js_url else None},
                        )

                        if player_js_url:
                            if nd is not None:
                                nd.add("decipher_attempt", player_js_url=player_js_url[:120])

                            # Check cache first
                            cached = get_cached_player(player_js_url)
                            if cached:
                                player_js = cached["js_code"]
                                decipher_js = cached.get("decipher_js")
                                log.info("download_media_player_js_cached", extra={"url": player_js_url[:60]})
                            else:
                                # Fetch player JS via browser context
                                log.info("download_media_fetching_player_js", extra={"url": player_js_url[:60]})
                                player_js = await cam.fetch_text_in_watch_context(url, player_js_url)
                                decipher_js = build_decipher_js(player_js)
                                cache_player(player_js_url, player_js, decipher_js)
                                log.info(
                                    "download_media_player_js_fetched",
                                    extra={
                                        "url": player_js_url[:60],
                                        "js_length": len(player_js),
                                        "has_decipher": bool(decipher_js),
                                    },
                                )

                            if decipher_js:
                                # Decipher the format URL
                                log.info("download_media_deciphering_url")
                                deciphered = await decipher_format_url(chosen, player_js)
                                if deciphered:
                                    media_url = deciphered
                                    cipher_playback_only = False  # We deciphered it!
                                    if nd is not None:
                                        nd.add("decipher_success", itag=chosen.get("itag"))
                                    log.info(
                                        "download_media_deciphered_url",
                                        extra={"itag": chosen.get("itag"), "player": player_js_url[:60]},
                                    )
                                else:
                                    log.warning("download_media_decipher_returned_none")
                            else:
                                log.warning("download_media_no_decipher_js_built")
                        else:
                            log.warning("download_media_no_player_js_url_found")
                    except Exception as exc_decipher:
                        if nd is not None:
                            nd.add("decipher_failed", error=str(exc_decipher)[:200])
                        log.warning(
                            "download_media_decipher_failed",
                            extra={"error": str(exc_decipher), "error_type": type(exc_decipher).__name__},
                        )

                if not media_url:
                    if cipher_playback_only:
                        if nd is not None:
                            nd.add(
                                "cipher_playback_only",
                                itag=chosen.get("itag"),
                                note="n/sig handled by the embedded player; bare GET to parsed url often 403",
                            )
                        media_url = (googlevideo_url_hint(chosen) or "") or ""
                    else:
                        u = chosen.get("url")
                        if not isinstance(u, str) or not u.strip():
                            msg = "Resolved format did not contain a URL string"
                            raise UnsupportedFormatError(msg, details="missing_url")
                        media_url = u
                raw_itag_early = chosen.get("itag")
                if isinstance(raw_itag_early, int):
                    sniff.prefer_itag = raw_itag_early
                elif isinstance(raw_itag_early, str) and raw_itag_early.isdigit():
                    sniff.prefer_itag = int(raw_itag_early, 10)
                # Do not tie the route sniffer to ``clen=``: many player ``videoplayback`` requests omit it;
                # ranking uses ``prefer_itag`` instead. Playback capture still uses ``cl_filter`` below.
                sniff.require_clen = None
                is_gv = is_googlevideo_media_url(media_url) if media_url.strip() else False
                gv_pipeline = is_gv or cipher_playback_only
                headers = dict(_GOOGLEVIDEO_HEADERS) if is_gv else None
                if nd is not None and is_gv:
                    nd.skipped_httpx_googlevideo = True

                # Try browser context GET for googlevideo URLs (including deciphered ones)
                if is_gv and not cipher_playback_only:
                    try:
                        log.info("download_media_trying_context_get", extra={"url_preview": media_url[:80]})
                        bctx = await cam.fetch_media_bytes_on_page(
                            page, url, media_url, max_bytes=max_bytes, network_debug_log=nd
                        )
                        if _prefix_looks_like_media(bctx):
                            data = bctx
                            strategy = "context_get"
                            log.info("download_media_context_get_success", extra={"bytes": len(data)})
                        else:
                            log.warning("download_media_context_get_bad_prefix", extra={"prefix": bctx[:20] if bctx else None})
                    except NavigationError as exc_ctx:
                        log.warning(
                            "download_media_context_get_failed",
                            extra={"error": str(exc_ctx)[:100]},
                        )

                # googlevideo: plain httpx (no same-tab cookies) almost always 403; browser strategies follow.
                if data is None and staged_media is None and not is_gv and not cipher_playback_only:
                    try:
                        if isinstance(self._http, HttpxHttpClient) and max_bytes is None:
                            part = output_path.parent / (output_path.name + ".youtube-scrape.part")
                            await self._http.stream_get_to_file(media_url, part, headers=headers)
                            head = _read_file_prefix(part, 131_072)
                            if is_gv and not _prefix_looks_like_media(head):
                                part.unlink(missing_ok=True)
                            else:
                                staged_media = part
                                strategy = "http"
                        else:
                            got = await self._http.get_bytes(media_url, headers=headers, max_bytes=max_bytes)
                            if not is_gv or _prefix_looks_like_media(got):
                                data = got
                                strategy = "http"
                    except HttpTransportError as e:
                        exc_http = e
                        if staged_media is not None and staged_media.exists():
                            staged_media.unlink(missing_ok=True)
                            staged_media = None
                        if not is_gv:
                            raise

                if data is None and staged_media is None and is_gv and not cipher_playback_only:
                    try:
                        raw_pf = await cam.fetch_media_via_page_fetch_on_page(
                            page, url, media_url, max_bytes=max_bytes
                        )
                        if _prefix_looks_like_media(raw_pf):
                            data = raw_pf
                            strategy = "page_fetch"
                    except Exception as exc_pf:
                        if nd is not None:
                            nd.add("page_fetch_inline_ex", error_type=type(exc_pf).__name__, detail=str(exc_pf)[:500])
                        log.warning(
                            "download_media_page_fetch_inline_failed",
                            extra={"error": str(exc_pf)},
                        )

                if data is None and staged_media is None and is_gv and not cipher_playback_only:
                    exp_rb = _content_length_int(chosen) or _clen_from_videoplayback_url(media_url)
                    # Try to get size from a HEAD request if not available
                    if exp_rb is None:
                        try:
                            head_resp = await page.context.request.head(media_url, timeout=10000)
                            if head_resp.status in (200, 206):
                                cl = head_resp.headers.get('content-length') or head_resp.headers.get('Content-Length')
                                if cl and str(cl).isdigit():
                                    exp_rb = int(cl)
                                    log.info("download_media_got_size_from_head", extra={"bytes": exp_rb})
                        except Exception as e:
                            log.debug("download_media_head_request_failed", extra={"error": str(e)})
                    if exp_rb is not None and exp_rb > 8192:
                        cap_total = exp_rb
                        if max_bytes is not None and max_bytes > 0:
                            cap_total = min(cap_total, int(max_bytes))
                        try:
                            ranged_b = await cam.fetch_media_via_page_ranged_sequential(
                                page,
                                url,
                                media_url,
                                total_bytes=cap_total,
                                max_bytes=max_bytes,
                            )
                        except NavigationError as exc_rb:
                            if nd is not None:
                                nd.add("page_ranged_sequential_failed", detail=str(exc_rb)[:500])
                            log.warning(
                                "download_media_page_ranged_sequential_failed",
                                extra={"error": str(exc_rb)},
                            )
                        else:
                            if _prefix_looks_like_media(ranged_b) and len(ranged_b) > 4096:
                                use_rb = True
                                if (
                                    stream_kind == "video"
                                    and _mime_head(chosen.get("mimeType")) == "video/mp4"
                                ):
                                    near_full = len(ranged_b) + 256_000 >= cap_total
                                    progressive_like = not _iso_bmff_moof_before_mdat(ranged_b)
                                    use_rb = near_full or progressive_like or (
                                        max_bytes is not None and max_bytes > 0
                                    )
                                if use_rb:
                                    data = ranged_b
                                    strategy = "page_ranged_sequential"
                                    log.info(
                                        "download_media_page_ranged_sequential_ok",
                                        extra={"bytes": len(data), "target": cap_total},
                                    )

                # Last resort: navigate to media URL in new tab to trigger browser download
                if data is None and staged_media is None and is_gv and not cipher_playback_only:
                    try:
                        log.info("download_media_trying_new_tab", extra={"url_preview": media_url[:80]})
                        tab_data = await cam.download_via_new_tab(
                            page, media_url, max_bytes=max_bytes
                        )
                        if _prefix_looks_like_media(tab_data):
                            data = tab_data
                            strategy = "new_tab_download"
                            log.info("download_media_new_tab_success", extra={"bytes": len(data)})
                    except Exception as exc_tab:
                        log.warning("download_media_new_tab_failed", extra={"error": str(exc_tab)[:100]})

                if data is None and staged_media is None and gv_pipeline:
                    sn_fast = bytes(sniff.best)
                    if sn_fast and _prefix_looks_like_media(sn_fast):
                        use_sn = stream_kind != "video" or _mime_head(chosen.get("mimeType")) != "video/mp4"
                        if not use_sn and not _iso_bmff_moof_before_mdat(sn_fast):
                            use_sn = True
                        if use_sn:
                            # Try to unwrap UMP format to clean DASH
                            unwrapped = unwrap_ump_media_file(sn_fast)
                            if unwrapped and len(unwrapped) > len(sn_fast) * 0.5:
                                data = unwrapped
                                log.info("download_media_ump_unwrapped", extra={"before": len(sn_fast), "after": len(data)})
                            else:
                                data = sn_fast
                            strategy = "route_sniffer"
                            log.info(
                                "download_media_route_sniffer_early",
                                extra={"bytes": len(data)},
                            )

                if data is None and staged_media is None and gv_pipeline:
                    merged_early = sniff.try_merge_byte_range_assembly()
                    exp_cl = _content_length_int(chosen)
                    if merged_early is not None and _accept_sniffer_range_merge(
                        merged_early,
                        stream_kind=stream_kind,
                        chosen_mime=chosen.get("mimeType"),
                        content_length=exp_cl,
                    ):
                        data = merged_early
                        strategy = "route_sniffer_range_merge"
                        log.info(
                            "download_media_route_sniffer_range_merge_early",
                            extra={"bytes": len(data)},
                        )

                if data is None and staged_media is None and gv_pipeline:
                    prefer_itag = sniff.prefer_itag
                    cl_filter = sniff.require_clen
                    # Extended capture time for full video fragment collection
                    listen_s = max(45.0, self._settings.http_timeout_s * 0.8)
                    if not self._settings.headless:
                        listen_s = max(listen_s, 60.0)
                    if max_bytes is None:
                        listen_s = max(
                            listen_s,
                            120.0,  # At least 2 minutes for full video
                            self._settings.http_timeout_s * 1.5,
                            min(300.0, self._settings.media_download_timeout_s * 0.5),
                        )
                        if not self._settings.headless:
                            listen_s = max(listen_s, 180.0)  # 3 minutes in non-headless
                    last_nav: NavigationError | None = None
                    data_gv: bytes | None = None
                    strategy = "playback_capture"
                    log.info(
                        "download_media_reusing_watch_tab",
                        extra={"watch_url": url, "reason": "context_and_http_exhausted"},
                    )

                    # ACTIVE FRAGMENT CAPTURE: Let video play to accumulate fragments
                    # This runs while route sniffer is active to capture fragments
                    try:
                        log.info("download_media_active_fragment_capture_start")
                        # Prime the video player
                        await cam._prime_video_for_media_capture(page)

                        # Wait for fragments to accumulate during natural playback
                        # Longer capture for more fragments
                        capture_time = min(listen_s, 90.0)  # Up to 90 seconds for more fragments
                        log.info("download_media_waiting_for_fragments", extra={"capture_time": capture_time})
                        await asyncio.sleep(capture_time)

                        log.info("download_media_active_fragment_capture_end", extra={"fragments_bytes": len(sniff.all_fragments), "count": sniff.fragments_count})
                    except Exception as exc_active:
                        log.debug("download_media_active_capture_failed", extra={"error": str(exc_active)[:100]})

                    # Use route sniffer capture - try accumulated fragments first
                    if data_gv is None:
                        # First try all accumulated fragments (for full video)
                        all_fragments = bytes(sniff.all_fragments)
                        if all_fragments and len(all_fragments) > 10000:
                            log.info("download_media_all_fragments_attempt", extra={"bytes": len(all_fragments), "count": sniff.fragments_count})
                            unwrapped_all = unwrap_ump_media_file(all_fragments)
                            if unwrapped_all and len(unwrapped_all) > len(all_fragments) * 0.5:
                                data_gv = unwrapped_all
                                log.info("download_media_all_fragments_unwrapped", extra={"before": len(all_fragments), "after": len(data_gv)})
                            else:
                                data_gv = all_fragments
                            strategy = "route_sniffer_all_fragments"

                        # Fall back to best single response if all_fragments didn't work
                        if data_gv is None or len(data_gv) < 10000:
                            sn_rescue = bytes(sniff.best)
                            if sn_rescue and _prefix_looks_like_media(sn_rescue):
                                # Try to unwrap UMP format
                                unwrapped = unwrap_ump_media_file(sn_rescue)
                                if unwrapped and len(unwrapped) > len(sn_rescue) * 0.5:
                                    data_gv = unwrapped
                                    log.info("download_media_ump_unwrapped_rescue", extra={"before": len(sn_rescue), "after": len(data_gv)})
                                else:
                                    data_gv = sn_rescue
                                strategy = "route_sniffer"

                        # Log sidx info for debugging (range requests don't work due to 403)
                        if data_gv is not None:
                            try:
                                from youtube_scrape.domain.dash_assembler import find_sidx_box, get_fragment_byte_ranges
                                sidx_info = find_sidx_box(data_gv)
                                if sidx_info:
                                    ranges = get_fragment_byte_ranges(data_gv, base_offset=0)
                                    if ranges:
                                        log.info("download_media_sidx_info", extra={
                                            "total_fragments": len(ranges),
                                            "current_bytes": len(data_gv),
                                            "expected_bytes": ranges[-1][1] + 1,
                                        })
                            except Exception:
                                pass

                        if data_gv is None:
                            if nd is not None:
                                _nd_record_sniffer_and_spool(nd, output_path, sniff)
                                nd.set_result(
                                    {
                                        "outcome": "failed",
                                        "detail": str(last_nav)[:2000] if last_nav is not None else str(exc_http),
                                        "http_error": str(exc_http),
                                        "output_path": str(output_path),
                                        "media_url_preview": url_preview(media_url),
                                    }
                                )
                                p_dbg = output_path.parent / f"{output_path.stem}.network-debug.json"
                                nd.write_json(p_dbg)
                            log.warning(
                                "download_media_browser_get_failed",
                                extra={"http_error": str(exc_http)},
                            )
                            msg = (
                                "Download failed: route sniffer, browser context GET, HTTP stream, "
                                "and playback capture could not retrieve media"
                            )
                            raise HttpTransportError(msg, details=str(last_nav)) from last_nav
                    data = data_gv
                    log.info(
                        "download_media_browser_bytes",
                        extra={"bytes": len(data), "watch_url": url, "strategy": strategy},
                    )
                    merged_full = sniff.try_merge_byte_range_assembly()
                    exp_cl = _content_length_int(chosen)
                    if (
                        staged_media is None
                        and merged_full is not None
                        and _accept_sniffer_range_merge(
                            merged_full,
                            stream_kind=stream_kind,
                            chosen_mime=chosen.get("mimeType"),
                            content_length=exp_cl,
                        )
                    ):
                        replace_m = (
                            data is None
                            or len(merged_full) > len(data)
                            or (
                                stream_kind == "video"
                                and _mime_head(chosen.get("mimeType")) == "video/mp4"
                                and data is not None
                                and _iso_bmff_moof_before_mdat(data)
                                and not _iso_bmff_moof_before_mdat(merged_full)
                            )
                            or (
                                exp_cl is not None
                                and data is not None
                                and len(merged_full) + 64_000 >= exp_cl
                                and len(data) + 64_000 < exp_cl
                            )
                        )
                        if replace_m:
                            data = merged_full
                            strategy = "route_sniffer_range_merge"
                            log.info(
                                "download_media_route_sniffer_range_merge",
                                extra={"bytes": len(data)},
                            )
                    if (
                        stream_kind == "video"
                        and _mime_head(chosen.get("mimeType")) == "video/mp4"
                        and strategy == "playback_capture"
                        and _iso_bmff_moof_before_mdat(data)
                        and not cipher_playback_only
                    ):
                        await asyncio.sleep(1.0)
                        try:
                            bfix = await cam.fetch_media_bytes_on_page(
                                page, url, media_url, max_bytes=max_bytes, network_debug_log=nd
                            )
                            if _prefix_looks_like_media(bfix) and not _iso_bmff_moof_before_mdat(bfix):
                                data = bfix
                                strategy = "context_get"
                                log.info(
                                    "download_media_replaced_dash_fragment",
                                    extra={"bytes": len(data)},
                                )
                        except NavigationError:
                            pass
                    sn_merge = bytes(sniff.best)
                    if staged_media is None and sn_merge and _prefix_looks_like_media(sn_merge):
                        cur = data
                        prefer_sn = cur is None or len(sn_merge) > len(cur)
                        if (
                            not prefer_sn
                            and cur is not None
                            and stream_kind == "video"
                            and _mime_head(chosen.get("mimeType")) == "video/mp4"
                        ):
                            cur_dash = _iso_bmff_moof_before_mdat(cur)
                            sn_dash = _iso_bmff_moof_before_mdat(sn_merge)
                            if (cur_dash and not sn_dash) or (
                                (not cur_dash and not sn_dash) and len(sn_merge) > len(cur)
                            ):
                                prefer_sn = True
                        if prefer_sn and strategy != "route_sniffer_range_merge":
                            # Try to unwrap UMP format
                            unwrapped = unwrap_ump_media_file(sn_merge)
                            if unwrapped and len(unwrapped) > len(sn_merge) * 0.5:
                                data = unwrapped
                                log.info("download_media_ump_unmerged", extra={"before": len(sn_merge), "after": len(data)})
                            else:
                                data = sn_merge
                            strategy = "route_sniffer"
                            log.info(
                                "download_media_route_sniffer_chosen",
                                extra={"bytes": len(data)},
                            )
                if data is not None and stream_kind == "video" and _mime_head(chosen.get("mimeType")) == "video/mp4":
                    merged_in, did_pre = _maybe_prepend_dash_init(data, sniff, chosen)
                    if did_pre:
                        data = merged_in
                        dash_init_prepended = True
                        log.info("download_media_dash_init_prepended", extra={"bytes": len(data)})
                dash_init_observed = bool(sniff.dash_init_by_itag) or (sniff.dash_init_unkeyed is not None)
                if nd is not None:
                    _nd_record_sniffer_and_spool(nd, output_path, sniff)
        else:
            player, _initial, _html = await self._browser.extract_watch_payload(url)
            if derive_output_title_under_dir is not None:
                output_path = _output_path_from_watch_title(
                    derive_output_title_under_dir,
                    player,
                    stream_kind=stream_kind,
                    audio_encoding=audio_encoding,
                )
            formats = _formats_for_download_selection(
                player, selection=selection, stream_kind=stream_kind
            )
            chosen = _choose_stream_format(formats, selection, stream_kind)
            media_url = chosen.get("url")
            if not isinstance(media_url, str):
                msg = "Resolved format did not contain a URL string"
                raise UnsupportedFormatError(msg, details="missing_url")
            headers = None
            host = urlparse(media_url).netloc.lower()
            is_gv = "googlevideo.com" in host or "googleusercontent.com" in host
            if is_gv:
                headers = dict(_GOOGLEVIDEO_HEADERS)
            strategy = "http"
            try:
                if isinstance(self._http, HttpxHttpClient) and max_bytes is None:
                    part = output_path.parent / (output_path.name + ".youtube-scrape.part")
                    await self._http.stream_get_to_file(media_url, part, headers=headers)
                    head = _read_file_prefix(part, 131_072)
                    if is_gv and not _prefix_looks_like_media(head):
                        part.unlink(missing_ok=True)
                        raise HttpTransportError(
                            "Downloaded body did not look like Google Video media (HTML block page?).",
                            details="bad_prefix",
                        )
                    staged_media = part
                else:
                    got = await self._http.get_bytes(media_url, headers=headers, max_bytes=max_bytes)
                    if is_gv and not _prefix_looks_like_media(got):
                        raise HttpTransportError(
                            "Downloaded body did not look like Google Video media (HTML block page?).",
                            details="bad_prefix",
                        )
                    data = got
            except HttpTransportError:
                raise

        transcode_mp3 = audio_encoding == "mp3"
        source_bytes_for_payload: int | None = None
        bytes_written: int
        truncated: bool
        codec_hint: str | None

        if staged_media is not None:
            prefix = _read_file_prefix(staged_media, 65_536)
            if _needs_mp4_ftyp_guard(chosen) and not _isobmff_ftyp_prefix(prefix):
                staged_media.unlink(missing_ok=True)
                msg = "Refused to write file: bytes are not a recognizable MP4 (missing ISO BMFF ftyp)."
                raise HttpTransportError(
                    msg,
                    details=f"strategy={strategy}, prefix={prefix[:32]!r}",
                )
            if transcode_mp3:
                dest = output_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                src_sz = staged_media.stat().st_size
                await asyncio.to_thread(_ffmpeg_encode_file_to_mp3, staged_media, dest)
                staged_media.unlink(missing_ok=True)
                bytes_written = output_path.stat().st_size
                source_bytes_for_payload = src_sz
            else:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                staged_media.replace(output_path)
                bytes_written = output_path.stat().st_size
            truncated = False
            if stream_kind == "video" and not transcode_mp3:
                codec_hint = _guess_mp4_codec_hint(_read_file_prefix(output_path, 2_097_152))
            else:
                codec_hint = None
        else:
            if data is None:
                msg = "No media bytes after download strategies"
                raise YouTubeScrapeError(msg, details="no_media")
            if _needs_mp4_ftyp_guard(chosen) and not _isobmff_ftyp_prefix(data):
                msg = "Refused to write file: bytes are not a recognizable MP4 (missing ISO BMFF ftyp)."
                raise HttpTransportError(
                    msg,
                    details=f"strategy={strategy}, byte_len={len(data)}, prefix={data[:32]!r}",
                )
            if transcode_mp3:
                dest = output_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                suffix = _ffmpeg_input_suffix(chosen.get("mimeType"))
                await asyncio.to_thread(_ffmpeg_encode_bytes_to_mp3, data, dest, suffix)
                bytes_written = dest.stat().st_size
                source_bytes_for_payload = len(data)
            else:
                self._files.write_bytes(output_path, data)
                bytes_written = len(data)
            truncated = max_bytes is not None and len(data) >= max_bytes
            codec_hint = _guess_mp4_codec_hint(data) if stream_kind == "video" else None

        caveats: list[str] = []
        fmp4_fragment_only = False
        if (
            stream_kind == "video"
            and not transcode_mp3
            and output_path.exists()
            and _mime_head(chosen.get("mimeType")) == "video/mp4"
        ):
            scan_file = _read_file_prefix(output_path, 2_097_152)
            if not dash_init_prepended and _iso_bmff_moof_before_mdat(scan_file):
                fmp4_fragment_only = True
                log.warning(
                    "download_dash_fmp4_fragment_often_unplayable_in_vlc",
                    extra={"path": str(output_path), "bytes": bytes_written},
                )
                caveats.append(
                    "VLC (and many players) often will not play this file: the bytes are a DASH fMP4 "
                    "segment (e.g. moof before mdat), not a complete progressive MP4 with a normal moov, "
                    "and only a short in-player piece was captured. A long duration line in the UI does "
                    "not mean a full file on disk. See `playback_fix_hint` in the payload for a playable "
                    "re-run, or use range-merge / a longer same-session capture when the pipeline allows."
                )
                if not dash_init_observed:
                    caveats.append(
                        "No separate DASH init fMP4 (ftyp+moov, no mdat) was seen on any videoplayback "
                        "response, so init could not be prepended. The client may have reused a cached init, "
                        "or the stream used `application/vnd.yt-ump` without a stand-alone init we recognize. "
                        "Use the default downloader when yt-dlp is on PATH, or try again with a longer capture."
                    )
        exp_cl = _content_length_int(chosen)
        if exp_cl is not None and bytes_written + 64_000 < exp_cl:
            caveats.append(
                "File size is far smaller than streamingData contentLength: demuxers (including VLC) "
                "often show the full presentation duration from DASH/init metadata even when only a "
                "prefix of media bytes exists on disk, so the timeline can read longer than playable "
                "media. Omit --max-bytes (CLI) or raise the cap for a larger prefix; a complete file "
                "requires streaming the full response."
            )
        mime_s = chosen.get("mimeType")
        if (
            stream_kind == "video"
            and isinstance(mime_s, str)
            and "avc1" in mime_s.lower()
            and codec_hint == "av01"
        ):
            caveats.append(
                "streamingData lists AVC progressive, but captured bytes look like AV1: the watch "
                "player used a different adaptive representation than the plain progressive URL row."
            )
        payload: dict[str, Any] = {
            "path": str(output_path),
            "stream_kind": stream_kind,
            "audio_encoding": audio_encoding,
            "itag": chosen.get("itag"),
            "mimeType": chosen.get("mimeType"),
            "contentLength": chosen.get("contentLength"),
            "bytes_written": bytes_written,
            "truncated": truncated,
            "strategy": strategy,
            "codec_hint": codec_hint,
            "transcoded_to_mp3": transcode_mp3,
        }
        if chosen.get("__cipher_playback_only"):
            payload["cipher_playback_only"] = True
        if dash_init_prepended:
            payload["dash_init_prepended"] = True
        if fmp4_fragment_only or (
            stream_kind == "video"
            and isinstance(chosen.get("mimeType"), str)
            and "avc1" in str(chosen.get("mimeType")).lower()
            and codec_hint == "av01"
        ):
            ytdlp_sibling = output_path.parent / f"{output_path.stem}.yt_dlp{output_path.suffix}"
            payload["playback_fix_hint"] = (
                f"DASH-style fragment or mismatched stream metadata: use the default full-file path "
                f"when yt-dlp is on PATH (omit --experimental-download), for example: "
                f"youtube-scrape download {url!r} -o {str(ytdlp_sibling)}"
            )
        ffmpeg_repair: dict[str, Any] | None = None
        if (
            fmp4_fragment_only
            and self._settings.ffmpeg_repair_dash_fragment
            and output_path.is_file()
        ):
            log.info("download_ffmpeg_repair_attempt", extra={"path": str(output_path)})
            rpath, rinfo = await asyncio.to_thread(_try_ffmpeg_repair_fmp4_fragment, output_path)
            if rpath is not None:
                ffmpeg_repair = {"repaired_path": str(rpath), "method": rinfo}
            else:
                ffmpeg_repair = {
                    "status": "failed",
                    "detail": rinfo,
                    "why_often_fails": (
                        "DASH playback uses a separate init segment; one moof/mdat without that init "
                        "is not a complete MP4, so remux often cannot fix it."
                    ),
                }
        if nd is not None:
            dbg = output_path.parent / f"{output_path.stem}.network-debug.json"
            nd.set_result(
                {
                    "outcome": "ok",
                    "bytes_written": bytes_written,
                    "strategy": strategy,
                    "truncated": truncated,
                    "caveat_count": len(caveats),
                    "fmp4_fragment_only": fmp4_fragment_only,
                    "output_path": str(output_path),
                }
            )
            nd.write_json(dbg)
            spool = output_path.parent / f"{output_path.stem}.network-debug.sniffer-best.bin"
            payload["network_debug"] = {
                "json": str(dbg),
                "sniffer_best_spool": str(spool) if spool.exists() else None,
            }
        if caveats:
            payload["playback_caveats"] = caveats
        if fmp4_fragment_only:
            payload["fmp4_fragment_only"] = True
        if transcode_mp3 and source_bytes_for_payload is not None:
            payload["source_bytes"] = source_bytes_for_payload
        if ffmpeg_repair is not None:
            payload["ffmpeg_repair_attempt"] = ffmpeg_repair

        # Cleanup Node.js decipher process
        close_global_decipherer()

        return make_envelope(settings=self._settings, kind="download", data=payload)

