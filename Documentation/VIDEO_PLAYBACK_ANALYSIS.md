# Video Playback Issue Analysis & Solution

## Summary

The unplayable `clip.mp4` was caused by incomplete DASH fragment capture - the file contained only initialization segments without proper media data assembly. This document explains why it happened and the implemented solution.

## Root Cause Analysis

### 1. File Structure Diagnosis

The output file `out/clip.mp4` (4MB) had this structure:

```
00000000  00 00 00 1c 66 74 79 70  64 61 73 68 00 00 00 00  |....ftypdash....|
00000010  69 73 6f 36 61 76 30 31  6d 70 34 31 00 00 02 a0  |iso6av01mp41....|
00000020  6d 6f 6f 76 00 00 00 6c  6d 76 68 64 00 00 00 00  |moov...lmvhd....|
```

**Problem**: The file starts with `ftypdash` (DASH format), not `ftypmp42` (progressive MP4).

**What this means**:
- DASH streams use **fragmented MP4** (fMP4) format
- Structure: `ftyp` → `moov` → `[moof` → `mdat]` × N (repeating fragments)
- The captured file had the init segment (`ftyp` + `moov`) but incomplete fragment assembly
- Most players (VLC, QuickTime) cannot play DASH fMP4 directly without a DASH manifest or proper initialization

### 2. Why Direct URL Fetch Failed

From `clip.network-debug.json`:

```json
{
  "events": [
    {
      "phase": "media_route_non_ok",
      "status": 403,
      "url": "https://rr1---sn-q4fl6n6z.googlevideo.com/videoplayback?..."
    },
    {
      "phase": "cipher_playback_only",
      "note": "n/sig handled by the embedded player; bare GET to parsed url often 403"
    }
  ]
}
```

**The 403 errors occurred because**:
1. YouTube returned `signatureCipher` instead of plain URLs
2. The URLs had obfuscated `s=` (signature) and `n=` (throttling) parameters
3. These parameters must be **deciphered using YouTube's player JS** before the URL becomes valid
4. Without deciphering, Google Video servers return 403 Forbidden

### 3. yt-dlp vs Our Original Implementation

| Capability | yt-dlp | Original youtube-scrape |
|------------|--------|------------------------|
| Extract player JS | ✅ | ❌ |
| Extract `sig` function | ✅ | ❌ |
| Extract `n` function | ✅ | ❌ |
| Execute JS transforms | ✅ (embedded JS) | ❌ |
| Decipher URLs | ✅ | ❌ |
| Direct HTTP download | ✅ | ❌ (fallback to capture) |
| DASH fragment assembly | ✅ | ⚠️ Partial |

## Implemented Solution

### New Components

#### 1. `player_js_extract.py` - Player JS Extraction

Extracts YouTube player JavaScript from watch pages and extracts deciphering functions:

```python
# Extract player base.js URL from watch page HTML
player_js_url = extract_player_js_url(html)
# Result: "https://www.youtube.com/s/player/abc123/player_ias.vflset/en_US/base.js"

# Extract signature function name from JS
sig_func_name = extract_sig_function_name(js_code)
# Result: "sigFunc" (actual name varies by player version)

# Extract n-parameter function name
n_func_name = extract_n_function_name(js_code)
# Result: "nFunc" (actual name varies by player version)

# Build standalone decipher JS
decipher_js = build_decipher_js(js_code)
# Result: JavaScript code that exports global decipher functions
```

#### 2. `js_decipher.py` - Node.js Deciphering Engine

Executes the extracted player JS in a Node.js subprocess:

```python
# Check if Node.js is available
is_decipher_available()  # True if node on PATH

# Decipher a signature
with NodeJSDecipherer() as decipherer:
    deciphered_sig = decipherer.decipher_signature(
        "OBFUSCATEDSIG==",
        decipher_js
    )
    # Result: "DECIPHEREDSIGNATURE"

# Generate new n-parameter
new_n = decipherer.generate_n_param("OLDNPARAM", decipher_js)
# Result: "NEWNTOKEN"

# Full URL deciphering
deciphered_url = decipherer.decipher_url(cipher_url, decipher_js)
# Result: Valid googlevideo URL with sig and n parameters fixed
```

#### 3. Integration in `download_media.py`

Modified download flow now attempts deciphering before playback capture:

```python
# NEW: Try Node.js deciphering if ciphered and Node.js available
if cipher_playback_only and is_decipher_available():
    player_js_url = extract_player_js_url(player)
    # Fetch player JS via browser
    player_js = await cam.fetch_text_in_watch_context(url, player_js_url)
    decipher_js = build_decipher_js(player_js)

    # Decipher the format URL
    deciphered = await asyncio.to_thread(
        decipher_format_url, chosen, player_js
    )
    if deciphered:
        media_url = deciphered
        cipher_playback_only = False  # Success!

# FALLBACK: If deciphering failed or Node.js unavailable
if not media_url:
    if cipher_playback_only:
        # Use browser playback capture
        media_url = googlevideo_url_hint(chosen)
    else:
        media_url = chosen.get("url")
```

### Architecture Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  DownloadMediaService.download()                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. Load watch page with Camoufox                                 │
│     → Extract player response + HTML                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Select format from streamingData                              │
│     → Check if ciphered (signatureCipher field)                 │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌─────────────────────────┐    ┌──────────────────────────────┐
│  Plain URL              │    │  Ciphered URL                 │
│  (use directly)         │    │  (needs deciphering)          │
└─────────────────────────┘    └──────────────────────────────┘
                                              │
                                              ▼
                    ┌──────────────────────────────────────────────┐
                    │  3. Extract player JS URL from page            │
                    │  4. Fetch player base.js via browser            │
                    │  5. Extract sig/n functions                   │
                    │  6. Build decipher JS                          │
                    │  7. Execute in Node.js subprocess              │
                    │  8. Get deciphered URL                          │
                    └──────────────────────────────────────────────┘
                                              │
                              ┌───────────────┴───────────────┐
                              │                               │
                              ▼                               ▼
                    ┌─────────────────┐    ┌──────────────────────────┐
                    │  Decipher Success │    │  Decipher Failed/No Node │
                    │  → Direct HTTP GET │    │  → Browser playback capture│
                    └─────────────────┘    └──────────────────────────┘
```

## Usage

### With Node.js (Recommended)

```bash
# Install Node.js first
sudo apt install nodejs  # Ubuntu/Debian
# or
brew install node        # macOS

# Download with experimental flag
youtube-scrape download "https://www.youtube.com/watch?v=VIDEO_ID" \
  --experimental-download \
  -o out/video.mp4
```

### Without Node.js

Still works, but falls back to browser playback capture:

```bash
youtube-scrape download "https://www.youtube.com/watch?v=VIDEO_ID" \
  --experimental-download \
  -o out/video.mp4
# Will see: "cipher_playback_only" in logs
# May capture shorter fragments
```

## Testing

New test coverage:

```bash
# Test cipher parsing
pytest tests/test_js_decipher.py -v

# Test player JS extraction
pytest tests/test_player_js_extract.py -v

# All tests
pytest tests/ -v
```

## Remaining Work

To achieve full yt-dlp parity, these items are pending:

1. **UMP Format Unwrapping**: YouTube's `application/vnd.yt-ump` format wraps DASH fragments. We accept it but don't properly unwrap to plain fMP4.

2. **Proper DASH Fragment Assembly**: Currently best-effort; should implement full DASH manifest parsing and ordered fragment assembly.

3. **Adaptive Stream Support**: Currently focused on progressive formats; full adaptive (separate audio/video) DASH support needs implementation.

4. **Player JS Caching**: Cache decipher code by player version (changes ~weekly) to avoid re-fetching.

## Compliance Checklist

- [x] Tests updated (`test_js_decipher.py`, `test_player_js_extract.py`)
- [x] README updated (Node.js prerequisite documented)
- [x] No external dependencies added (Node.js is optional)
- [x] Fallback behavior preserved (works without Node.js)
- [x] Domain logic properly separated (player_js_extract, js_decipher)
- [x] Integration complete (download_media.py uses new modules)
