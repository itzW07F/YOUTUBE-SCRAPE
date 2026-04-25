"""yt-dlp executable resolution (no network)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from unittest import mock

from youtube_scrape.application import yt_dlp_download as yd


def test_resolve_yt_dlp_executable_matches_shutil() -> None:
    found = yd.resolve_yt_dlp_executable()
    w = shutil.which("yt-dlp")
    if w is not None:
        assert found is not None
    alt = (Path(sys.prefix) / "bin" / "yt-dlp")
    if alt.is_file() and w is None:
        assert found == str(alt)


def test_is_yt_dlp_available_uses_resolve() -> None:
    with mock.patch.object(yd, "resolve_yt_dlp_executable", return_value=None):
        assert yd.is_yt_dlp_available() is False
    with mock.patch.object(yd, "resolve_yt_dlp_executable", return_value="/x/yt-dlp"):
        assert yd.is_yt_dlp_available() is True


def test_network_debug_log_write_json(tmp_path) -> None:
    from youtube_scrape.application import network_debug as ndmod

    log = ndmod.NetworkDebugLog()
    log.add("test", x=1)
    log.set_sniffer({"a": 1})
    log.set_result({"outcome": "ok"})
    p = tmp_path / "n.json"
    log.write_json(p)
    data = p.read_text(encoding="utf-8")
    assert "test" in data
    assert "outcome" in data
    sp = tmp_path / "b.bin"
    assert log.spool_bytes(sp, b"hello")
    assert sp.read_bytes() == b"hello"
