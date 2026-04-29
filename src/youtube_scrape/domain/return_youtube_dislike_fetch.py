"""Optional fetch for **video** dislike (and duplicate like) totals from Return YouTube Dislike.

Public YouTube no longer publishes dislike totals in the player / watch renderer (often only "Dislike
this video" in accessibility strings). Return YouTube Dislike documents a stable read-only endpoint:

https://returnyoutubedislike.com/docs/fetching — ``GET …/votes?videoId=<id>``.

This data is **community-maintained** (archived pre–Dec 2021 + extrapolation from extension users).
It is **not** an official Google number. ``VideoMetadata.dislike_source`` is set when values come from RYD.

**Comments:** Per-comment dislike / downvote totals are **not** exposed through the InnerTube payloads
we parse (toolbar surfaces like counts only). There is no RYD analogue for arbitrary comment rows.

"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

_VIDEO_ID_OK = re.compile(r"^[a-zA-Z0-9_-]{11}$")

RYD_PUBLIC_VOTES_ENDPOINT = "/votes"


def _as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        try:
            n = int(value)
        except (OverflowError, ValueError):
            return None
        return n if n >= 0 else None
    return None


def parse_ryd_votes_payload(data: Any) -> tuple[int | None, int | None]:
    """Return ``(likes, dislikes)`` from a JSON dict, if present and sane."""
    if not isinstance(data, dict):
        return None, None
    likes = _as_non_negative_int(data.get("likes"))
    dislikes = _as_non_negative_int(data.get("dislikes"))
    return likes, dislikes


def ryd_votes_url(video_id: str, *, base_url: str) -> str:
    """Build the documented query URL (RFC 3986–safe id fragment)."""
    b = base_url.rstrip("/")
    safe = quote(video_id, safe="")
    return f"{b}{RYD_PUBLIC_VOTES_ENDPOINT}?videoId={safe}"


async def fetch_ryd_vote_counts(
    video_id: str,
    *,
    base_url: str = "https://returnyoutubedislikeapi.com",
    timeout_s: float = 5.0,
) -> tuple[int | None, int | None]:
    """GET Return YouTube Dislike public ``/votes`` endpoint; return ``(likes, dislikes)``.

    Returns ``(None, None)`` if the API is unreachable or the id format is invalid.
    """
    if not _VIDEO_ID_OK.match(video_id or ""):
        return None, None
    url = ryd_votes_url(video_id, base_url=base_url)
    headers = {
        "Accept": "application/json",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }
    try:
        timeout = httpx.Timeout(timeout_s)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        log.debug(
            "ryd_votes_request_failed",
            extra={"video_id": video_id, "url": url, "error": str(exc)},
        )
        return None, None
    if resp.status_code == 404:
        log.debug("ryd_votes_not_found", extra={"video_id": video_id})
        return None, None
    try:
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.debug("ryd_votes_bad_status", extra={"video_id": video_id, "error": str(exc)})
        return None, None
    try:
        data = resp.json()
    except ValueError:
        log.debug("ryd_votes_bad_json", extra={"video_id": video_id})
        return None, None
    likes, dislikes = parse_ryd_votes_payload(data)
    if likes is None and dislikes is None:
        log.debug("ryd_votes_empty_numbers", extra={"video_id": video_id})
        return None, None
    return likes, dislikes
