"""Convert timedtext XML into plain text or WebVTT-ish output."""

from __future__ import annotations

from typing import Any, Literal

import defusedxml.ElementTree as ET

CaptionFormat = Literal["txt", "vtt"]


def timedtext_json3_to_plain(data: dict[str, Any]) -> str:
    """Flatten YouTube ``fmt=srv3`` / JSON3 timedtext ``events`` into plain text."""
    lines: list[str] = []
    for ev in data.get("events") or []:
        if not isinstance(ev, dict):
            continue
        parts: list[str] = []
        for seg in ev.get("segs") or []:
            if not isinstance(seg, dict):
                continue
            u = seg.get("utf8")
            if isinstance(u, str) and u:
                parts.append(u)
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def timedtext_xml_to_plain(xml_text: str) -> str:
    """Join caption text nodes in document order with newlines."""
    root = ET.fromstring(xml_text)
    lines: list[str] = []
    for node in root.iter():
        if node.tag.endswith("text") and node.text:
            lines.append(node.text.strip())
    return "\n".join(lines).strip()


def timedtext_xml_to_webvtt(xml_text: str) -> str:
    """Produce a minimal WebVTT document from timedtext XML."""
    root = ET.fromstring(xml_text)
    parts: list[str] = ["WEBVTT", ""]
    for node in root.iter():
        if not node.tag.endswith("text"):
            continue
        start = node.get("start")
        dur = node.get("dur")
        text = (node.text or "").strip()
        if start is None or dur is None or not text:
            continue
        try:
            start_f = float(start)
            dur_f = float(dur)
        except ValueError:
            continue
        end_f = start_f + dur_f

        def fmt_ts(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = seconds % 60
            if h > 0:
                return f"{h:02d}:{m:02d}:{s:06.3f}"
            return f"{m:02d}:{s:06.3f}"

        parts.append(f"{fmt_ts(start_f)} --> {fmt_ts(end_f)}")
        parts.append(text)
        parts.append("")
    return "\n".join(parts).strip() + "\n"
