"""Parse YouTube video identifiers and build canonical watch URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from youtube_scrape.exceptions import ExtractionError

_VIDEO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def parse_video_id(url_or_id: str) -> str:
    """Return an 11-character video id from a watch URL or raw id string."""
    raw = url_or_id.strip()
    if _VIDEO_ID_RE.match(raw):
        return raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if "youtu.be" in host:
        seg = parsed.path.strip("/").split("/")[0]
        if _VIDEO_ID_RE.match(seg):
            return seg
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        qs = parse_qs(parsed.query)
        v = qs.get("v", [""])[0]
        if _VIDEO_ID_RE.match(v):
            return v
        m = re.match(r"^/shorts/([a-zA-Z0-9_-]{11})", parsed.path)
        if m:
            return m.group(1)
        m = re.match(r"^/embed/([a-zA-Z0-9_-]{11})", parsed.path)
        if m:
            return m.group(1)
    msg = f"Unrecognized YouTube URL or video id: {url_or_id!r}"
    raise ExtractionError(msg, details="invalid_video_id")


def watch_url(video_id: str) -> str:
    """Canonical HTTPS watch URL for ``video_id``."""
    vid = parse_video_id(video_id)
    return f"https://www.youtube.com/watch?v={vid}"
