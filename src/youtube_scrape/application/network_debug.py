"""Structured network diagnostics for the Camoufox download path."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MAX_EVENTS = 600


def url_preview(u: str, max_len: int = 220) -> str:
    """Shorten long URLs; keep the start (host, path, itag) for logs."""
    if not u:
        return ""
    if len(u) <= max_len:
        return u
    return f"{u[: max_len - 3]}..."


def body_sha256_prefix(data: bytes, n: int = 16) -> str:
    """Hex digest prefix for spool / verification (not full file hash for huge blobs in JSON)."""
    h = hashlib.sha256()
    to_hash = data if len(data) <= 8_000_000 else data[:8_000_000]
    h.update(to_hash)
    return h.hexdigest()[:n]


@dataclass
class NetworkDebugLog:
    """Mutable capture buffer written to ``*.network-debug.json`` after download."""

    events: list[dict[str, Any]] = field(default_factory=list)
    sniffer: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    skipped_httpx_googlevideo: bool = False
    _started_monotonic: float = field(default_factory=time.monotonic)

    def add(self, phase: str, **kwargs: Any) -> None:
        if len(self.events) >= _MAX_EVENTS:
            if not any(e.get("phase") == "events_truncated" for e in self.events):
                self.events.append(
                    {
                        "phase": "events_truncated",
                        "limit": _MAX_EVENTS,
                        "t_offset_s": round(time.monotonic() - self._started_monotonic, 3),
                    }
                )
            return
        self.events.append(
            {
                "phase": phase,
                "t_offset_s": round(time.monotonic() - self._started_monotonic, 3),
                **kwargs,
            }
        )

    def set_sniffer(self, d: dict[str, Any] | None) -> None:
        self.sniffer = d

    def set_result(self, d: dict[str, Any] | None) -> None:
        self.result = d

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "skipped_httpx_googlevideo": self.skipped_httpx_googlevideo,
            "events": self.events,
            "sniffer": self.sniffer,
            "result": self.result,
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_jsonable(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def spool_bytes(self, path: Path, data: bytes, *, max_bytes: int = 104_857_600) -> bool:
        """Write a binary sample; returns whether write occurred."""
        if not data:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = data if len(data) <= max_bytes else data[:max_bytes]
        path.write_bytes(blob)
        self.add("spool_written", path=str(path), bytes_written=len(blob), truncated=len(data) > len(blob))
        return True
