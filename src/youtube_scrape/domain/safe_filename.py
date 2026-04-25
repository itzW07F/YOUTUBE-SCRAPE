"""Map human-readable titles to single path components (no path separators)."""

from __future__ import annotations

import re


def safe_video_filename(
    title: str,
    *,
    default_stem: str = "video",
    extension: str = ".mp4",
    max_stem_chars: int = 160,
) -> str:
    """Return ``<sanitized title>.mp4`` safe for POSIX and Windows file names."""
    ext = extension if extension.startswith(".") else f".{extension}"
    raw = (title or "").strip()
    stem = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "", raw)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if not stem:
        stem = default_stem
    if len(stem) > max_stem_chars:
        stem = stem[:max_stem_chars].rstrip(" .")
    return f"{stem}{ext}"
