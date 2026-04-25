"""YouTube ``signatureCipher`` / ``cipher`` fields (not AES ``encryption`` in the asset sense).

The player applies **JavaScript n/sig transforms** to the ``url=`` in this blob before requesting
`googlevideo`. This module provides both **parsing** (legacy) and **deciphering** (via Node.js)
functionality to transform ciphered URLs into playable URLs.

Example ciphered URL components:
- ``s``: The obfuscated signature (needs deciphering)
- ``sp``: The signature parameter name (usually "sig" or "signature")
- ``n``: The throttling parameter (needs token regeneration)
- ``url``: The base URL that needs the signature appended
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse


def url_from_signature_cipher(s: str | None) -> str | None:
    """Return the **base** `url=…` from a ``signatureCipher`` / ``cipher`` string (URL-decoded).

    This URL is often not directly fetchable (missing valid ``n``/``sig``); the Camoufox path
    should rely on **playback** capture, not a bare ``GET`` to this value.
    """
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    m = re.search(r"(?:^|&)url=([^&]+)", t)
    if m:
        return unquote(m.group(1).replace("+", "%20"))
    m2 = re.search(r"(?:^|&)url=([^&]+)$", t.replace("\n", ""))
    if m2:
        return unquote(m2.group(1).replace("+", "%20"))
    return None


def has_cipher_only(fmt: dict[str, Any]) -> bool:
    """True when the row has ``signatureCipher``/``cipher`` and no plain top-level ``url`` string."""
    return bool(fmt.get("signatureCipher") or fmt.get("cipher")) and not (
        isinstance(fmt.get("url"), str) and str(fmt.get("url") or "").strip()
    )


def googlevideo_url_hint(fmt: dict[str, Any]) -> str | None:
    """If the format has a plain ``url``, return it; if cipher, parse the embedded base URL only."""
    u = fmt.get("url")
    if isinstance(u, str) and u.strip() and not (fmt.get("signatureCipher") or fmt.get("cipher")):
        return u
    s = fmt.get("signatureCipher") or fmt.get("cipher")
    if not s:
        return None
    u2 = url_from_signature_cipher(str(s))
    return u2 if isinstance(u2, str) and u2.strip() else None


def is_googlevideo_media_url(href: str) -> bool:
    try:
        host = urlparse(href).netloc.lower()
    except (TypeError, ValueError):
        return False
    return "googlevideo.com" in host or "googleusercontent.com" in host


def extract_cipher_components(cipher_string: str) -> dict[str, str]:
    """Parse a signatureCipher string into its components.

    Args:
        cipher_string: The signatureCipher or cipher value from streamingData.

    Returns:
        Dict with keys: 'url' (base URL), 's' (signature), 'sp' (sig param name), 'n' (n-param).
        Values are URL-decoded. Missing components are omitted.
    """
    from urllib.parse import unquote_plus

    decoded = unquote_plus(cipher_string)
    parts: dict[str, str] = {}

    # Extract url parameter (the base googlevideo URL)
    url_match = re.search(r'(?:^|&)url=([^&]+)', decoded)
    if url_match:
        parts["url"] = unquote(url_match.group(1))

    # Extract signature (s parameter) - the obfuscated sig to decipher
    sig_match = re.search(r'(?:^|&)s=([^&]+)', decoded)
    if sig_match:
        parts["s"] = unquote(sig_match.group(1))

    # Extract signature parameter name (sp) - usually "sig" or "signature"
    sp_match = re.search(r'(?:^|&)sp=([^&]+)', decoded)
    if sp_match:
        parts["sp"] = unquote(sp_match.group(1))
    else:
        parts["sp"] = "sig"  # Default per YouTube convention

    # Extract n parameter (throttling/PO token) - needs regeneration
    n_match = re.search(r'(?:^|&)n=([^&]+)', decoded)
    if n_match:
        parts["n"] = unquote(n_match.group(1))

    return parts


def needs_deciphering(fmt: dict[str, Any]) -> bool:
    """Check if a format requires JavaScript deciphering to be playable.

    Args:
        fmt: The format dict from streamingData.

    Returns:
        True if the format has cipher components that need deciphering.
    """
    # Has explicit cipher field
    if fmt.get("signatureCipher") or fmt.get("cipher"):
        return True

    # Has plain URL but might have stale n-param (throttling)
    url = fmt.get("url")
    if isinstance(url, str) and url:
        # Check if URL has n-param (might be stale)
        try:
            qs = urlparse(url).query
            if "n=" in qs:
                return True
        except Exception:
            pass

    return False


def get_format_cipher_hint(fmt: dict[str, Any]) -> dict[str, Any]:
    """Get cipher information about a format without deciphering.

    Args:
        fmt: The format dict from streamingData.

    Returns:
        Dict with cipher metadata for diagnostics.
    """
    result: dict[str, Any] = {
        "has_cipher": False,
        "has_n_param": False,
        "needs_sig_decipher": False,
        "needs_n_regen": False,
    }

    # Check for cipher
    cipher = fmt.get("signatureCipher") or fmt.get("cipher")
    if cipher:
        result["has_cipher"] = True
        result["needs_sig_decipher"] = True
        components = extract_cipher_components(str(cipher))
        if "n" in components:
            result["has_n_param"] = True
            result["needs_n_regen"] = True

    # Check plain URL for n-param
    url = fmt.get("url")
    if isinstance(url, str) and url and "n=" in url:
        result["has_n_param"] = True
        # Only needs regen if we're having issues (throttling detection)

    return result
