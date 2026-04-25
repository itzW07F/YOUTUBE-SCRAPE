"""Optional full-media download via the ``yt-dlp`` CLI (not a Python dependency).

YouTube often returns 403 to out-of-context ``googlevideo`` GETs; in-project capture can still
yield short fMP4 fragments. When a complete file is required, install ``yt-dlp`` and pass
``--use-yt-dlp`` on the download command.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from youtube_scrape.exceptions import YouTubeScrapeError

log = logging.getLogger(__name__)


def resolve_yt_dlp_executable() -> str | None:
    """Return ``yt-dlp`` (or ``youtube-dl``) path, or ``None`` if not found."""
    for name in ("yt-dlp", "youtube-dl"):
        path = shutil.which(name)
        if path:
            return path
    bindir = Path(sys.prefix) / "bin"
    for name in ("yt-dlp", "youtube-dl"):
        candidate = bindir / name
        if candidate.is_file():
            return str(candidate)
    return None


def is_yt_dlp_available() -> bool:
    """True when a full-file download can run via the ``yt-dlp`` CLI (production default)."""
    return resolve_yt_dlp_executable() is not None


def _yt_dlp_executable() -> str:
    """Resolve ``yt-dlp`` even when the venv ``bin`` dir is not on ``PATH`` (common under IDEs)."""
    p = resolve_yt_dlp_executable()
    if p is not None:
        return p
    msg = "No yt-dlp on PATH (try: pipx install yt-dlp, or see https://github.com/yt-dlp/yt-dlp)."
    raise YouTubeScrapeError(msg, details="yt_dlp_missing")


def run_yt_dlp_download(
    url_or_id: str,
    output: Path,
    *,
    name_from_title: bool,
    timeout_s: float = 3600.0,
) -> tuple[Path, dict[str, Any]]:
    """Run ``yt-dlp`` and return ``(written_path, info_dict)``.

    * ``name_from_title=False``: ``output`` is the desired file path (``stem.%(ext)s`` under its parent).
    * ``name_from_title=True``: ``output`` is a directory; use ``%(title)s.%(ext)s`` in that directory.
    """
    exe = _yt_dlp_executable()
    if name_from_title:
        suffixes = (".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".bin")
        if output.suffix.lower() in suffixes:
            msg = "With name_from_title, output must be a directory when using yt-dlp."
            raise YouTubeScrapeError(msg, details="yt_dlp_bad_output")
        output.mkdir(parents=True, exist_ok=True)
        before_mtime: dict[Path, float] = {}
        for p in output.iterdir():
            if p.is_file():
                before_mtime[p.resolve()] = p.stat().st_mtime
        outtmpl = str((output / "%(title)s.%(ext)s").resolve())
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        parent = output.parent
        before_mtime = {}
        for p in parent.iterdir():
            if p.is_file():
                before_mtime[p.resolve()] = p.stat().st_mtime
        outtmpl = str((parent / f"{output.stem}.%(ext)s").resolve())

    cmd = [
        exe,
        "--no-playlist",
        "--no-warnings",
        "--force-overwrites",
        "--no-continue",
        "-f",
        "best",
        "-o",
        outtmpl,
        url_or_id,
    ]
    log.info("yt_dlp_download_start", extra={"exe": exe})
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-4000:]
        msg = f"yt-dlp exited with status {proc.returncode}"
        raise YouTubeScrapeError(msg, details=tail)

    def _touched_media(paths: list[Path]) -> list[Path]:
        out_list: list[Path] = []
        for p in paths:
            if not p.is_file():
                continue
            if p.suffix.lower() not in (".mp4", ".webm", ".mkv", ".m4a"):
                continue
            r = p.resolve()
            m = p.stat().st_mtime
            prev = before_mtime.get(r)
            if prev is None or m > prev + 0.5 or m >= t0 - 2.0:
                out_list.append(p)
        return out_list

    if name_from_title:
        media = sorted(
            _touched_media([p for p in output.iterdir()]),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not media:
            msg = "yt-dlp reported success but no media file was updated in the output directory."
            raise YouTubeScrapeError(msg, details=str(output))
        written = media[0]
    else:
        media = sorted(
            _touched_media([p for p in output.parent.iterdir() if p.stem == output.stem]),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not media:
            if output.exists() and output.is_file() and output.stat().st_mtime >= t0 - 2.0:
                written = output
            else:
                msg = "yt-dlp reported success but the expected output file is missing."
                raise YouTubeScrapeError(msg, details=str(output))
        else:
            written = media[0]
    info: dict[str, Any] = {
        "path": str(written),
        "bytes_written": written.stat().st_size,
        "strategy": "yt_dlp",
    }
    log.info("yt_dlp_download_ok", extra={"path": str(written), "bytes": info["bytes_written"]})
    return written, info
