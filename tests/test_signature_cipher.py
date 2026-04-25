"""``signatureCipher`` query parsing (no network)."""

from __future__ import annotations

from youtube_scrape.domain.signature_cipher import (
    googlevideo_url_hint,
    has_cipher_only,
    is_googlevideo_media_url,
    url_from_signature_cipher,
)


def test_url_from_signature_cipher() -> None:
    s = "sp=sig&url=https%3A%2F%2Frr1---x.googlevideo.com%2Fvideoplayback%3Fitag%3D18"
    u = url_from_signature_cipher(s)
    assert u is not None
    assert "googlevideo.com" in u
    assert is_googlevideo_media_url(u)


def test_has_cipher_only() -> None:
    assert has_cipher_only({"signatureCipher": "a=1", "url": ""})
    assert not has_cipher_only({"url": "https://a.example/v.mp4"})


def test_googlevideo_url_hint_plain() -> None:
    h = googlevideo_url_hint({"url": "https://a.googlevideo.com/x", "mimeType": "video/mp4"})
    assert h and "googlevideo" in h
