"""Keep ``video.json`` comment totals aligned with scraped comment envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from youtube_scrape.adapters.analytics_artifacts import envelope_inner_data, read_json_file
from youtube_scrape.domain.models import ResultEnvelope


def total_count_from_comments_json(output_dir: Path) -> int | None:
    """Return ``data.total_count`` from ``comments.json`` when present and non-negative."""
    path = output_dir / "comments.json"
    root = read_json_file(path)
    if root is None:
        return None
    data = envelope_inner_data(root)
    total = data.get("total_count")
    if not isinstance(total, int) or total < 0:
        return None
    return total


def _metadata_has_usable_comment_count(metadata: dict[str, Any]) -> bool:
    v = metadata.get("comment_count")
    if v is None or isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v >= 0
    if isinstance(v, float) and v.is_integer():
        return int(v) >= 0
    if isinstance(v, str) and v.strip():
        try:
            int(float(v.replace(",", "").replace("_", "").strip()))
            return True
        except ValueError:
            return False
    return False


def metadata_with_comment_count_from_scraped_comments(
    output_dir: Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Fill ``comment_count`` from ``comments.json`` when the watch scrape omitted it.

    Metadata refresh uses a light watch extract (no comment-section DOM hydration), so public totals
    are often missing from the player payload. The scraped corpus total matches what
    :func:`sync_comment_count_in_video_json` already writes after comment runs; applying the same
    fallback here keeps ``metadata_history.jsonl`` sparklines consistent with ``video.json``.
    """
    if _metadata_has_usable_comment_count(metadata):
        return metadata
    total = total_count_from_comments_json(output_dir)
    if total is None:
        return metadata
    out = dict(metadata)
    out["comment_count"] = total
    return out


def sync_comment_count_in_video_json(output_dir: Path, comments_envelope: ResultEnvelope) -> None:
    """Write ``data.metadata.comment_count`` in ``video.json`` to match comments ``data.total_count``.

    Called after ``comments.json`` is saved so analytics and the snapshot UI reflect the same corpus
    count as the scrape (until the next metadata refresh from YouTube).
    """
    data = comments_envelope.data
    if not isinstance(data, dict):
        return
    total = data.get("total_count")
    if not isinstance(total, int) or total < 0:
        return
    path = output_dir / "video.json"
    root = read_json_file(path)
    if root is None:
        return
    inner = envelope_inner_data(root)
    meta = inner.get("metadata")
    if not isinstance(meta, dict):
        return
    meta["comment_count"] = total
    path.write_text(json.dumps(root, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
