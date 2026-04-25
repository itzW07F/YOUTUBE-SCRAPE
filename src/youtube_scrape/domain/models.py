"""Normalized output models (schema versioned at envelope level)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ThumbnailRef(BaseModel):
    url: str
    width: int | None = None
    height: int | None = None


class VideoMetadata(BaseModel):
    video_id: str
    title: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    view_count: int | None = None
    like_count: int | None = None
    duration_seconds: int | None = None
    thumbnails: list[ThumbnailRef] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    category: str | None = None
    is_live: bool | None = None


class CaptionTrackRef(BaseModel):
    language_code: str
    name: str | None = None
    base_url: str
    kind: str | None = None


class CommentRecord(BaseModel):
    comment_id: str
    text: str
    author: str | None = None
    author_channel_id: str | None = None
    published_text: str | None = None
    like_count: int | None = None
    is_reply: bool = False
    parent_comment_id: str | None = None


class StreamFormatRef(BaseModel):
    itag: int
    mime_type: str | None = None
    quality_label: str | None = None
    has_audio: bool | None = None
    has_video: bool | None = None
    url: str | None = None
    content_length: int | None = None


class ResultEnvelope(BaseModel):
    schema_version: str
    kind: Literal["video", "comments", "transcript", "download", "thumbnails"]
    data: dict[str, Any]
