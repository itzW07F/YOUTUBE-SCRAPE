"""DASH init detection, URL itag, and download merge."""

from __future__ import annotations

from typing import Any

from youtube_scrape.adapters.browser_playwright import (
    MediaRouteSnifferState,
    _iso_bmff_moof_before_mdat,
)
from youtube_scrape.application.download_media import _maybe_prepend_dash_init
from youtube_scrape.domain.dash_init import is_dash_init_fmp4, itag_from_videoplayback_url


def _sniff(
    dash_init_by_itag: dict[int, bytes] | None = None,
    prefer_itag: int | None = None,
) -> Any:
    s = MediaRouteSnifferState()
    if dash_init_by_itag is not None:
        s.dash_init_by_itag = dict(dash_init_by_itag)
    s.prefer_itag = prefer_itag
    return s


def test_itag_from_videoplayback_url() -> None:
    u = "https://r1---sn.example.com/videoplayback?itag=136&clen=123&mime=video%2Fmp4"
    assert itag_from_videoplayback_url(u) == 136
    uenc = (
        "https://r1---sn.example.com/videoplayback?expire=1"
        "&mime=video%2Fmp4&itag%3D399&clen=99"
    )
    assert itag_from_videoplayback_url(uenc) == 399


def test_is_dash_init_fmp4_positive() -> None:
    init = (
        b"\x00\x00\x00\x1c" + b"ftyp" + b"isom" + b"\x00" * 12
        + b"\x00\x00\x00\x20" + b"moov" + b"\x00" * 0x1C
    )
    assert is_dash_init_fmp4(init)


def test_is_dash_init_fmp4_rejects_fragment() -> None:
    frag = b"\x00\x00\x00\x18" + b"ftyp" + b"isom" + b"\x00" * 4 + b"\x00\x00\x00\x10moof" + b"\x00" * 8
    assert not is_dash_init_fmp4(frag)


def test_is_dash_init_fmp4_rejects_progressive_mdat() -> None:
    ftyp = b"\x00\x00\x00\x1c" + b"ftyp" + b"isom" + b"\x00" * 12
    moov = b"\x00\x00\x02\x00" + b"moov" + b"\x00" * (0x200 - 8)
    mdat = b"\x00\x00\x00\x20" + b"mdat" + b"\x00" * (0x20 - 8)
    prog = ftyp + moov + mdat
    assert not is_dash_init_fmp4(prog)
    assert is_dash_init_fmp4(ftyp + moov)


def test_maybe_prepend_merges_fragment() -> None:
    init = (
        b"\x00\x00\x00\x1cftyp" + b"isom" + b"\x00" * 8
        + b"\x00\x00\x00\x2cmoov" + b"\x00" * 0x28
    )
    seg = b"\x00\x00\x00\x10moof" + b"\x00" * 8 + b"\x00\x00\x00\x10mdat" + b"zzzzzzzz"
    assert _iso_bmff_moof_before_mdat(seg)
    s = _sniff({18: init}, prefer_itag=18)
    out, did = _maybe_prepend_dash_init(seg, s, {"itag": 18})
    assert did
    assert out == init + seg
    assert out.startswith(b"\x00\x00\x00\x1cftyp")
    assert _iso_bmff_moof_before_mdat(out)


def test_maybe_prepend_skips_non_fragment() -> None:
    s = _sniff({18: b"\x00" * 64}, prefer_itag=18)
    full = b"\x00" * 1000
    out, did = _maybe_prepend_dash_init(full, s, {"itag": 18})
    assert not did
    assert out is full


def test_maybe_prepend_uses_unkeyed_init() -> None:
    init = (
        b"\x00\x00\x00\x1c" + b"ftyp" + b"isom" + b"\x00" * 12
        + b"\x00\x00\x00\x2c" + b"moov" + b"\x00" * 0x24
    )
    seg = b"\x00\x00\x00\x10moof" + b"\x00" * 8 + b"\x00\x00\x00\x10mdat" + b"zzzzzzzz"
    s = _sniff({}, prefer_itag=18)
    s.dash_init_unkeyed = init
    out, did = _maybe_prepend_dash_init(seg, s, {"itag": 18})
    assert did
    assert out == init + seg
