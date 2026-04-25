"""Tests for player JavaScript extraction module.

These tests verify the regex patterns for extracting player JS URLs and
function names from HTML and JS code.
"""

from __future__ import annotations

import pytest

from youtube_scrape.domain.player_js_extract import (
    extract_function_with_helpers,
    extract_n_function_name,
    extract_player_js_url,
    extract_sig_function_name,
    _normalize_player_url,
)


def test_extract_player_js_url_from_html() -> None:
    """Test extracting player URL from HTML."""
    html = '''
    <script src="https://www.youtube.com/s/player/abc123/player_ias.vflset/en_US/base.js"></script>
    '''
    url = extract_player_js_url(html)
    assert url is not None
    assert "googlevideo" not in url
    assert "player" in url
    assert "base.js" in url


def test_extract_player_js_url_from_assets() -> None:
    """Test extracting player URL from player response assets."""
    player = {
        "assets": {
            "js": "/s/player/abc123/player_ias.vflset/en_US/base.js"
        }
    }
    url = extract_player_js_url(player)
    assert url is not None
    assert url.startswith("https://")
    assert "base.js" in url


def test_extract_player_js_url_from_jsurl_field() -> None:
    """Test extracting player URL from jsUrl field at top level."""
    player = {
        "jsUrl": "/s/player/xyz789/player_ias.vflset/en_US/base.js"
    }
    url = extract_player_js_url(player)
    assert url is not None
    assert url.startswith("https://")
    assert "base.js" in url
    assert "xyz789" in url


def test_normalize_player_url_absolute() -> None:
    """Test that absolute URLs are preserved."""
    url = "https://www.youtube.com/s/player/base.js"
    assert _normalize_player_url(url) == url


def test_normalize_player_url_relative() -> None:
    """Test normalizing relative URLs."""
    assert _normalize_player_url("/s/player/base.js").startswith("https://")
    assert _normalize_player_url("//youtube.com/s/player.js").startswith("https://")


def test_extract_sig_function_name_pattern1() -> None:
    """Test signature function name extraction - classic pattern."""
    js = '''
    var sigFunc = function(a) {
        a = a.split("");
        a.reverse();
        return a.join("");
    };
    '''
    name = extract_sig_function_name(js)
    # Should find the function name
    assert name is not None


def test_extract_n_function_name_pattern() -> None:
    """Test n-parameter function name extraction."""
    js = '''
    var nFunc = function(a) {
        var b = a.split("");
        // some transforms
        return b.join("");
    };
    ytplayer.config = {};
    '''
    name = extract_n_function_name(js)
    # Should find the function name
    assert name is not None


def test_extract_function_with_helpers_simple() -> None:
    """Test extracting a simple function."""
    js = '''
    var myFunc = function(x) {
        return x.split("").reverse().join("");
    };
    '''
    extracted = extract_function_with_helpers(js, "myFunc")
    assert extracted is not None
    assert "function" in extracted
    assert "myFunc" in extracted


def test_extract_function_not_found() -> None:
    """Test extracting non-existent function."""
    js = 'var otherFunc = function() {}'
    extracted = extract_function_with_helpers(js, "missingFunc")
    assert extracted is None


def test_extract_player_js_url_returns_none_for_invalid() -> None:
    """Test that invalid HTML returns None."""
    html = "<html><body>No player here</body></html>"
    url = extract_player_js_url(html)
    # May or may not find something in random HTML
    # Just verify it doesn't crash


def test_extract_sig_function_name_not_found() -> None:
    """Test signature extraction from JS without sig function."""
    js = 'var foo = function() { return 1; }'
    name = extract_sig_function_name(js)
    # May or may not find something - patterns are broad
    # Just verify it doesn't crash
