"""Resolve scrape job output directory (default tree vs in-place GUI folder)."""

from __future__ import annotations

import os
from pathlib import Path

from youtube_scrape.adapters.analytics_artifacts import envelope_inner_data, read_json_file
from youtube_scrape.application.gallery_metadata_refresh import output_roots_from_env, resolve_output_dir_for_refresh
from youtube_scrape.domain.youtube_url import parse_video_id


def default_output_path_for_video_id(video_id: str) -> Path:
    root = Path(os.environ.get("OUTPUT_DIR", "output")).resolve()
    return root / video_id


def video_id_from_scrape_folder(path: Path) -> str | None:
    env = read_json_file(path / "video.json")
    if env is None:
        return None
    inner = envelope_inner_data(env)
    meta = inner.get("metadata")
    if not isinstance(meta, dict):
        return None
    vid = meta.get("video_id")
    if vid is None:
        vid = meta.get("videoId")
    if vid is None:
        return None
    s = str(vid).strip()
    return s or None


def resolve_scrape_job_output_path(*, watch_url: str, output_dir_hint: str | None) -> Path:
    """Return the folder to write scrape artifacts into.

    Raises ``ValueError`` with an API-safe message when ``output_dir_hint`` is invalid
    or does not match the video id from ``watch_url``.
    """
    video_id = parse_video_id(watch_url)
    raw = (output_dir_hint or "").strip() if output_dir_hint else ""
    if not raw:
        return default_output_path_for_video_id(video_id)
    try:
        path = resolve_output_dir_for_refresh(raw, output_roots_from_env())
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not (path / "video.json").is_file():
        raise ValueError(
            "When output_dir is set, the folder must contain video.json (an existing scrape output)."
        )
    folder_vid = video_id_from_scrape_folder(path)
    if not folder_vid:
        raise ValueError(
            "video.json in output_dir is missing metadata.video_id — cannot verify the folder matches the URL."
        )
    if folder_vid != video_id:
        raise ValueError(f"output_dir is for video {folder_vid} but the URL is for {video_id}.")
    return path
