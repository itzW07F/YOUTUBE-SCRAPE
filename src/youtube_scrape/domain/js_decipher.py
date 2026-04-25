"""Execute YouTube signature/n-parameter deciphering via Node.js subprocess.

This module provides a sandboxed JavaScript execution environment for running
YouTube's player JS signature transforms. It uses Node.js subprocess for isolation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlencode, urlunparse

from youtube_scrape.domain.player_js_extract import (
    build_decipher_js,
    cache_player,
    extract_n_function_name,
    extract_player_js_url,
    extract_sig_function_name,
    get_cached_player,
)
from youtube_scrape.exceptions import YouTubeScrapeError

log = logging.getLogger(__name__)

# Node.js wrapper script template - decipher code file path inserted at runtime
_NODE_WRAPPER_TEMPLATE = '''
const readline = require('readline');
const fs = require('fs');

// Polyfill minimal browser globals that player JS might expect
const window = globalThis;
const document = { createElement: () => ({}), documentElement: {}, body: {}, head: {} };
const navigator = { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', language: 'en-US', platform: 'Win32' };
const location = { href: 'https://www.youtube.com/watch', hostname: 'www.youtube.com', host: 'www.youtube.com', protocol: 'https:', port: '', pathname: '/watch', search: '', hash: '' };
const console = { log: () => {}, error: () => {}, warn: () => {}, debug: () => {} };
const localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const sessionStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

// Load the decipher code from file
let decipherLoaded = false;
try {
    const decipherPath = process.env.YT_DECIPHER_JS_PATH || '';
    if (decipherPath && fs.existsSync(decipherPath)) {
        const decipherCode = fs.readFileSync(decipherPath, 'utf8');
        if (decipherCode) {
            eval(decipherCode);
            decipherLoaded = true;
        }
    }
} catch (e) {
    console.error('Failed to load decipher code:', e.message);
}

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false
});

function processRequest(req) {
    try {
        if (req.action === 'decipher_signature') {
            const sig = req.signature;
            if (typeof ytDecipherSignature === 'function') {
                const result = ytDecipherSignature(sig);
                return { success: true, result };
            }
            return { success: false, error: 'ytDecipherSignature not available' };
        }

        if (req.action === 'generate_n_param') {
            const n = req.n_param;
            if (typeof ytGenerateNParam === 'function') {
                const result = ytGenerateNParam(n);
                return { success: true, result };
            }
            return { success: false, error: 'ytGenerateNParam not available' };
        }

        if (req.action === 'decipher_url') {
            let url = req.url;
            const sigMatch = url.match(/[?&]s=([^&]+)/);
            const nMatch = url.match(/[?&]n=([^&]+)/);

            if (sigMatch && typeof ytDecipherSignature === 'function') {
                const sig = decodeURIComponent(sigMatch[1]);
                const deciphered = ytDecipherSignature(sig);
                url = url.replace(/([?&])s=([^&]+)/, `$1sig=${encodeURIComponent(deciphered)}`);
            }

            if (nMatch && typeof ytGenerateNParam === 'function') {
                const n = decodeURIComponent(nMatch[1]);
                const newN = ytGenerateNParam(n);
                url = url.replace(/([?&])n=([^&]+)/, `$1n=${encodeURIComponent(newN)}`);
            }

            return { success: true, result: url };
        }

        return { success: false, error: 'Unknown action: ' + req.action };
    } catch (e) {
        return { success: false, error: e.message, stack: e.stack };
    }
}

rl.on('line', (line) => {
    try {
        const req = JSON.parse(line);
        const resp = processRequest(req);
        console.log(JSON.stringify(resp));
    } catch (e) {
        console.log(JSON.stringify({ success: false, error: 'Invalid JSON: ' + e.message }));
    }
});
'''


def _resolve_nodejs() -> str | None:
    """Find Node.js executable on PATH."""
    for name in ("node", "nodejs"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _check_nodejs_available() -> bool:
    """Check if Node.js is available and working."""
    node = _resolve_nodejs()
    if not node:
        return False
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0 and result.stdout.strip().startswith("v")
    except Exception:
        return False


class JSDecipherError(YouTubeScrapeError):
    """Raised when JavaScript deciphering fails."""
    pass


class NodeJSDecipherer:
    """Node.js-based JavaScript deciphering for YouTube signatures.

    Uses command-line arguments instead of stdin/stdout RPC for reliability.
    """

    def __init__(self) -> None:
        self._node_path: str | None = _resolve_nodejs()

    def is_available(self) -> bool:
        """Check if Node.js is available for deciphering."""
        return self._node_path is not None and _check_nodejs_available()

    def _run_js_operation(self, decipher_js: str, operation: str, input_value: str) -> str:
        """Run a decipher operation in Node.js.

        Args:
            decipher_js: The decipher JavaScript code.
            operation: 'sig' or 'n'.
            input_value: The value to transform.

        Returns:
            Transformed value.
        """
        if not self._node_path:
            raise JSDecipherError("Node.js not available")

        # Build script that performs the operation
        script = f"""
const window = globalThis;
const document = {{ createElement: () => ({{}}), documentElement: {{}} }};
const navigator = {{ userAgent: 'Mozilla/5.0', language: 'en-US' }};
const location = {{ href: 'https://www.youtube.com/watch', hostname: 'www.youtube.com' }};

{decipher_js}

const operation = '{operation}';
const inputValue = process.argv[2];

let result;
if (operation === 'sig' && typeof ytDecipherSignature === 'function') {{
    result = ytDecipherSignature(inputValue);
}} else if (operation === 'n' && typeof ytGenerateNParam === 'function') {{
    result = ytGenerateNParam(inputValue);
}} else {{
    console.error('Operation not available:', operation);
    process.exit(1);
}}

console.log(JSON.stringify({{ success: true, result }}));
"""

        # Write script to temp file
        fd, script_path = tempfile.mkstemp(suffix=".js", prefix="yt_decipher_")
        with open(fd, "w") as f:
            f.write(script)

        try:
            # Run Node.js with the input value as argument
            result = subprocess.run(
                [self._node_path, script_path, input_value],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                raise JSDecipherError(f"Node.js error: {result.stderr[:200]}")

            # Parse result
            try:
                output = json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                raise JSDecipherError(f"Invalid output: {result.stdout[:200]}")

            if not output.get("success"):
                raise JSDecipherError(f"Operation failed: {output.get('error', 'Unknown')}")

            return output["result"]

        finally:
            # Cleanup
            try:
                os.unlink(script_path)
            except Exception:
                pass

    def decipher_signature(self, signature: str, decipher_js: str) -> str:
        """Decipher a YouTube signature using the player JS."""
        if not decipher_js:
            raise JSDecipherError("No decipher JS provided")
        return self._run_js_operation(decipher_js, "sig", signature)

    def generate_n_param(self, n_param: str, decipher_js: str) -> str:
        """Generate a new n-parameter token using the player JS."""
        if not decipher_js:
            raise JSDecipherError("No decipher JS provided")
        return self._run_js_operation(decipher_js, "n", n_param)

    def decipher_url(self, cipher_url: str, decipher_js: str) -> str:
        """Fully decipher a ciphered YouTube URL (sig + n-param)."""
        # Parse and apply transforms
        from youtube_scrape.domain.js_decipher import parse_cipher_components, apply_sig_to_url, apply_n_param_to_url

        components = parse_cipher_components(cipher_url)
        result_url = components.get("url", "")

        if "s" in components:
            deciphered_sig = self.decipher_signature(components["s"], decipher_js)
            result_url = apply_sig_to_url(result_url, deciphered_sig, components.get("sp", "sig"))

        if "n" in components:
            new_n = self.generate_n_param(components["n"], decipher_js)
            result_url = apply_n_param_to_url(result_url, new_n)

        return result_url

    def close(self) -> None:
        """No-op for compatibility."""
        pass

    def __enter__(self) -> NodeJSDecipherer:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# Global decipherer instance (lazy-initialized)
_decipherer: NodeJSDecipherer | None = None


def _get_decipherer() -> NodeJSDecipherer:
    """Get or create the global decipherer instance."""
    global _decipherer
    if _decipherer is None:
        _decipherer = NodeJSDecipherer()
    return _decipherer


def is_decipher_available() -> bool:
    """Check if Node.js deciphering is available."""
    return _get_decipherer().is_available()


def parse_cipher_components(cipher_string: str) -> dict[str, str]:
    """Parse a signatureCipher string into components.

    Args:
        cipher_string: The signatureCipher value from streamingData.

    Returns:
        Dict with 'url', 's' (signature), 'sp' (sig param), 'n' (n-param) keys.
    """
    # Decode the cipher string
    from urllib.parse import unquote

    decoded = unquote(cipher_string.replace("+", " "))
    parts: dict[str, str] = {}

    # Extract url parameter
    url_match = re.search(r'[?&]url=([^&]+)', decoded)
    if url_match:
        parts["url"] = unquote(url_match.group(1))

    # Extract signature (s parameter)
    sig_match = re.search(r'[?&]s=([^&]+)', decoded)
    if sig_match:
        parts["s"] = unquote(sig_match.group(1))

    # Extract signature parameter name (sp)
    sp_match = re.search(r'[?&]sp=([^&]+)', decoded)
    if sp_match:
        parts["sp"] = unquote(sp_match.group(1))
    else:
        parts["sp"] = "sig"  # Default

    # Extract n parameter (throttling param)
    n_match = re.search(r'[?&]n=([^&]+)', decoded)
    if n_match:
        parts["n"] = unquote(n_match.group(1))

    return parts


def apply_sig_to_url(base_url: str, signature: str, sig_param: str = "sig") -> str:
    """Apply a deciphered signature to a URL.

    Args:
        base_url: The base URL from cipher (before deciphering).
        signature: The deciphered signature string.
        sig_param: The parameter name to use (usually 'sig' or 'signature').

    Returns:
        URL with signature parameter added.
    """
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query, keep_blank_values=True)

    # Add the deciphered signature
    qs[sig_param] = [signature]

    # Rebuild URL
    new_query = urlencode(qs, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))


def apply_n_param_to_url(url: str, n_param: str) -> str:
    """Apply a new n-parameter to a URL.

    Args:
        url: The URL (may already have n parameter).
        n_param: The new n parameter value.

    Returns:
        URL with n parameter updated.
    """
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)

    qs["n"] = [n_param]

    new_query = urlencode(qs, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))


def _extract_function_code(js_code: str, func_name: str) -> str | None:
    """Extract a single function definition from player JS.

    Uses regex to find the function and brace counting to extract the full body.
    """
    import re

    # Find function definition - support various patterns
    patterns = [
        rf'{re.escape(func_name)}=function\([^)]*\)\{{',
        rf'var\s+{re.escape(func_name)}=function\([^)]*\)\{{',
        rf'const\s+{re.escape(func_name)}=function\([^)]*\)\{{',
        rf'function\s+{re.escape(func_name)}\([^)]*\)\{{',
    ]

    func_start = None
    for pattern in patterns:
        match = re.search(pattern, js_code)
        if match:
            func_start = match.start()
            break

    if func_start is None:
        return None

    # Find the opening brace
    brace_start = js_code.find('{', func_start)
    if brace_start == -1:
        return None

    # Brace counting to find the end
    brace_count = 1
    in_string = None
    escape_next = False

    for i in range(brace_start + 1, len(js_code)):
        char = js_code[i]

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
                # Include 'var/const/let name=' prefix if present
                prefix_start = func_start
                # Check if there's a variable declaration before the function
                prefix_match = re.search(r'(?:var|const|let)\s+' + re.escape(func_name) + r'\s*=$', js_code[max(0, func_start-50):func_start])
                if prefix_match:
                    prefix_start = func_start - 50 + prefix_match.start()
                    # Skip whitespace before the prefix
                    while prefix_start > 0 and js_code[prefix_start] in (' ', '\t', '\n'):
                        prefix_start -= 1
                    prefix_start = max(0, prefix_start - 5)  # Give some buffer

                return js_code[prefix_start:i+1]

    return None


async def decipher_format_url(
    format_dict: dict[str, Any],
    player_js_code: str,
) -> str | None:
    """Decipher a format's URL if it has cipher, otherwise return plain URL.

    Args:
        format_dict: The format dict from streamingData (may have cipher).
        player_js_code: The player JavaScript source code.

    Returns:
        Deciphered URL ready for fetching, or None if unavailable.
    """
    # Check for plain URL first
    plain_url = format_dict.get("url")
    if isinstance(plain_url, str) and plain_url.strip():
        # For plain URLs, just return them (n-param refresh is optional)
        return plain_url

    # Handle ciphered URL
    cipher = format_dict.get("signatureCipher") or format_dict.get("cipher")
    if not isinstance(cipher, str) or not cipher.strip():
        return None

    if not is_decipher_available():
        log.warning("cipher_url_but_nodejs_unavailable")
        return None

    try:
        components = parse_cipher_components(cipher)
        base_url = components.get("url")
        if not base_url:
            log.warning("decipher_no_base_url_in_cipher")
            return None

        # Extract function names from player JS
        sig_func_name = extract_sig_function_name(player_js_code)
        n_func_name = extract_n_function_name(player_js_code)

        log.debug("decipher_functions", extra={"sig": sig_func_name, "n": n_func_name})

        if not sig_func_name and not n_func_name:
            log.warning("decipher_no_functions_found")
            return None

        # Build decipher JS by extracting just the function code
        decipher_js_parts = ["// Extracted decipher functions"]

        # Add minimal polyfills
        decipher_js_parts.append("""
const window = globalThis;
const document = { createElement: () => ({}), documentElement: {} };
const navigator = { userAgent: 'Mozilla/5.0', language: 'en-US' };
const location = { href: 'https://www.youtube.com/watch', hostname: 'www.youtube.com' };
""")

        # Extract and add the decipher functions (much faster than full player JS)
        if sig_func_name:
            sig_code = _extract_function_code(player_js_code, sig_func_name)
            if sig_code:
                decipher_js_parts.append(f"// Signature function: {sig_func_name}")
                decipher_js_parts.append(sig_code)
                decipher_js_parts.append(f"globalThis.ytDecipherSignature = {sig_func_name};")
            else:
                log.warning("decipher_sig_extract_failed", extra={"func": sig_func_name})

        if n_func_name:
            n_code = _extract_function_code(player_js_code, n_func_name)
            if n_code:
                decipher_js_parts.append(f"// N-param function: {n_func_name}")
                decipher_js_parts.append(n_code)
                decipher_js_parts.append(f"globalThis.ytGenerateNParam = {n_func_name};")
            else:
                log.warning("decipher_n_extract_failed", extra={"func": n_func_name})

        decipher_js = "\n".join(decipher_js_parts)

        with _get_decipherer() as decipherer:
            result_url = base_url

            # Apply signature decipher if present
            if "s" in components and sig_func_name:
                try:
                    deciphered_sig = decipherer.decipher_signature(components["s"], decipher_js)
                    result_url = apply_sig_to_url(result_url, deciphered_sig, components.get("sp", "sig"))
                except Exception as e:
                    log.warning("decipher_sig_failed", extra={"error": str(e)})
                    # Continue anyway - maybe n-param is enough

            # Apply n-param generation if present
            if "n" in components and n_func_name:
                try:
                    new_n = decipherer.generate_n_param(components["n"], decipher_js)
                    result_url = apply_n_param_to_url(result_url, new_n)
                except Exception as e:
                    log.warning("decipher_n_failed", extra={"error": str(e)})

        return result_url

    except Exception as e:
        log.warning("decipher_format_url_failed", extra={"error": str(e)})
        return None


def close_global_decipherer() -> None:
    """Clean up the global decipherer instance."""
    global _decipherer
    if _decipherer:
        _decipherer.close()
        _decipherer = None
