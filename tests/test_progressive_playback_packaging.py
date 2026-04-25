"""ISO BMFF heuristics for capture ranking and download metadata."""

from youtube_scrape.adapters.browser_playwright import (
    _bytes_ok_for_progressive_playback,
    _guess_mp4_codec_hint,
    _iso_bmff_moof_before_mdat,
    _playback_capture_rank,
)


def test_moof_before_mdat_detects_fragment_layout() -> None:
    dashish = (
        b"\x00\x00\x00\x18ftypmp42"
        + b"\x00" * 100
        + b"\x00\x00\x00\x10moof"
        + b"\x00" * 20
        + b"\x00\x00\x00\x08mdat"
        + b"mdatxxxx"
    )
    assert _iso_bmff_moof_before_mdat(dashish)
    prog = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200 + b"\x00\x00\x00\x10mdat" + b"mdatxxxx"
    assert not _iso_bmff_moof_before_mdat(prog)


def test_bytes_ok_requires_unwrapped_ftyp() -> None:
    assert not _bytes_ok_for_progressive_playback(b"hello")
    assert _bytes_ok_for_progressive_playback(b"\x00\x00\x00\x1cftypdash" + b"\x00" * 20)
    assert _bytes_ok_for_progressive_playback(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200 + b"mdat" + b"\x00" * 8000)


def test_guess_codec_hint() -> None:
    blob = b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 40 + b"av01" + b"\x00" * 100
    assert _guess_mp4_codec_hint(blob) == "av01"
    h264 = b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 40 + b"avc1" + b"\x00" * 100
    assert _guess_mp4_codec_hint(h264) == "avc1"


def test_rank_prefers_no_moof_before_mdat() -> None:
    url = "https://r1---sn.example.googlevideo.com/videoplayback?mime=video%2Fmp4"
    good = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 300 + b"mdat" + b"\x00" * 80_000
    bad = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 80 + b"moof" + b"\x00" * 40 + b"mdat" + b"\x00" * 80_000
    assert _playback_capture_rank(
        url,
        good,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=0,
    ) > _playback_capture_rank(
        url,
        bad,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=0,
    )
