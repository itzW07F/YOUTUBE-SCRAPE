"""Parse ``ytInitialPlayerResponse`` / ``playerResponse`` into domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from youtube_scrape.domain.models import CaptionTrackRef, ThumbnailRef, VideoMetadata
from youtube_scrape.exceptions import ExtractionError


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_thumbnails(video_details: dict[str, Any]) -> list[ThumbnailRef]:
    thumbs: list[ThumbnailRef] = []
    raw = video_details.get("thumbnail") or {}
    for entry in raw.get("thumbnails") or []:
        url = entry.get("url")
        if not url:
            continue
        thumbs.append(
            ThumbnailRef(
                url=url,
                width=_as_int(entry.get("width")),
                height=_as_int(entry.get("height")),
            )
        )
    return thumbs


def _parse_caption_tracks(player: dict[str, Any]) -> list[CaptionTrackRef]:
    caps = player.get("captions", {}).get("playerCaptionsTracklistRenderer", {})
    tracks: list[CaptionTrackRef] = []
    for t in caps.get("captionTracks") or []:
        base = t.get("baseUrl")
        if not base:
            continue
        tracks.append(
            CaptionTrackRef(
                language_code=str(t.get("languageCode") or ""),
                name=t.get("name", {}).get("simpleText") if isinstance(t.get("name"), dict) else None,
                base_url=base,
                kind=t.get("kind"),
            )
        )
    return tracks


def _parse_boolish(value: Any) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _parse_published_at(player: dict[str, Any]) -> datetime | None:
    micro = player.get("microformat", {}).get("playerMicroformatRenderer", {}).get("publishDate")
    if isinstance(micro, str):
        try:
            return datetime.fromisoformat(micro.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None
    return None


def parse_video_metadata(player: dict[str, Any]) -> VideoMetadata:
    """Build :class:`VideoMetadata` from a parsed player response dict."""
    details = player.get("videoDetails")
    if not isinstance(details, dict):
        msg = "videoDetails missing from player response"
        raise ExtractionError(msg, details="video_details_missing")

    video_id = str(details.get("videoId") or "")
    if not video_id:
        msg = "videoId missing from videoDetails"
        raise ExtractionError(msg, details="video_id_missing")

    return VideoMetadata(
        video_id=video_id,
        title=details.get("title"),
        channel_id=details.get("channelId"),
        channel_title=details.get("author"),
        description=details.get("shortDescription"),
        published_at=_parse_published_at(player),
        view_count=_as_int(details.get("viewCount")),
        like_count=_as_int(details.get("likeCount")),
        comment_count=_as_int(details.get("commentCount")),
        duration_seconds=_as_int(details.get("lengthSeconds")),
        thumbnails=_parse_thumbnails(details),
        keywords=list(details.get("keywords") or []) if isinstance(details.get("keywords"), list) else [],
        category=(details.get("category") or None),
        is_live=_parse_boolish(details.get("isLiveContent")),
    )


def parse_caption_tracks(player: dict[str, Any]) -> list[CaptionTrackRef]:
    """Return caption tracks from player response."""
    return _parse_caption_tracks(player)


def parse_stream_formats(player: dict[str, Any]) -> list[dict[str, Any]]:
    """Return raw format dicts from ``streamingData`` (progressive + adaptive)."""
    streaming = player.get("streamingData")
    if not isinstance(streaming, dict):
        return []
    out: list[dict[str, Any]] = []
    for key in ("formats", "adaptiveFormats"):
        for fmt in streaming.get(key) or []:
            if isinstance(fmt, dict):
                out.append(fmt)
    return out


def parse_muxed_progressive_formats(player: dict[str, Any]) -> list[dict[str, Any]]:
    """Return format dicts from ``streamingData.formats`` only (combined A+V progressive rows).

    YouTube puts true progressive muxes here; ``adaptiveFormats`` are separate video/audio
    DASH representations and must not be fed to ``select_best_progressive_format`` when the goal
    is a single playable file from one URL.
    """
    streaming = player.get("streamingData")
    if not isinstance(streaming, dict):
        return []
    out: list[dict[str, Any]] = []
    for fmt in streaming.get("formats") or []:
        if isinstance(fmt, dict):
            out.append(fmt)
    return out
