"""Archive ``comments.json`` before a refresh so prior scrapes remain on disk."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

COMMENT_SNAPSHOTS_SUBDIR = "comment_snapshots"


def archive_existing_comments_json(output_dir: Path) -> Path | None:
    """If ``comments.json`` exists, copy it into ``comment_snapshots/``.

    Returns the destination path, or ``None`` when there was no file to archive.
    """
    src = output_dir / "comments.json"
    if not src.is_file():
        return None
    dest_dir = output_dir / COMMENT_SNAPSHOTS_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    dest = dest_dir / f"comments_{stamp}.json"
    shutil.copy2(src, dest)
    return dest
