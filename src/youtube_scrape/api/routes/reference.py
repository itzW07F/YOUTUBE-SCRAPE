"""Public reference / documentation helpers (e.g. YouTube Data API discovery JSON)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from youtube_scrape.adapters.youtube_data_api import YouTubeDataApiError, fetch_discovery_document

router = APIRouter()


class YouTubeDiscoveryResponse(BaseModel):
    """Subset of Google's discovery document plus fetch metadata."""

    title: str | None = None
    id: str | None = None
    version: str | None = None
    revision: str | None = None
    discovery_url: str = Field(default="https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest")
    fetched_at: str = Field(..., description="ISO8601 UTC when this server retrieved the discovery document.")
    http_status: int = 200


@router.get("/youtube-data-api/discovery", response_model=YouTubeDiscoveryResponse)
async def youtube_data_api_discovery() -> YouTubeDiscoveryResponse:
    """Fetch the live YouTube Data API v3 discovery JSON from Google (for docs freshness / connectivity)."""
    fetched_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            doc = await fetch_discovery_document(client=client)
        except YouTubeDataApiError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": str(exc),
                    "status_code": exc.status_code,
                    "api_detail": exc.api_detail,
                    "fetched_at": fetched_at,
                },
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail={"message": f"Discovery request failed: {exc}", "fetched_at": fetched_at},
            ) from exc

    title = doc.get("title") if isinstance(doc.get("title"), str) else None
    id_ = doc.get("id") if isinstance(doc.get("id"), str) else None
    version = doc.get("version") if isinstance(doc.get("version"), str) else None
    revision = doc.get("revision") if isinstance(doc.get("revision"), str) else None
    return YouTubeDiscoveryResponse(
        title=title,
        id=id_,
        version=version,
        revision=revision,
        fetched_at=fetched_at,
        http_status=200,
    )
