"""Tests for comment snapshot archiving before refresh."""

from __future__ import annotations

from pathlib import Path

from youtube_scrape.application.comment_snapshot_archive import (
    COMMENT_SNAPSHOTS_SUBDIR,
    archive_existing_comments_json,
)


def test_archive_existing_comments_json_copies_into_subdir(tmp_path: Path) -> None:
    out = tmp_path / "abc123"
    out.mkdir()
    src = out / "comments.json"
    src.write_text('{"hello": 1}', encoding="utf-8")

    dest = archive_existing_comments_json(out)

    assert dest is not None
    assert dest.is_file()
    assert dest.parent == out / COMMENT_SNAPSHOTS_SUBDIR
    assert dest.name.startswith("comments_") and dest.name.endswith(".json")
    assert dest.read_text(encoding="utf-8") == '{"hello": 1}'
    assert src.read_text(encoding="utf-8") == '{"hello": 1}'


def test_archive_existing_comments_json_returns_none_when_missing(tmp_path: Path) -> None:
    out = tmp_path / "nodata"
    out.mkdir()
    assert archive_existing_comments_json(out) is None
