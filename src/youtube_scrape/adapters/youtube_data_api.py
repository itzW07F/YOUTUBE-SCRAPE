"""Thin httpx client for YouTube Data API v3 (no google-api-python-client dependency)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

YOUTUBE_V3_BASE = "https://www.googleapis.com/youtube/v3"
DISCOVERY_YOUTUBE_V3_REST = "https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest"


class YouTubeDataApiError(RuntimeError):
    """Raised when the Data API returns an error payload or unexpected response."""

    def __init__(self, message: str, *, status_code: int | None = None, api_detail: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_detail = api_detail


async def fetch_discovery_document(
    *,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """GET the published discovery JSON for youtube v3."""
    resp = await client.get(DISCOVERY_YOUTUBE_V3_REST)
    text = resp.text
    if resp.status_code != 200:
        raise YouTubeDataApiError(
            f"YouTube discovery HTTP {resp.status_code}",
            status_code=resp.status_code,
            api_detail=text[:500] if text else None,
        )
    try:
        data = resp.json()
    except Exception as exc:
        raise YouTubeDataApiError(f"Invalid discovery JSON: {exc}", status_code=resp.status_code) from exc
    if not isinstance(data, dict):
        raise YouTubeDataApiError("Discovery response is not an object", status_code=resp.status_code)
    return data


async def videos_list(
    *,
    client: httpx.AsyncClient,
    api_key: str,
    video_id: str,
) -> dict[str, Any]:
    params = {
        "part": "snippet,statistics,contentDetails,status",
        "id": video_id,
        "key": api_key,
    }
    resp = await client.get(f"{YOUTUBE_V3_BASE}/videos", params=params)
    return _parse_json_response(resp, context="videos.list")


async def comment_threads_list_page(
    *,
    client: httpx.AsyncClient,
    api_key: str,
    video_id: str,
    page_token: str | None,
    max_results: int = 100,
) -> dict[str, Any]:
    params: dict[str, str | int] = {
        "part": "snippet,replies",
        "videoId": video_id,
        "key": api_key,
        "maxResults": min(100, max(1, max_results)),
        "textFormat": "plainText",
    }
    if page_token:
        params["pageToken"] = page_token
    resp = await client.get(f"{YOUTUBE_V3_BASE}/commentThreads", params=params)
    return _parse_json_response(resp, context="commentThreads.list")


def _parse_json_response(resp: httpx.Response, *, context: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except Exception as exc:
        raise YouTubeDataApiError(
            f"{context}: invalid JSON (HTTP {resp.status_code})",
            status_code=resp.status_code,
        ) from exc
    if not isinstance(body, dict):
        raise YouTubeDataApiError(f"{context}: expected object", status_code=resp.status_code)
    if resp.status_code != 200:
        err = body.get("error")
        detail: str | None = None
        if isinstance(err, dict):
            errs = err.get("errors")
            if isinstance(errs, list) and errs:
                first = errs[0]
                if isinstance(first, dict) and first.get("reason"):
                    detail = str(first.get("reason"))
            if detail is None and err.get("message"):
                detail = str(err["message"])
        msg = f"{context}: HTTP {resp.status_code}" + (f" — {detail}" if detail else "")
        log.warning("youtube_data_api_error", extra={"context": context, "status": resp.status_code, "detail": detail})
        raise YouTubeDataApiError(msg, status_code=resp.status_code, api_detail=detail)
    return body
