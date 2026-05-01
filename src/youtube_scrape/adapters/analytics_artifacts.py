"""Filesystem reads for analytics inputs (scrape output folder)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def envelope_inner_data(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return ResultEnvelope ``data`` when present; otherwise the root object (legacy flat dumps).

    Aligned with the Electron ``envelopeDataRoot`` helper so analytics and artifact viewers agree.
    """

    inner = envelope.get("data")
    return inner if isinstance(inner, dict) else envelope


def read_metadata_history_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    lines: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            lines.append(obj)
    return lines
