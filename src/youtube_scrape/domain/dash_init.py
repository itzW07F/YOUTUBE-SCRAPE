"""DASH fMP4 init segment detection and googlevideo URL itag parsing."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# Match itag=... in URL with various encodings (SABR / signed params).
_TAG_LOOSE = re.compile(
    r"itag(?:%25?3D|\s*=\s*|---|--)(\d+)",
    re.IGNORECASE,
)
_TAG_AMP = re.compile(r"[\?&]itag=(\d+)(?:$|&|#)", re.IGNORECASE)


def _unquote_cascade(s: str, *, rounds: int = 4) -> str:
    prev = s
    for _ in range(rounds):
        nxt = unquote(prev)
        if nxt == prev:
            return nxt
        prev = nxt
    return nxt


def itag_from_videoplayback_url(url: str) -> int | None:
    """``itag`` from a ``googlevideo.com/.../videoplayback?...`` request URL (best-effort)."""
    if not url:
        return None
    if "videoplayback" not in url and "googlevideo" not in url and "googleusercontent" not in url:
        return None
    uq = _unquote_cascade(url)
    for candidate in (uq, url):
        try:
            q: dict[str, Any] = parse_qs(urlparse(candidate).query, keep_blank_values=True)
        except (TypeError, ValueError, AttributeError):
            q = {}
        for key in ("itag", "ITAG", "Itag"):
            vals = q.get(key)
            if not vals:
                continue
            s0 = str((vals[0] if isinstance(vals, list) else vals) or "").strip()
            try:
                return int(s0.split(".", 1)[0], 10)
            except (TypeError, ValueError, AttributeError):
                continue
        m = _TAG_AMP.search(candidate)
        if m:
            try:
                return int(m.group(1), 10)
            except ValueError:
                pass
    for blob in (uq, url):
        m = _TAG_LOOSE.search(blob)
        if m:
            try:
                return int(m.group(1), 10)
            except ValueError:
                pass
    return None


def _first_top_level_mdat_index(body: bytes, *, max_scan: int) -> int | None:
    """Index of a **top-level** ``mdat`` box, or None if not found in the scanned prefix."""
    n = min(len(body), max_scan)
    i = 0
    while i + 8 <= n:
        s32 = int.from_bytes(body[i : i + 4], "big")
        if s32 < 1:
            i += 1
            continue
        if s32 == 1:
            if i + 16 > n:
                break
            box_len = int.from_bytes(body[i + 8 : i + 16], "big")
            hlen = 16
        else:
            box_len = s32
            hlen = 8
        if box_len < hlen or i + box_len > len(body):
            i += 1
            continue
        kind = body[i + 4 : i + 8]
        if kind == b"mdat":
            return i
        i += box_len
    return None


def is_dash_init_fmp4(body: bytes) -> bool:
    """DASH init: ``ftyp`` + ``moov``; no top-level ``mdat``/``moof`` before media."""
    if not body or len(body) < 32:
        return False
    n = min(len(body), 4_000_000)
    head = body[:n]
    if b"ftyp" not in head and b"ftyp" not in body[: 16_384]:
        return False
    if b"moov" not in head:
        return False
    if b"moof" in head:
        return False
    if _first_top_level_mdat_index(body, max_scan=n) is not None:
        return False
    return True
