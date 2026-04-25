"""Innertube helpers for youtubei/v1/next continuations."""

from __future__ import annotations

import json
import re
from typing import Any

from youtube_scrape.exceptions import ExtractionError


def extract_innertube_api_key(html: str) -> str:
    """Parse INNERTUBE_API_KEY from watch HTML."""
    m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    if not m:
        msg = "INNERTUBE_API_KEY not found in HTML"
        raise ExtractionError(msg, details="innertube_api_key_missing")
    return m.group(1)


def extract_innertube_context(html: str) -> dict[str, Any]:
    """Parse INNERTUBE_CONTEXT JSON object from watch HTML."""
    m = re.search(r'"INNERTUBE_CONTEXT"\s*:\s*(\{)', html)
    if not m:
        msg = "INNERTUBE_CONTEXT not found in HTML"
        raise ExtractionError(msg, details="innertube_context_missing")
    start = m.start(1)
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(html[start:])
    except json.JSONDecodeError as exc:
        msg = "Failed to parse INNERTUBE_CONTEXT JSON"
        raise ExtractionError(msg, details=str(exc)) from exc
    if not isinstance(obj, dict):
        msg = "INNERTUBE_CONTEXT JSON was not an object"
        raise ExtractionError(msg, details="innertube_context_not_object")
    return obj


def next_endpoint(api_key: str) -> str:
    """Build youtubei/v1/next URL."""
    return f"https://www.youtube.com/youtubei/v1/next?key={api_key}"
