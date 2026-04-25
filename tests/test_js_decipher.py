"""Tests for JavaScript deciphering module.

These tests verify the cipher parsing logic. Full deciphering tests require
Node.js and real YouTube player JS.
"""

from __future__ import annotations

import pytest

from youtube_scrape.domain.js_decipher import (
    apply_n_param_to_url,
    apply_sig_to_url,
    parse_cipher_components,
)
from youtube_scrape.domain.signature_cipher import (
    extract_cipher_components,
    get_format_cipher_hint,
    needs_deciphering,
)


def test_parse_cipher_components() -> None:
    """Test parsing a signatureCipher string."""
    cipher = "sp=sig&url=https%3A%2F%2Frr1---x.googlevideo.com%2Fvideoplayback%3Fitag%3D18&s=ABC123%3D%3D"
    parts = parse_cipher_components(cipher)

    assert parts["url"] == "https://rr1---x.googlevideo.com/videoplayback?itag=18"
    assert parts["s"] == "ABC123=="
    assert parts["sp"] == "sig"


def test_parse_cipher_with_n_param() -> None:
    """Test parsing cipher with n-parameter."""
    cipher = "url=https%3A%2F%2Fgooglevideo.com%2Fvideoplayback&n=xyz789&s=SIG"
    parts = parse_cipher_components(cipher)

    assert "n" in parts
    assert parts["n"] == "xyz789"
    assert parts["s"] == "SIG"


def test_apply_sig_to_url() -> None:
    """Test applying deciphered signature to URL."""
    base_url = "https://rr1---x.googlevideo.com/videoplayback?itag=18"
    sig = "DECIPHEREDSIG"

    result = apply_sig_to_url(base_url, sig, "sig")
    assert "sig=DECIPHEREDSIG" in result
    assert "itag=18" in result


def test_apply_n_param_to_url() -> None:
    """Test applying new n-parameter to URL."""
    url = "https://rr1---x.googlevideo.com/videoplayback?itag=18&n=OLDN"
    new_n = "NEWNPARAM"

    result = apply_n_param_to_url(url, new_n)
    assert "n=NEWNPARAM" in result
    assert "itag=18" in result
    assert "n=OLDN" not in result


def test_needs_deciphering_with_cipher() -> None:
    """Test detection of ciphered formats."""
    fmt_cipher = {"signatureCipher": "url=...&s=..."}
    assert needs_deciphering(fmt_cipher) is True

    fmt_cipher2 = {"cipher": "url=...&s=..."}
    assert needs_deciphering(fmt_cipher2) is True


def test_needs_deciphering_with_n_param() -> None:
    """Test detection of n-param in plain URL."""
    fmt_n = {"url": "https://googlevideo.com/videoplayback?n=xyz"}
    assert needs_deciphering(fmt_n) is True


def test_needs_deciphering_plain() -> None:
    """Test that plain URLs don't need deciphering."""
    fmt_plain = {"url": "https://googlevideo.com/videoplayback?itag=18"}
    assert needs_deciphering(fmt_plain) is False


def test_get_format_cipher_hint() -> None:
    """Test cipher hint extraction."""
    fmt = {
        "signatureCipher": "url=...&s=...&n=...",
        "url": None,
    }
    hint = get_format_cipher_hint(fmt)

    assert hint["has_cipher"] is True
    assert hint["has_n_param"] is True
    assert hint["needs_sig_decipher"] is True
    assert hint["needs_n_regen"] is True


def test_get_format_cipher_hint_plain() -> None:
    """Test cipher hint for plain format."""
    fmt = {"url": "https://googlevideo.com/videoplayback?itag=18"}
    hint = get_format_cipher_hint(fmt)

    assert hint["has_cipher"] is False
    assert hint["has_n_param"] is False
    assert hint["needs_sig_decipher"] is False
