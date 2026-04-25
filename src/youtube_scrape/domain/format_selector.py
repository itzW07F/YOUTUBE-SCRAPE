"""Select downloadable stream formats from ``streamingData`` entries."""

from __future__ import annotations

from typing import Any

from youtube_scrape.exceptions import UnsupportedFormatError


def _has_cipher(fmt: dict[str, Any]) -> bool:
    return bool(fmt.get("signatureCipher") or fmt.get("cipher"))


def _tag_cipher_playback(fmt: dict[str, Any]) -> dict[str, Any]:
    c = dict(fmt)
    c["__cipher_playback_only"] = True
    return c


def _has_plain_url(fmt: dict[str, Any]) -> bool:
    url = fmt.get("url")
    return isinstance(url, str) and bool(url) and not _has_cipher(fmt)


def _height(fmt: dict[str, Any]) -> int:
    label = fmt.get("qualityLabel") or ""
    if isinstance(label, str) and label.endswith("p"):
        try:
            return int(label[:-1])
        except ValueError:
            return 0
    return int(fmt.get("height") or 0)


def select_best_progressive_format(formats: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the highest-resolution muxed progressive format with a plain ``url``.

    Expect ``formats`` rows from ``streamingData.formats`` only—do not pass
    ``adaptiveFormats``, or ``best`` may choose a video-only DASH representation.
    """
    candidates = [f for f in formats if _has_plain_url(f)]
    if not candidates:
        ciph = [f for f in formats if _has_cipher(f)]
        if ciph:
            ciph.sort(key=_height, reverse=True)
            return _tag_cipher_playback(ciph[0])
        msg = "No progressive format rows in streamingData.formats"
        raise UnsupportedFormatError(msg, details="cipher_or_missing_url")
    candidates.sort(key=_height, reverse=True)
    return candidates[0]


def _audio_bitrate_score(fmt: dict[str, Any]) -> int:
    for key in ("averageBitrate", "bitrate"):
        v = fmt.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip(), 10)
    return 0


def _is_plain_audio_only(fmt: dict[str, Any]) -> bool:
    if not _has_plain_url(fmt):
        return False
    return _is_audio_mime_only(fmt)


def _is_audio_mime_only(fmt: dict[str, Any]) -> bool:
    mime = fmt.get("mimeType")
    if not isinstance(mime, str):
        return False
    head = mime.split(";", 1)[0].strip().lower()
    if not head.startswith("audio/"):
        return False
    if "video" in head:
        return False
    return True


def select_best_audio_format(formats: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the highest-bitrate adaptive **audio-only** format with a plain ``url``."""
    candidates = [f for f in formats if _is_plain_audio_only(f)]
    if not candidates:
        ciph = [f for f in formats if _has_cipher(f) and _is_audio_mime_only(f)]
        if ciph:
            ciph.sort(key=_audio_bitrate_score, reverse=True)
            return _tag_cipher_playback(ciph[0])
        msg = "No audio-only format with a plain URL was found (ciphered streams not supported yet)"
        raise UnsupportedFormatError(msg, details="cipher_or_missing_audio_url")
    candidates.sort(key=_audio_bitrate_score, reverse=True)
    return candidates[0]


def select_worst_audio_format(formats: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the lowest-bitrate adaptive **audio-only** format with a plain ``url``."""
    candidates = [f for f in formats if _is_plain_audio_only(f)]
    if not candidates:
        ciph = [f for f in formats if _has_cipher(f) and _is_audio_mime_only(f)]
        if ciph:
            ciph.sort(key=_audio_bitrate_score)
            return _tag_cipher_playback(ciph[0])
        msg = "No audio-only format with a plain URL was found (ciphered streams not supported yet)"
        raise UnsupportedFormatError(msg, details="cipher_or_missing_audio_url")
    candidates.sort(key=_audio_bitrate_score)
    return candidates[0]


def select_worst_progressive_format(formats: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the lowest-resolution progressive format with a plain ``url``."""
    candidates = [f for f in formats if _has_plain_url(f)]
    if not candidates:
        ciph = [f for f in formats if _has_cipher(f)]
        if ciph:
            ciph.sort(key=_height)
            return _tag_cipher_playback(ciph[0])
        msg = "No progressive format rows in streamingData.formats"
        raise UnsupportedFormatError(msg, details="cipher_or_missing_url")
    candidates.sort(key=_height)
    return candidates[0]


def select_by_itag(formats: list[dict[str, Any]], itag: int) -> dict[str, Any]:
    """Return the format dict matching ``itag`` if it has a plain URL."""
    for fmt in formats:
        if int(fmt.get("itag") or 0) != itag:
            continue
        if not _has_plain_url(fmt) and not _has_cipher(fmt):
            msg = f"Format itag={itag} has no url or signatureCipher"
            raise UnsupportedFormatError(msg, details="missing_url_and_cipher")
        if _has_cipher(fmt) and not _has_plain_url(fmt):
            return _tag_cipher_playback(fmt)
        return fmt
    msg = f"No format found for itag={itag}"
    raise UnsupportedFormatError(msg, details="itag_not_found")
