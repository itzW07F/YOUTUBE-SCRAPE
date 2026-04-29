"""Tests for gallery metadata refresh path validation and JSONL history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_scrape.application.gallery_metadata_refresh import (
    append_metadata_history_jsonl,
    resolve_output_dir_for_refresh,
    utc_now_iso_z,
)


def test_resolve_output_dir_accepts_nested_subdir(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    sub = root / "dQw4w9WgXcQ"
    sub.mkdir()
    resolved = resolve_output_dir_for_refresh(str(sub), [root])
    assert resolved == sub.resolve()


def test_resolve_output_dir_rejects_non_directory(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    file_path = root / "not_a_dir"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not a directory"):
        resolve_output_dir_for_refresh(str(file_path), [root])


def test_resolve_output_dir_rejects_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    with pytest.raises(ValueError, match="outside"):
        resolve_output_dir_for_refresh(str(elsewhere), [root])


def test_resolve_output_dir_rejects_root_itself(tmp_path: Path) -> None:
    root = tmp_path / "out"
    root.mkdir()
    with pytest.raises(ValueError, match="root"):
        resolve_output_dir_for_refresh(str(root), [root])


def test_append_metadata_history_jsonl_writes_one_line(tmp_path: Path) -> None:
    sub = tmp_path / "vid"
    sub.mkdir()
    meta = {
        "video_id": "abc",
        "title": "T",
        "channel_title": "C",
        "view_count": 99,
        "like_count": 1,
        "dislike_count": 2,
        "comment_count": 3,
        "published_at": "2024-01-01T00:00:00Z",
    }
    cap = "2026-01-02T03:04:05Z"
    append_metadata_history_jsonl(sub, captured_at_iso_z=cap, video_id="abc", metadata=meta)
    lines = (sub / "metadata_history.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["schema_version"] == "1"
    assert obj["captured_at"] == cap
    assert obj["video_id"] == "abc"
    assert obj["output_dir"] == str(sub)
    assert obj["metrics"]["title"] == "T"
    assert obj["metrics"]["view_count"] == 99


def test_resolve_output_dir_accepts_second_root(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    sub = b / "nested" / "vid"
    sub.mkdir(parents=True)
    resolved = resolve_output_dir_for_refresh(str(sub), [a, b])
    assert resolved == sub.resolve()


def test_resolve_output_dir_fails_if_no_root_matches(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    with pytest.raises(ValueError, match="outside"):
        resolve_output_dir_for_refresh(str(elsewhere), [a])


def test_utc_now_iso_z_ends_with_z() -> None:
    assert utc_now_iso_z().endswith("Z")
