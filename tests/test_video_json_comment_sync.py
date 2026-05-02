"""Tests for patching ``video.json`` after comments scrape."""

from __future__ import annotations

import json
from pathlib import Path

from youtube_scrape.application.video_json_comment_sync import sync_comment_count_in_video_json
from youtube_scrape.domain.models import ResultEnvelope


def test_sync_comment_count_updates_video_json_metadata(tmp_path: Path) -> None:
    sub = tmp_path / "vid"
    sub.mkdir()
    video_payload = {
        "schema_version": "1",
        "kind": "video",
        "data": {
            "metadata": {
                "video_id": "abc123xyz01",
                "title": "T",
                "comment_count": 100,
            }
        },
    }
    (sub / "video.json").write_text(json.dumps(video_payload), encoding="utf-8")

    env = ResultEnvelope(
        schema_version="1",
        kind="comments",
        data={
            "video_id": "abc123xyz01",
            "comments": [],
            "total_count": 1029,
            "top_level_count": 500,
        },
    )
    sync_comment_count_in_video_json(sub, env)

    root = json.loads((sub / "video.json").read_text(encoding="utf-8"))
    assert root["data"]["metadata"]["comment_count"] == 1029
