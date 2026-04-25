"""Local filesystem sink."""

from __future__ import annotations

from pathlib import Path


class LocalFileSink:
    """Write outputs to disk, creating parent directories."""

    def write_text(self, path: Path, content: str, *, encoding: str = "utf-8") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)

    def write_bytes(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
