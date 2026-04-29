"""Gallery metadata refresh: path validation and history append (JSONL)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_REFRESH_BATCH_ITEMS = 20

_METRICS_KEYS = (
    "video_id",
    "title",
    "channel_title",
    "published_at",
    "published_text",
    "view_count",
    "like_count",
    "dislike_count",
    "comment_count",
    "duration_seconds",
    "category",
    "is_live",
)


def output_roots_from_env() -> list[Path]:
    """Paths allowed for gallery/metadata refresh (matches GUI ``getAllowedOutputRoots``)."""
    multi = os.environ.get("YOUTUBE_SCRAPE_OUTPUT_ROOTS", "").strip()
    if multi:
        return [Path(p).expanduser().resolve() for p in multi.split(os.pathsep) if p.strip()]
    return [Path(os.environ.get("OUTPUT_DIR", "output")).resolve()]


def resolve_output_dir_for_refresh(output_dir: str, output_roots: Sequence[Path]) -> Path:
    """Resolve ``output_dir`` if it is a strict subdirectory of one of ``output_roots``."""
    target = Path(output_dir).expanduser().resolve()
    if not target.is_dir():
        raise ValueError("Output path is not a directory")
    for root in output_roots:
        r = root.resolve()
        try:
            target.relative_to(r)
        except ValueError:
            continue
        if target == r:
            raise ValueError("Cannot refresh metadata for the output root itself")
        return target
    raise ValueError("Output directory is outside the configured output root(s)")


def utc_now_iso_z() -> str:
    """UTC timestamp with ``Z`` suffix for history lines."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def append_metadata_history_jsonl(
    out_dir: Path,
    *,
    captured_at_iso_z: str,
    video_id: str,
    metadata: Mapping[str, Any],
) -> None:
    """Append one JSON object per line to ``metadata_history.jsonl`` under ``out_dir``."""
    metrics = {k: metadata.get(k) for k in _METRICS_KEYS}
    line: dict[str, Any] = {
        "schema_version": "1",
        "captured_at": captured_at_iso_z,
        "video_id": video_id,
        "output_dir": str(out_dir),
        "metrics": metrics,
    }
    hist = out_dir / "metadata_history.jsonl"
    with hist.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
