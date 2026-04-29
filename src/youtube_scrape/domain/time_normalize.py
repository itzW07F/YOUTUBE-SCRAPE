"""Normalize YouTube time labels into absolute UTC datetimes."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_RELATIVE_TIME_RE = re.compile(
    r"(?P<value>\d+)\s*(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago",
    re.IGNORECASE,
)

_JUST_NOW_RE = re.compile(r"\bjust now\b", re.IGNORECASE)
_YESTERDAY_RE = re.compile(r"\byesterday\b", re.IGNORECASE)
_ISO_LIKE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ][^ ]+)?$")
_MONTH_NAME_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}$",
    re.IGNORECASE,
)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_published_text_to_utc(
    text: str | None,
    *,
    now_utc: datetime | None = None,
) -> datetime | None:
    """Parse relative or absolute published text into a UTC datetime."""
    if not text:
        return None
    raw = text.strip()
    if not raw:
        return None
    now = _to_utc(now_utc or datetime.now(UTC))

    if _JUST_NOW_RE.search(raw):
        return now
    if _YESTERDAY_RE.search(raw):
        return now - timedelta(days=1)

    relative = _RELATIVE_TIME_RE.search(raw)
    if relative:
        value = int(relative.group("value"))
        unit = relative.group("unit").lower()
        # Approximate month/year units because source does not include exact date.
        if unit == "second":
            delta = timedelta(seconds=value)
        elif unit == "minute":
            delta = timedelta(minutes=value)
        elif unit == "hour":
            delta = timedelta(hours=value)
        elif unit == "day":
            delta = timedelta(days=value)
        elif unit == "week":
            delta = timedelta(weeks=value)
        elif unit == "month":
            delta = timedelta(days=value * 30)
        else:
            delta = timedelta(days=value * 365)
        return now - delta

    normalized = raw.replace("Sept ", "Sep ")
    try:
        return _to_utc(datetime.fromisoformat(normalized.replace("Z", "+00:00")))
    except ValueError:
        pass

    if _ISO_LIKE_RE.match(normalized):
        try:
            return _to_utc(datetime.fromisoformat(normalized))
        except ValueError:
            return None

    if _MONTH_NAME_RE.match(normalized):
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return _to_utc(datetime.strptime(normalized, fmt))
            except ValueError:
                continue
    return None
