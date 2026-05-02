"""Build deterministic :class:`AnalyticsSnapshot` from validated scrape output directories."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from youtube_scrape.adapters.analytics_artifacts import (
    envelope_inner_data,
    read_json_file,
    read_metadata_history_jsonl,
)
from youtube_scrape.application.comment_snapshot_archive import COMMENT_SNAPSHOTS_SUBDIR
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
        description=_meta_str(meta, "description", "short_description"),
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


def _captured_at_epoch_seconds(captured_at: str) -> float | None:
    raw = captured_at.strip()
    if not raw:
        return None
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return None


def sort_metadata_history_chronologically(points: list[MetadataHistoryPoint]) -> list[MetadataHistoryPoint]:
    """Sort by ``captured_at`` ascending so trend charts match real time order.

    ``metadata_history.jsonl`` is usually append-only, but merged or hand-edited files may be
    out of order; analytics must still plot chronologically.
    """
    if len(points) <= 1:
        return points
    indexed = list(enumerate(points))

    def sort_key(it: tuple[int, MetadataHistoryPoint]) -> tuple[float, int]:
        i, p = it
        epoch = _captured_at_epoch_seconds(p.captured_at)
        if epoch is None:
            return (float("inf"), i)
        return (epoch, i)

    indexed.sort(key=sort_key)
    return [p for _, p in indexed]


def backfill_video_metrics_comment_count_from_history(
    video_metrics: VideoMetricsSummary | None,
    metadata_history: list[MetadataHistoryPoint],
    notes: list[str],
) -> VideoMetricsSummary | None:
    """When ``video.json`` omits ``comment_count`` (common after some metadata refreshes), use history.

    The watch pipeline often still records the public total in ``metadata_history.jsonl`` rows; analytics
    should not show a blank YouTube comment total when the trend series has values.
    """
    if video_metrics is None or video_metrics.comment_count is not None:
        return video_metrics
    for p in reversed(metadata_history):
        if p.comment_count is not None:
            notes.append(
                "YouTube public comment total was missing from video.json; filled from the latest "
                "metadata_history.jsonl capture that includes it."
            )
            return video_metrics.model_copy(update={"comment_count": p.comment_count})
    return video_metrics


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
    metadata_history = sort_metadata_history_chronologically(history_points_from_jsonl(hist_raw))
    if not metadata_history:
        notes.append("No metadata_history.jsonl — refresh metadata from the gallery to build trend lines.")
    elif len(metadata_history) < 2:
        notes.append("Only one metadata history point — trends need at least two refreshes.")

    comments_present = cpath.is_file()
    snap_dir = output_dir / COMMENT_SNAPSHOTS_SUBDIR
    if snap_dir.is_dir() and any(snap_dir.glob("comments_*.json")):
        notes.append(
            f"Older comment pulls are preserved under {COMMENT_SNAPSHOTS_SUBDIR}/; comments.json is the latest scrape."
        )

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

    video_metrics = backfill_video_metrics_comment_count_from_history(
        video_metrics, metadata_history, notes
    )

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
