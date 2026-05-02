"""Keep ``video.json`` comment totals in sync after an in-place comments scrape."""

from __future__ import annotations

import json
from pathlib import Path

from youtube_scrape.adapters.analytics_artifacts import envelope_inner_data, read_json_file
from youtube_scrape.domain.models import ResultEnvelope


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
