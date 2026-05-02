"""Scrape job output path: default OUTPUT_DIR/<id> vs GUI-targeted existing folder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from youtube_scrape.application.scrape_job_output_path import (
    default_output_path_for_video_id,
    resolve_scrape_job_output_path,
)


def test_default_output_dir_uses_output_root_and_video_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    out = resolve_scrape_job_output_path(
        watch_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        output_dir_hint=None,
    )
    assert out == default_output_path_for_video_id("dQw4w9WgXcQ")
    assert out.parent == tmp_path.resolve()


def test_explicit_output_dir_requires_matching_video_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    nest = tmp_path / "channel" / "my_vid_folder"
    nest.mkdir(parents=True)
    vid = "dQw4w9WgXcQ"
    envelope = {"data": {"metadata": {"video_id": vid, "title": "T"}}}
    (nest / "video.json").write_text(json.dumps(envelope), encoding="utf-8")
    out = resolve_scrape_job_output_path(
        watch_url=f"https://www.youtube.com/watch?v={vid}",
        output_dir_hint=str(nest),
    )
    assert out.resolve() == nest.resolve()


def test_explicit_output_dir_rejects_wrong_video(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    nest = tmp_path / "x"
    nest.mkdir()
    envelope = {"data": {"metadata": {"video_id": "aaaaaaaaaaa", "title": "T"}}}
    (nest / "video.json").write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="output_dir is for"):
        resolve_scrape_job_output_path(
            watch_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir_hint=str(nest),
        )
