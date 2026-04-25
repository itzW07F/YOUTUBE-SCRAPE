import pytest

from youtube_scrape.domain.format_selector import (
    select_best_audio_format,
    select_best_progressive_format,
    select_by_itag,
    select_worst_audio_format,
    select_worst_progressive_format,
)
from youtube_scrape.exceptions import UnsupportedFormatError


def test_select_best_progressive() -> None:
    formats = [
        {"itag": 18, "qualityLabel": "360p", "url": "https://a.example/a.mp4"},
        {"itag": 22, "qualityLabel": "720p", "url": "https://a.example/b.mp4"},
    ]
    chosen = select_best_progressive_format(formats)
    assert chosen["itag"] == 22


def test_select_worst_progressive() -> None:
    formats = [
        {"itag": 18, "qualityLabel": "360p", "url": "https://a.example/a.mp4"},
        {"itag": 22, "qualityLabel": "720p", "url": "https://a.example/b.mp4"},
    ]
    chosen = select_worst_progressive_format(formats)
    assert chosen["itag"] == 18


def test_ciphered_falls_back_to_playback() -> None:
    formats = [
        {"itag": 18, "qualityLabel": "360p", "signatureCipher": "sp=sig&url=https%3A%2F%2Fa.test%2Fa"},
        {"itag": 22, "qualityLabel": "720p", "signatureCipher": "sp=sig&url=https%3A%2F%2Fa.test%2Fb"},
    ]
    c = select_best_progressive_format(formats)
    assert c.get("__cipher_playback_only") is True
    assert c["itag"] == 22


def test_select_by_itag_cipher() -> None:
    formats = [
        {"itag": 18, "signatureCipher": "s=x&sp=sig&url=https%3A%2F%2Fgg.googlevideo.com%2Fv"},
    ]
    c = select_by_itag(formats, 18)
    assert c.get("__cipher_playback_only") is True


def test_select_by_itag() -> None:
    formats = [{"itag": 18, "url": "https://a.example/a.mp4"}]
    assert select_by_itag(formats, 18)["itag"] == 18


def test_select_best_audio_by_bitrate() -> None:
    formats = [
        {
            "itag": 140,
            "mimeType": "audio/mp4; codecs=\"mp4a.40.2\"",
            "url": "https://a.example/a.m4a",
            "averageBitrate": 128_000,
        },
        {
            "itag": 251,
            "mimeType": "audio/webm; codecs=\"opus\"",
            "url": "https://a.example/a.webm",
            "averageBitrate": 160_000,
        },
    ]
    assert select_best_audio_format(formats)["itag"] == 251


def test_select_worst_audio_by_bitrate() -> None:
    formats = [
        {
            "itag": 140,
            "mimeType": "audio/mp4; codecs=\"mp4a.40.2\"",
            "url": "https://a.example/a.m4a",
            "averageBitrate": 128_000,
        },
        {
            "itag": 251,
            "mimeType": "audio/webm; codecs=\"opus\"",
            "url": "https://a.example/a.webm",
            "averageBitrate": 160_000,
        },
    ]
    assert select_worst_audio_format(formats)["itag"] == 140


def test_no_plain_audio_raises() -> None:
    formats = [{"itag": 18, "mimeType": "video/mp4", "url": "https://a.example/v.mp4"}]
    with pytest.raises(UnsupportedFormatError):
        select_best_audio_format(formats)
