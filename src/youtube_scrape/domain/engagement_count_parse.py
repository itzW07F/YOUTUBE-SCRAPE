"""Parse counts from YouTube accessibility/title strings (subset of yt-dlp ``parse_count``)."""

from __future__ import annotations

import re

_STRIP_LEADING_NON_DIGITS_RE = re.compile(r"^[^\d]+")
_COUNT_WITH_SUFFIX_RE = re.compile(r"^([\d,.]+)\s*([KkMmBb])\b")


def parse_engagement_count_text(raw: str | None) -> int | None:
    """Return a non-negative int count, or ``None`` if no parseable number (e.g. \"Dislike\")."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = _STRIP_LEADING_NON_DIGITS_RE.sub("", s)
    if not s:
        return None
    plain = re.match(r"^([\d,]+)$", s)
    if plain:
        try:
            return int(plain.group(1).replace(",", ""))
        except ValueError:
            return None
    m = _COUNT_WITH_SUFFIX_RE.match(s)
    if m:
        try:
            base = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
        suf = m.group(2).upper()
        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suf, 1)
        return int(base * mult)
    lead = re.match(r"^([\d,.]+)", s)
    if lead:
        try:
            return int(float(lead.group(1).replace(",", "")))
        except ValueError:
            return None
    return None
