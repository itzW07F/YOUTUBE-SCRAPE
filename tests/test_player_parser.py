import json
from pathlib import Path

from youtube_scrape.domain.player_parser import (
    parse_caption_tracks,
    parse_muxed_progressive_formats,
    parse_stream_formats,
    parse_video_metadata,
)


def test_parse_video_metadata_from_fixture() -> None:
    raw = Path(__file__).parent / "fixtures" / "player_response_min.json"
    player = json.loads(raw.read_text(encoding="utf-8"))
    meta = parse_video_metadata(player)
    assert meta.video_id == "dQw4w9WgXcQ"
    assert meta.title == "Sample"
    assert meta.view_count == 1234567
    assert meta.is_live is False
    assert meta.published_at is not None


def test_caption_tracks() -> None:
    raw = Path(__file__).parent / "fixtures" / "player_response_min.json"
    player = json.loads(raw.read_text(encoding="utf-8"))
    tracks = parse_caption_tracks(player)
    assert len(tracks) == 1
    assert tracks[0].language_code == "en"


def test_stream_formats_counts() -> None:
    raw = Path(__file__).parent / "fixtures" / "player_response_min.json"
    player = json.loads(raw.read_text(encoding="utf-8"))
    fmts = parse_stream_formats(player)
    assert len(fmts) == 2


def test_muxed_progressive_formats_only_formats_key() -> None:
    raw = Path(__file__).parent / "fixtures" / "player_response_min.json"
    player = json.loads(raw.read_text(encoding="utf-8"))
    muxed = parse_muxed_progressive_formats(player)
    assert len(muxed) == 1
    assert muxed[0].get("itag") == 18
