"""Unit tests for playback capture scoring (no browser)."""

from youtube_scrape.adapters.browser_playwright import _playback_capture_rank


def test_rank_prefers_isobmff_ftyp_over_larger_webm_head() -> None:
    webm_url = "https://r1---sn.example.googlevideo.com/videoplayback?mime=video%2Fwebm"
    mp4_url = "https://r1---sn.example.googlevideo.com/videoplayback?mime=video%2Fmp4"
    webm_body = b"\x1a\x45\xdf\xa3" + b"\x00" * 200_000
    mp4_body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 50_000
    assert _playback_capture_rank(
        mp4_url,
        mp4_body,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=1,
    ) > _playback_capture_rank(
        webm_url,
        webm_body,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=1,
    )


def test_rank_prefers_matching_itag_over_larger_other() -> None:
    match_url = "https://r1---sn.example.googlevideo.com/videoplayback?itag=18&mime=video%2Fmp4"
    other_url = "https://r1---sn.example.googlevideo.com/videoplayback?itag=22&mime=video%2Fmp4"
    match_body = b"\x00\x00\x00\x18ftypmp42" + b"x" * 12_000
    other_body = b"\x00\x00\x00\x18ftypmp42" + b"y" * 80_000
    assert _playback_capture_rank(
        match_url,
        match_body,
        18,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=1,
    ) > _playback_capture_rank(
        other_url,
        other_body,
        18,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=1,
    )


def test_rank_prefers_mp42_over_dash_ftyp_at_same_size() -> None:
    url = "https://r1---sn.example.googlevideo.com/videoplayback?mime=video%2Fmp4"
    dash_body = b"\x00\x00\x00\x18ftypdash" + b"\x00" * 50_000
    prog_body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 50_000
    assert _playback_capture_rank(
        url,
        prog_body,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=0,
    ) > _playback_capture_rank(
        url,
        dash_body,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=0,
    )


def test_rank_prefers_playwright_media_resource_type() -> None:
    url = "https://r1---sn.example.googlevideo.com/videoplayback?mime=video%2Fmp4"
    body = b"\x00\x00\x00\x18ftypmp42" + b"z" * 20_000
    assert _playback_capture_rank(
        url,
        body,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=1,
    ) > _playback_capture_rank(
        url,
        body,
        None,
        starts_at_file_origin=1,
        not_xhr_like=1,
        content_type_is_video=2,
        media_resource_type=0,
    )
