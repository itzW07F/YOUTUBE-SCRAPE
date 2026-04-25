"""Extract embedded JSON objects from HTML or inline script text."""

from __future__ import annotations

import json
import re
from typing import Any

from youtube_scrape.exceptions import ExtractionError


def extract_object_after_marker(text: str, marker: str) -> dict[str, Any]:
    """Return the first JSON object found immediately after ``marker`` in ``text``.

    ``marker`` should include any delimiter you expect before the opening brace, e.g.
    ``'ytInitialPlayerResponse'`` with the surrounding ``=`` matched separately.

    Raises:
        ExtractionError: if the object cannot be located or parsed.
    """
    idx = text.find(marker)
    if idx == -1:
        msg = f"Marker not found: {marker!r}"
        raise ExtractionError(msg, details="page_html_missing_marker")
    brace = text.find("{", idx)
    if brace == -1:
        msg = f"No opening brace after marker: {marker!r}"
        raise ExtractionError(msg, details="page_html_missing_json_start")
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(text[brace:])
    except json.JSONDecodeError as exc:  # pragma: no cover - exercised via fixtures
        msg = f"Invalid JSON after marker: {marker!r}"
        raise ExtractionError(msg, details=str(exc)) from exc
    if not isinstance(obj, dict):
        msg = f"Expected JSON object after marker: {marker!r}"
        raise ExtractionError(msg, details="json_not_object")
    return obj


_PLAYER_MARKERS = (
    "var ytInitialPlayerResponse = ",
    "ytInitialPlayerResponse = ",
    'window["ytInitialPlayerResponse"] = ',
)


def extract_yt_initial_player_response(html: str) -> dict[str, Any]:
    """Locate ``ytInitialPlayerResponse`` in HTML and parse it."""
    for marker in _PLAYER_MARKERS:
        if marker in html:
            return extract_object_after_marker(html, marker)
    # Fallback: sometimes embedded as "playerResponse":{...} inside larger blob
    m = re.search(r'"playerResponse"\s*:\s*(\{)', html)
    if m:
        start = m.start(1)
        decoder = json.JSONDecoder()
        try:
            obj, _ = decoder.raw_decode(html[start:])
        except json.JSONDecodeError as exc:
            msg = "Failed to parse playerResponse JSON"
            raise ExtractionError(msg, details=str(exc)) from exc
        if isinstance(obj, dict):
            return obj
    msg = "Could not locate ytInitialPlayerResponse"
    raise ExtractionError(msg, details="player_response_missing")


_INITIAL_DATA_MARKERS = (
    "var ytInitialData = ",
    "ytInitialData = ",
    'window["ytInitialData"] = ',
)


def extract_yt_initial_data(html: str) -> dict[str, Any]:
    """Locate ``ytInitialData`` in HTML and parse it."""
    for marker in _INITIAL_DATA_MARKERS:
        if marker in html:
            return extract_object_after_marker(html, marker)
    msg = "Could not locate ytInitialData"
    raise ExtractionError(msg, details="initial_data_missing")
