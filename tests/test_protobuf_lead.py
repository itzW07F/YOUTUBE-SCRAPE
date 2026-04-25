"""Heuristic for rejecting protobuf-shaped bodies mistaken for media."""

from youtube_scrape.adapters.browser_playwright import _find_isobmff_root, _protobuf_like_lead


def test_protobuf_style_first_byte_detected() -> None:
    assert _protobuf_like_lead(bytes.fromhex("3a020801"))


def test_mp4_ftyp_prefix_not_pb_style() -> None:
    blob = b"\x00\x00\x00\x20ftyp" + b"\x00" * 40
    assert not _protobuf_like_lead(blob)


def test_find_isobmff_root_after_ump_prefix() -> None:
    prefix = bytes.fromhex("3a0208012f0c0a05080010b009120310f02e34080a064341")
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    blob = prefix + mp4
    assert _find_isobmff_root(blob) == len(prefix)
