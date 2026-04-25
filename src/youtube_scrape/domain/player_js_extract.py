"""Extract and cache YouTube player JavaScript for signature deciphering.

YouTube's player JS contains the signature (sig) and n-parameter transforms that must be
applied to googlevideo URLs before they become playable. This module extracts the player
JS URL from watch pages and caches it for deciphering operations.
"""

from __future__ import annotations

import re
from typing import Any

from youtube_scrape.exceptions import ExtractionError

# Player base.js URL patterns in watch page HTML/initial data
_PLAYER_JS_PATTERNS = [
    # Standard player base.js
    re.compile(r'"([^"]*player[^"]*base\.js)"'),
    re.compile(r'"([^"]*\/s\/player\/[^"]+\/player_ias[^"]*\.js)"'),
    re.compile(r'"([^"]*\/s\/player\/[^"]+\/base\.js)"'),
    # From player response assets
    re.compile(r'"jsUrl":"([^"]+)"'),
    re.compile(r'"assets"[^}]*"js":"([^"]+)"'),
]

# Signature function name patterns (change periodically, need multiple)
_SIG_FUNCTION_PATTERNS = [
    # Classic patterns
    re.compile(r'\b[a-zA-Z0-9_$]+\s*=\s*function\([^)]*\)\s*\{\s*return\s+[^}]*\.signature\b'),
    re.compile(r'\b[a-zA-Z0-9_$]+\s*&&\s*[a-zA-Z0-9_$]+\s*\.sig\|\|[^}]*\.[a-zA-Z0-9_$]+\b'),
    re.compile(r'([a-zA-Z0-9_$]+)\s*=\s*function\([^)]*\)\s*\{\s*[^}]*\.split\([^}]*\.join\('),
    # Newer patterns
    re.compile(r'\b([a-zA-Z0-9_$]+)\s*:\s*function\([^)]*\)\s*\{\s*return\s+[^}]*\.reverse\(\)'),
    re.compile(r'["\']signature["\']\s*:\s*([a-zA-Z0-9_$]+)\b'),
]

# N-parameter function patterns
_N_FUNCTION_PATTERNS = [
    re.compile(r'\b([a-zA-Z0-9_$]+)\s*=\s*function\([a-zA-Z0-9_$]+\)\s*\{\s*[^}]*\.split[^}]*\.join\('),
    re.compile(r'[a-zA-Z0-9_$]+\s*&&\s*[a-zA-Z0-9_$]+\s*\.n\|\|\s*([a-zA-Z0-9_$]+)\b'),
    re.compile(r'["\']n["\']\s*:\s*([a-zA-Z0-9_$]+)\b'),
    re.compile(r'\.get\("n"\)\)&&\s*\(b\s*=\s*([a-zA-Z0-9_$]+)\('),
]

# Obfuscation helpers that need to be extracted with the functions
_HELPER_PATTERNS = [
    re.compile(r'var\s+([a-zA-Z0-9_$]+)\s*=\s*\{[^}]*\}(?:;|\s*,)'),
    re.compile(r'([a-zA-Z0-9_$]+)\s*=\s*\{[^}]*:[^}]*\}(?:;|\s*,)'),
]


def extract_player_js_url(html_or_player: str | dict[str, Any]) -> str | None:
    """Extract player base.js URL from watch page HTML or player response.

    Args:
        html_or_player: Either the raw HTML string or parsed player response dict.

    Returns:
        Absolute or relative URL to the player JS file, or None if not found.
    """
    text = ""
    if isinstance(html_or_player, dict):
        # Try to extract from player response assets or jsUrl field
        assets = html_or_player.get("assets", {})
        if isinstance(assets, dict):
            js_url = assets.get("js")
            if isinstance(js_url, str) and js_url:
                return _normalize_player_url(js_url)

        # Try jsUrl at top level (common format)
        js_url = html_or_player.get("jsUrl")
        if isinstance(js_url, str) and js_url:
            return _normalize_player_url(js_url)

        # Also check in streamingData or playerConfig
        for key in ("streamingData", "playerConfig", "PLAYER_CONFIG"):
            section = html_or_player.get(key, {})
            if isinstance(section, dict):
                assets = section.get("assets", {})
                if isinstance(assets, dict):
                    js_url = assets.get("js")
                    if isinstance(js_url, str) and js_url:
                        return _normalize_player_url(js_url)

        # Flatten dict to string for regex search
        text = str(html_or_player)
    elif isinstance(html_or_player, str):
        text = html_or_player

    if not text:
        return None

    for pattern in _PLAYER_JS_PATTERNS:
        match = pattern.search(text)
        if match:
            return _normalize_player_url(match.group(1))

    return None


def _normalize_player_url(url: str) -> str:
    """Convert relative player URLs to absolute."""
    url = url.strip()
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.youtube.com{url}"
    return f"https://www.youtube.com/{url}"


def extract_sig_function_name(js_code: str) -> str | None:
    """Extract the name of the signature transformation function from player JS.

    Args:
        js_code: The player JavaScript source code.

    Returns:
        Function name as string, or None if patterns don't match.
    """
    for pattern in _SIG_FUNCTION_PATTERNS:
        match = pattern.search(js_code)
        if match:
            # Return first capture group or the matched function name
            if match.groups():
                return match.group(1)
            # Extract function name from the match
            text = match.group(0)
            name_match = re.search(r'\b([a-zA-Z0-9_$]+)\s*[=:]', text)
            if name_match:
                return name_match.group(1)
    return None


def extract_n_function_name(js_code: str) -> str | None:
    """Extract the name of the n-parameter transformation function from player JS.

    Args:
        js_code: The player JavaScript source code.

    Returns:
        Function name as string, or None if patterns don't match.
    """
    for pattern in _N_FUNCTION_PATTERNS:
        match = pattern.search(js_code)
        if match:
            if match.groups():
                return match.group(1)
            text = match.group(0)
            name_match = re.search(r'\b([a-zA-Z0-9_$]+)\s*[=:]', text)
            if name_match:
                return name_match.group(1)
    return None


def extract_function_with_helpers(js_code: str, func_name: str) -> str | None:
    """Extract a function definition plus any helper objects it depends on.

    Args:
        js_code: The player JavaScript source code.
        func_name: Name of the function to extract.

    Returns:
        JavaScript code containing the function and its dependencies, or None.
    """
    if not func_name or not js_code:
        return None

    # Find the function definition
    # Match function declarations: function name(...) or var name = function(...)
    func_patterns = [
        rf'(?:function\s+{re.escape(func_name)}|var\s+{re.escape(func_name)}\s*=\s*function|{re.escape(func_name)}\s*[=:]\s*function)\s*\([^)]*\)\s*\{{',
        rf'{re.escape(func_name)}\s*:\s*function\s*\([^)]*\)\s*\{{',
    ]

    func_start = None
    for pattern in func_patterns:
        match = re.search(pattern, js_code)
        if match:
            func_start = match.start()
            break

    if func_start is None:
        return None

    # Extract the full function using brace counting
    brace_count = 0
    in_string = None
    escape_next = False
    func_end = None

    for i, char in enumerate(js_code[func_start:]):
        idx = func_start + i

        if escape_next:
            escape_next = False
            continue

        if char == '\\' and in_string:
            escape_next = True
            continue

        if char in '"\'`':
            if in_string is None:
                in_string = char
            elif in_string == char:
                in_string = None
            continue

        if in_string:
            continue

        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                func_end = idx + 1
                break

    if func_end is None:
        return None

    function_code = js_code[func_start:func_end]

    # Find helper dependencies in the function code
    helpers: list[str] = []
    for pattern in _HELPER_PATTERNS:
        for match in pattern.finditer(js_code):
            helper_name = match.group(1)
            # Check if the helper is referenced in our function
            if helper_name in function_code:
                helper_start = match.start()
                # Extract the full helper definition
                helper_end = js_code.find(';', helper_start)
                if helper_end == -1:
                    helper_end = js_code.find(',', helper_start)
                if helper_end == -1:
                    helper_end = helper_start + 500  # Fallback
                helper_code = js_code[helper_start:helper_end + 1]
                helpers.append(helper_code)

    # Combine helpers and function
    if helpers:
        return '\n'.join(helpers) + '\n' + function_code
    return function_code


def build_decipher_js(js_code: str, sig_func_name: str | None = None, n_func_name: str | None = None) -> str:
    """Build a standalone JavaScript snippet for deciphering URLs.

    Args:
        js_code: The player JavaScript source code.
        sig_func_name: Optional known signature function name.
        n_func_name: Optional known n-param function name.

    Returns:
        JavaScript code that exports decipher functions globally.
    """
    sig_name = sig_func_name or extract_sig_function_name(js_code)
    n_name = n_func_name or extract_n_function_name(js_code)

    parts: list[str] = []

    # Add sig function if found
    if sig_name:
        sig_code = extract_function_with_helpers(js_code, sig_name)
        if sig_code:
            parts.append(sig_code)
            parts.append(f'\nif (typeof {sig_name} !== "undefined") {{')
            parts.append(f'    globalThis.ytDecipherSignature = {sig_name};')
            parts.append('}')

    # Add n function if found
    if n_name:
        n_code = extract_function_with_helpers(js_code, n_name)
        if n_code:
            parts.append(n_code)
            parts.append(f'\nif (typeof {n_name} !== "undefined") {{')
            parts.append(f'    globalThis.ytGenerateNParam = {n_name};')
            parts.append('}')

    return '\n'.join(parts)


class PlayerJSCache:
    """Simple in-memory cache for player JS and extracted decipher functions.

    In production, this should be backed by disk cache with TTL based on
    player version (player JS changes ~weekly).
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def get(self, player_url: str) -> dict[str, Any] | None:
        """Get cached player data if available."""
        return self._cache.get(player_url)

    def set(self, player_url: str, data: dict[str, Any]) -> None:
        """Cache player data."""
        self._cache[player_url] = data

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


# Global cache instance
_player_js_cache = PlayerJSCache()


def get_cached_player(player_url: str) -> dict[str, Any] | None:
    """Get cached player JS data."""
    return _player_js_cache.get(player_url)


def cache_player(player_url: str, js_code: str, decipher_js: str | None = None) -> dict[str, Any]:
    """Cache player JS with extracted decipher code."""
    data = {
        "url": player_url,
        "js_code": js_code,
        "decipher_js": decipher_js,
        "sig_func_name": extract_sig_function_name(js_code),
        "n_func_name": extract_n_function_name(js_code),
    }
    _player_js_cache.set(player_url, data)
    return data
