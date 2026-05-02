"""Build scrape envelopes via YouTube Data API v3 (optional browser-free path)."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from youtube_scrape.adapters.youtube_data_api import (
    YouTubeDataApiError,
    comment_threads_list_page,
    videos_list,
)
from youtube_scrape.application.envelope import make_envelope
from youtube_scrape.application.scrape_comments import organize_comments_hierarchical
from youtube_scrape.domain.models import CommentRecord, ResultEnvelope, ThumbnailRef, VideoMetadata
from youtube_scrape.domain.return_youtube_dislike_fetch import fetch_ryd_vote_counts
from youtube_scrape.domain.youtube_url import parse_video_id
from youtube_scrape.settings import Settings

log = logging.getLogger(__name__)

_ISO_DURATION_RE = re.compile(
    r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?$",
    re.IGNORECASE,
)


def parse_youtube_content_duration(iso: str | None) -> int | None:
    """Parse ISO8601 duration from videos.contentDetails.duration (e.g. PT1H2M3S)."""
    if not iso or not isinstance(iso, str):
        return None
    m = _ISO_DURATION_RE.match(iso.strip())
    if not m:
        return None
    h = int(m.group("h") or 0)
    mi = int(m.group("m") or 0)
    s = int(m.group("s") or 0)
    return h * 3600 + mi * 60 + s


async def maybe_enrich_metadata_from_ryd(meta: VideoMetadata, settings: Settings) -> VideoMetadata:
    if not settings.fetch_ryd_vote_counts:
        return meta
    need_dislike = meta.dislike_count is None
    need_like = meta.like_count is None
    if not need_dislike and not need_like:
        return meta
    ryd_likes, ryd_dislikes = await fetch_ryd_vote_counts(
        meta.video_id,
        base_url=settings.ryd_api_base_url,
        timeout_s=settings.ryd_timeout_s,
    )
    updates: dict[str, Any] = {}
    if need_dislike and ryd_dislikes is not None:
        updates["dislike_count"] = ryd_dislikes
        updates["dislike_source"] = "return_youtube_dislike"
    if need_like and ryd_likes is not None:
        updates["like_count"] = ryd_likes
    if not updates:
        return meta
    return meta.model_copy(update=updates)


def _int_field(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            return int(raw)
        except ValueError:
            return None
    return None


def _dict_section(raw: Any) -> dict[str, Any]:
    """Narrow JSON object sections for mypy-friendly access."""
    return raw if isinstance(raw, dict) else {}


def _metadata_from_videos_item(video_id: str, item: dict[str, Any]) -> VideoMetadata:
    sn = _dict_section(item.get("snippet"))
    st = _dict_section(item.get("statistics"))
    cd = _dict_section(item.get("contentDetails"))
    stat = _dict_section(item.get("status"))

    thumbnails: list[ThumbnailRef] = []
    td = sn.get("thumbnails")
    if isinstance(td, dict):
        for _k, ref in td.items():
            if not isinstance(ref, dict):
                continue
            u = ref.get("url")
            if isinstance(u, str) and u:
                thumbnails.append(
                    ThumbnailRef(
                        url=u,
                        width=_int_field(ref.get("width")),
                        height=_int_field(ref.get("height")),
                    )
                )

    published_at: datetime | None = None
    published_text: str | None = None
    pats = sn.get("publishedAt")
    if isinstance(pats, str):
        published_text = pats
        try:
            if pats.endswith("Z"):
                published_at = datetime.fromisoformat(pats.replace("Z", "+00:00")).astimezone(UTC)
            else:
                published_at = datetime.fromisoformat(pats)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
                else:
                    published_at = published_at.astimezone(UTC)
        except ValueError:
            published_at = None

    tags = sn.get("tags")
    keywords: list[str] = []
    if isinstance(tags, list):
        keywords = [str(t) for t in tags if isinstance(t, str)]

    life_cycle = stat.get("lifeCycleStatus")
    is_live: bool | None = None
    if isinstance(life_cycle, str) and "live" in life_cycle.lower():
        is_live = True

    return VideoMetadata(
        video_id=video_id,
        title=sn.get("title") if isinstance(sn.get("title"), str) else None,
        channel_id=sn.get("channelId") if isinstance(sn.get("channelId"), str) else None,
        channel_title=sn.get("channelTitle") if isinstance(sn.get("channelTitle"), str) else None,
        description=sn.get("description") if isinstance(sn.get("description"), str) else None,
        published_at=published_at,
        published_text=published_text,
        view_count=_int_field(st.get("viewCount")),
        like_count=_int_field(st.get("likeCount")),
        comment_count=_int_field(st.get("commentCount")),
        duration_seconds=parse_youtube_content_duration(
            cd.get("duration") if isinstance(cd.get("duration"), str) else None
        ),
        thumbnails=thumbnails,
        keywords=keywords,
        category=sn.get("categoryId") if isinstance(sn.get("categoryId"), str) else None,
        is_live=is_live,
    )


def _author_channel_id(sn: dict[str, Any]) -> str | None:
    ch = sn.get("authorChannelId")
    if isinstance(ch, dict):
        val = ch.get("value")
        if isinstance(val, str):
            return val
    return None


def _published_from_snippet(sn: dict[str, Any]) -> tuple[datetime | None, str | None]:
    published_text: str | None = None
    published_at: datetime | None = None
    pats = sn.get("publishedAt")
    if isinstance(pats, str):
        published_text = pats
        try:
            if pats.endswith("Z"):
                published_at = datetime.fromisoformat(pats.replace("Z", "+00:00")).astimezone(UTC)
            else:
                published_at = datetime.fromisoformat(pats)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
                else:
                    published_at = published_at.astimezone(UTC)
        except ValueError:
            published_at = None
    return published_at, published_text


def _comment_record_from_api(
    resource: dict[str, Any],
    *,
    is_reply: bool,
    parent_comment_id: str | None,
) -> CommentRecord | None:
    cid = resource.get("id")
    if not isinstance(cid, str) or not cid:
        return None
    sn = _dict_section(resource.get("snippet"))
    text = str(sn.get("textDisplay") or "")
    author = sn.get("authorDisplayName") if isinstance(sn.get("authorDisplayName"), str) else None
    published_at, published_text = _published_from_snippet(sn)
    return CommentRecord(
        comment_id=cid,
        text=text,
        author=author,
        author_channel_id=_author_channel_id(sn),
        published_text=published_text,
        published_at=published_at,
        like_count=_int_field(sn.get("likeCount")),
        is_reply=is_reply,
        parent_comment_id=parent_comment_id,
    )


async def scrape_video_via_data_api(
    *,
    url_or_id: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> ResultEnvelope:
    video_id = parse_video_id(url_or_id)
    key = settings.youtube_data_api_key.strip()
    raw = await videos_list(client=client, api_key=key, video_id=video_id)
    items = raw.get("items")
    if not isinstance(items, list) or len(items) == 0:
        raise YouTubeDataApiError(f"videos.list: no items for video_id={video_id}", status_code=404)
    first = items[0]
    if not isinstance(first, dict):
        raise YouTubeDataApiError("videos.list: invalid item shape", status_code=502)
    meta = _metadata_from_videos_item(video_id, first)
    meta = await maybe_enrich_metadata_from_ryd(meta, settings)
    payload: dict[str, Any] = {
        "metadata": meta.model_dump(mode="json"),
        "caption_tracks": [],
        "stream_formats_preview": [],
        "stream_formats_total": 0,
        "source": "youtube_data_api_v3",
    }
    return make_envelope(settings=settings, kind="video", data=payload)


async def scrape_comments_via_data_api(
    *,
    url_or_id: str,
    settings: Settings,
    client: httpx.AsyncClient,
    max_comments: int | None,
    fetch_all: bool,
    max_replies_per_thread: int | None,
    include_replies: bool,
) -> ResultEnvelope:
    video_id = parse_video_id(url_or_id)
    key = settings.youtube_data_api_key.strip()
    flat: list[CommentRecord] = []
    page_token: str | None = None

    def should_stop() -> bool:
        return len(flat) >= settings.comments_safety_ceiling or (
            max_comments is not None and len(flat) >= max_comments
        )

    while True:
        page = await comment_threads_list_page(
            client=client,
            api_key=key,
            video_id=video_id,
            page_token=page_token,
            max_results=100,
        )
        items = page.get("items")
        if not isinstance(items, list):
            break
        for thread in items:
            if not isinstance(thread, dict):
                continue
            sn_thread = _dict_section(thread.get("snippet"))
            top = sn_thread.get("topLevelComment")
            if not isinstance(top, dict):
                continue
            parent_rec = _comment_record_from_api(top, is_reply=False, parent_comment_id=None)
            if parent_rec is None:
                continue
            flat.append(parent_rec)
            if should_stop():
                break

            if include_replies:
                replies_obj = sn_thread.get("replies")
                reply_list: list[Any] = []
                if isinstance(replies_obj, dict):
                    rc = replies_obj.get("comments")
                    if isinstance(rc, list):
                        reply_list = rc
                capped = reply_list
                if max_replies_per_thread is not None:
                    capped = reply_list[: max(0, max_replies_per_thread)]
                for reply_res in capped:
                    if not isinstance(reply_res, dict):
                        continue
                    rr = _comment_record_from_api(
                        reply_res,
                        is_reply=True,
                        parent_comment_id=parent_rec.comment_id,
                    )
                    if rr is None:
                        continue
                    flat.append(rr)
                    if should_stop():
                        break
            if should_stop():
                break

        if fetch_all and len(flat) >= settings.comments_safety_ceiling:
            log.warning(
                "comments_safety_ceiling_hit",
                extra={"video_id": video_id, "ceiling": settings.comments_safety_ceiling, "source": "data_api"},
            )

        if should_stop():
            break

        next_tok = page.get("nextPageToken")
        if not isinstance(next_tok, str) or not next_tok:
            break
        if fetch_all:
            page_token = next_tok
            continue
        if max_comments is not None and len(flat) < max_comments:
            page_token = next_tok
            continue
        break

    organized = organize_comments_hierarchical(flat)
    top_level_count = sum(1 for c in flat if not c.is_reply)
    data = {
        "video_id": video_id,
        "comments": organized,
        "total_count": len(flat),
        "top_level_count": top_level_count,
        "source": "youtube_data_api_v3",
    }
    return make_envelope(settings=settings, kind="comments", data=data)
