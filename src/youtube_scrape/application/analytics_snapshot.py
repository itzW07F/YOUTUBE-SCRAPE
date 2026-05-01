"""Build deterministic :class:`AnalyticsSnapshot` from validated scrape output directories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from youtube_scrape.adapters.analytics_artifacts import (
    envelope_inner_data,
    read_json_file,
    read_metadata_history_jsonl,
)
from youtube_scrape.domain.analytics_aggregate import (
    build_comment_stats,
    extract_keywords,
    flatten_comment_nodes,
)
from youtube_scrape.domain.analytics_models import (
    AnalyticsSnapshot,
    KeywordTerm,
    MetadataHistoryPoint,
    VideoMetricsSummary,
)


def _meta_int(meta: dict[str, Any], *keys: str) -> int | None:
    for k in keys:
        if k not in meta:
            continue
        v = meta[k]
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, str) and v.strip():
            try:
                return int(float(v.replace(",", "").replace("_", "").strip()))
            except ValueError:
                continue
    return None


def _meta_str(meta: dict[str, Any], *keys: str) -> str | None:
    for k in keys:
        if k not in meta:
            continue
        v = meta[k]
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def video_metrics_from_metadata(meta: dict[str, Any]) -> VideoMetricsSummary:
    return VideoMetricsSummary(
        video_id=_meta_str(meta, "video_id"),
        title=_meta_str(meta, "title"),
        channel_title=_meta_str(meta, "channel_title"),
        published_at=_meta_str(meta, "published_at"),
        view_count=_meta_int(meta, "view_count"),
        like_count=_meta_int(meta, "like_count"),
        dislike_count=_meta_int(meta, "dislike_count"),
        comment_count=_meta_int(meta, "comment_count"),
        duration_seconds=_meta_int(meta, "duration_seconds"),
    )


def history_points_from_jsonl(rows: list[dict[str, Any]]) -> list[MetadataHistoryPoint]:
    out: list[MetadataHistoryPoint] = []
    for row in rows:
        cap = row.get("captured_at")
        if not isinstance(cap, str) or not cap.strip():
            continue
        metrics = row.get("metrics")
        m: dict[str, Any] = metrics if isinstance(metrics, dict) else {}
        vid = row.get("video_id")
        out.append(
            MetadataHistoryPoint(
                captured_at=cap.strip(),
                video_id=str(vid) if vid is not None else _meta_str(m, "video_id"),
                view_count=_meta_int(m, "view_count"),
                like_count=_meta_int(m, "like_count"),
                dislike_count=_meta_int(m, "dislike_count"),
                comment_count=_meta_int(m, "comment_count"),
            )
        )
    return out


def build_analytics_snapshot(output_dir: Path) -> AnalyticsSnapshot:
    """Load artifacts from ``output_dir`` (already validated under output roots)."""

    notes: list[str] = []
    vpath = output_dir / "video.json"
    cpath = output_dir / "comments.json"
    hist_path = output_dir / "metadata_history.jsonl"

    video_metrics: VideoMetricsSummary | None = None
    env = read_json_file(vpath)
    if env is None:
        notes.append("video.json missing or unreadable — performance snapshot limited.")
    else:
        inner = envelope_inner_data(env)
        meta = inner.get("metadata")
        if isinstance(meta, dict):
            video_metrics = video_metrics_from_metadata(meta)
        else:
            notes.append("video.json has no metadata object.")

    hist_raw = read_metadata_history_jsonl(hist_path)
    metadata_history = history_points_from_jsonl(hist_raw)
    if not metadata_history:
        notes.append("No metadata_history.jsonl — refresh metadata from the gallery to build trend lines.")
    elif len(metadata_history) < 2:
        notes.append("Only one metadata history point — trends need at least two refreshes.")

    comments_present = cpath.is_file()
    comment_stats = None
    keywords: list[KeywordTerm] = []

    if comments_present:
        cenv = read_json_file(cpath)
        if cenv is None:
            notes.append("comments.json unreadable.")
        else:
            data = envelope_inner_data(cenv)
            raw_comments = data.get("comments")
            if not isinstance(raw_comments, list):
                notes.append("comments.json has no comments list.")
            else:
                flat = flatten_comment_nodes(raw_comments)
                top_level_count = data.get("top_level_count")
                tl = int(top_level_count) if isinstance(top_level_count, int) else None
                comment_stats = build_comment_stats(flat, top_level_count=tl)
                keywords = extract_keywords(flat)

    return AnalyticsSnapshot(
        output_dir=str(output_dir),
        video_metrics=video_metrics,
        metadata_history=metadata_history,
        metadata_history_points=len(metadata_history),
        comments_file_present=comments_present,
        comment_stats=comment_stats,
        keywords=keywords,
        notes=notes,
    )
