"""Refresh video metadata into existing scrape folders (gallery / analytics history)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from youtube_scrape.application.gallery_metadata_refresh import MAX_REFRESH_BATCH_ITEMS, output_roots_from_env
from youtube_scrape.application.metadata_refresh_iterate import iterate_metadata_refresh

router = APIRouter()


class RefreshMetadataItem(BaseModel):
    """One gallery row to refresh."""

    output_dir: str = Field(..., description="Absolute path to scrape output folder")
    url: str = Field(..., description="Watch URL for the video")


class RefreshMetadataBatchRequest(BaseModel):
    items: list[RefreshMetadataItem] = Field(
        ...,
        min_length=1,
        max_length=MAX_REFRESH_BATCH_ITEMS,
    )


class RefreshMetadataBatchResultItem(BaseModel):
    output_dir: str
    ok: bool
    error: str | None = None


class RefreshMetadataBatchResponse(BaseModel):
    results: list[RefreshMetadataBatchResultItem]
    output_roots: list[str]


async def _batch_results_from_iterate(
    pairs: list[tuple[str, str]],
) -> tuple[list[RefreshMetadataBatchResultItem], list[str]]:
    aggregated: list[RefreshMetadataBatchResultItem] = []
    async for _, outcome in iterate_metadata_refresh(pairs):
        aggregated.append(
            RefreshMetadataBatchResultItem(
                output_dir=outcome.output_dir,
                ok=outcome.ok,
                error=outcome.error,
            )
        )
    roots_str = [str(r) for r in output_roots_from_env()]
    return aggregated, roots_str


@router.post("/refresh-batch", response_model=RefreshMetadataBatchResponse)
async def refresh_metadata_batch(body: RefreshMetadataBatchRequest) -> RefreshMetadataBatchResponse:
    """Re-scrape video metadata into each folder; write ``video.json`` and append ``metadata_history.jsonl``."""
    pairs = [(item.output_dir, item.url) for item in body.items]
    results, roots_str = await _batch_results_from_iterate(pairs)
    return RefreshMetadataBatchResponse(results=results, output_roots=roots_str)


@router.post("/refresh-batch-stream")
async def refresh_metadata_batch_stream(body: RefreshMetadataBatchRequest) -> StreamingResponse:
    """NDJSON stream: ``start``, one ``item`` line per folder, final ``done`` with full aggregate payload."""

    roots = output_roots_from_env()
    roots_str = [str(r) for r in roots]
    pairs = [(item.output_dir, item.url) for item in body.items]
    n = len(pairs)

    async def ndjson_chunks() -> AsyncIterator[bytes]:
        yield (
            json.dumps({"type": "start", "total": n, "output_roots": roots_str}, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        aggregated: list[RefreshMetadataBatchResultItem] = []
        async for index, outcome in iterate_metadata_refresh(pairs):
            item = RefreshMetadataBatchResultItem(
                output_dir=outcome.output_dir,
                ok=outcome.ok,
                error=outcome.error,
            )
            aggregated.append(item)
            evt = {
                "type": "item",
                "index": index,
                "total": n,
                "output_dir": outcome.output_dir,
                "ok": outcome.ok,
                "error": outcome.error,
            }
            yield json.dumps(evt, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
        envelope = RefreshMetadataBatchResponse(results=aggregated, output_roots=roots_str)
        yield (
            json.dumps({"type": "done", **envelope.model_dump()}, ensure_ascii=False, default=str).encode(
                "utf-8"
            )
            + b"\n"
        )

    return StreamingResponse(
        ndjson_chunks(),
        media_type="application/x-ndjson",
    )

