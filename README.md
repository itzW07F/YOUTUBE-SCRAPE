# youtube-scrape

Cross-platform **YouTube scraper** CLI, GUI, and library: yt-dlp for video downloads, Camoufox + Playwright for metadata/scraping (no YouTube Data API), with structured outputs.

**NEW**: Professional Electron GUI with React + Tailwind CSS - [see GUI docs](gui/README.md)

## Prerequisites (pinned for development)

- **Git**: needed to clone the repository.
- **Internet access**: setup downloads Python packages, Electron packages, and the Camoufox browser payload.
- **Node.js 18+ / npm**: setup verifies this and attempts package-manager installation where supported.
- **Python**: managed locally by `uv` from `uv.lock`; supported runtime is `3.12` or `3.13`.

## One-command setup

Linux/macOS:

```bash
./setup.sh
```

Windows (recommended for non-technical users — double-click from File Explorer):

```text
setup-windows.cmd
```

The CMD launcher forces a safe working directory and execution policy, then runs `setup.ps1`. For automation or advanced use:

```powershell
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Useful flags: `-SkipGui`, `-SkipBrowser`, `-SkipPreflight`, `-SkipAudit`, `-MinDiskGiB 8`. Set `SETUP_WINDOWS_NONINTERACTIVE=1` before running `setup-windows.cmd` to skip the end pause (CI/scripts).

The setup scripts create an isolated `.venv`, install Python dependencies from `uv.lock`, download Camoufox with `python -m camoufox fetch`, and install Electron dependencies from `gui/package-lock.json` with `npm ci`. Large generated folders (`.venv/`, `gui/node_modules/`, `gui/out/`, `output/`, browser payloads, packaged installers) are intentionally excluded from GitHub.

**Linux / macOS (`setup.sh`):** prints the same style of **read-only audit** (OS, arch, free space, curl/git/node/uv, resolved Node tarball URL when `curl` + `python3` or `jq` are available), asserts repo files, checks disk + HTTPS to nodejs.org and astral.sh, retries flaky `uv` / `camoufox` / `npm ci` steps, installs `uv`, runs distro packages on Linux (unless `--skip-os-deps`), provisions Node via **apt / dnf / pacman / Homebrew** when possible and otherwise **official Node LTS `.tar.xz`** under `$XDG_DATA_HOME` (or `~/.local/share`), and falls back across Python **3.13** / **3.12** if needed. Flags: `--skip-gui`, `--skip-browser`, `--skip-os-deps`, `--skip-audit`, `--skip-preflight`, `--min-disk-gib N`. See `./setup.sh --help`.

**Windows behavior notes:** `setup.ps1` prints a **read-only environment audit** (OS, architecture, PATH tooling, resolved Node portable URL when online), then checks repo files, free disk space, and HTTPS reachability before large downloads; retries flaky network steps; installs `uv` and Node.js (trying winget, then Chocolatey if present, then a per-user portable Node LTS zip from nodejs.org if neither applies); falls back across Python `3.13` / `3.12` if one toolchain cannot be provisioned. Use `-SkipAudit` to suppress the audit banner.

## Packaging (testers / beta)

From the repository root, on the **same OS** you want to ship for:

```bash
./scripts/package-standalone.sh --help
./scripts/package-standalone.sh
```

- **Linux** (run on Linux): produces an **AppImage** under `gui/dist/` (self-contained GUI + PyInstaller API binary + bundled resources). Re-running clears `gui/dist`, `gui/out`, `build/pyinstaller`, and `gui/resources/{python,camoufox}` by default (use `--no-clean` to skip).
- **Windows** (run from **Git Bash** on Windows): produces an **NSIS installer** `.exe` under `gui/dist/`.
- **macOS**: `./scripts/package-standalone.sh --target mac` builds a **DMG**.

Requirements: `uv`, Node 18+, `npm`; first run downloads **Camoufox** via `uv run python -m camoufox fetch` unless you pass `--skip-camoufox-fetch`. PyInstaller is pulled with `uv run --with pyinstaller==6.16.0` for the API step (no extra line in `pyproject.toml`).

**Note:** “Runs on any computer” is limited by normal desktop constraints (glibc vs musl on Linux, 64-bit, AppImage FUSE on some systems, Windows x64 for the default NSIS target). Cross-compiling Windows installers from Linux is not wired in this script.

## Run

```bash
uv run youtube-scrape --help
# Global flags (timeouts, headless, …) must appear before the subcommand name.

# Download full video (uses yt-dlp automatically)
uv run youtube-scrape download "https://www.youtube.com/watch?v=VIDEO_ID" -o output/video.mp4

# Scrape video metadata
uv run youtube-scrape --browser-timeout 90 video "https://www.youtube.com/watch?v=dYag3jVVfsQ" --out output/video.json

# Download thumbnails
mkdir -p output/thumbs
uv run youtube-scrape --browser-timeout 90 thumbnails "https://www.youtube.com/watch?v=dYag3jVVfsQ" --out-dir output/thumbs --out output/thumbs.json --max 5

# Run ALL enabled scrapes from config (video, comments, transcript, thumbnails, download)
uv run youtube-scrape all "https://www.youtube.com/watch?v=VIDEO_ID" -d ./output
```

GUI:

```bash
./start-gui.sh
```

Windows:

```text
start-gui.cmd
```

or `powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\start-gui.ps1`

## Test

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src/youtube_scrape
uv run pytest
```

Optional browser smoke tests:

```bash
RUN_BROWSER_TESTS=1 uv run pytest -m browser
```

### Live reference test + review output

Hits real YouTube with Camoufox and writes JSON/images under `tests/output/reference/<video_id>/` for manual inspection (generated files are gitignored).

```bash
export RUN_BROWSER_TESTS=1
export RUN_LIVE_REFERENCE_TESTS=1
# Optional: export REFERENCE_VIDEO_URL="https://www.youtube.com/watch?v=..."

uv run pytest -m live_reference tests/test_live_reference_video.py -v
```

See [tests/output/README.md](tests/output/README.md) for the artifact layout.

## Configuration

`youtube-scrape` uses a centralized configuration system. Create a config file as your single source of truth:

```bash
# Copy the example and customize
cp config-example.yaml ~/.config/youtube-scrape/config.yaml
```

### Config File Locations (searched in order):
1. Path specified via `--config` flag
2. `~/.config/youtube-scrape/config.yaml`
3. `~/.config/youtube-scrape/config.json`
4. `./youtube-scrape.yaml` (project root)

### Config Precedence (highest to lowest):
1. CLI arguments (e.g., `--max-comments 50`)
2. Config file values
3. Environment variables (`YOUTUBE_SCRAPE_*`)
4. Built-in defaults

### Example: Minimal Config

```yaml
# ~/.config/youtube-scrape/config.yaml
# Default output directory is "output/" folder
comments:
  max_comments: 100
  include_replies: true

download:
  format: "best"
```

### Example: Archival Profile (Maximum Data)

```yaml
comments:
  enabled: true
  fetch_all: true                    # Get ALL comments
  include_replies: true
  max_replies_per_thread: null     # Unlimited replies

thumbnails:
  enabled: true
  max_variants: null               # All variants

download:
  enabled: true
  format: "best"
  stream: "video"
```

### Example: Smoke Test Profile (Fast)

```yaml
comments:
  enabled: true
  max_comments: 10                 # Just 10 comments
  include_replies: false

thumbnails:
  enabled: true
  max_variants: 1                  # Just 1 thumbnail

transcript:
  enabled: true
  fmt: "txt"

browser:
  headless: true
  timeout_s: 30.0                  # Shorter timeout
```

### Using Profiles

```bash
# Quick smoke test
youtube-scrape --config ./config-smoke.yaml video "..."

# Full archival scrape
youtube-scrape --config ./config-archive.yaml video "..."

# Default config + CLI override
youtube-scrape video "..." --max-comments 500
```

See `config-example.yaml` for all available options.

## Video Download

Download full videos using **yt-dlp** (bundled as a Python dependency):

```bash
# Download best quality video (muxed audio+video)
youtube-scrape download "https://www.youtube.com/watch?v=VIDEO_ID" -o output/video.mp4

# Download specific format
youtube-scrape download "https://www.youtube.com/watch?v=VIDEO_ID" -o output/video.mp4 --format 18

# Download audio only (m4a/webm container)
youtube-scrape download "https://www.youtube.com/watch?v=VIDEO_ID" -o output/audio.m4a --stream audio

# Download audio and transcode to MP3
youtube-scrape download "https://www.youtube.com/watch?v=VIDEO_ID" -o output/audio.mp3 --stream audio --audio-encoding mp3
```

### How it works

1. **Primary**: Uses `yt-dlp` Python API for reliable full-file downloads
   - Handles JavaScript challenge solving (n-parameter and signature deciphering)
   - Browser impersonation (TLS fingerprinting, headers)
   - Multi-client API strategy (android_vr, web_safari, etc.)
   - DASH/HLS stream downloading with proper authentication

2. **Fallback**: Experimental browser-based capture (audio/MP3 only when yt-dlp fails)
   - Uses Camoufox to capture media from browser playback
   - Produces ~22 second clips due to YouTube player buffer limitations
   - UMP format wrapping may result in playback issues
   - Only used for audio/MP3 extraction when yt-dlp is unavailable

### Architecture

```
┌─────────────────┐
│   CLI Download  │
└────────┬────────┘
         │
    ┌────┴──────────┐
    │               │
    ▼               ▼ (audio/MP3 only, on failure)
┌─────────┐   ┌──────────────────┐
│ yt-dlp  │   │ Experimental     │
│ (Python)│   │ Browser Capture  │
└─────────┘   └──────────────────┘
```

## All-in-One Scrape (`all` command)

The `all` command runs **all enabled scrapes** from your config file in a single operation:

```bash
# Scrape everything enabled in config
youtube-scrape all "https://www.youtube.com/watch?v=VIDEO_ID" -d ./output

# With custom config file
youtube-scrape --config ./archive.yaml all "..." -d ./my-archive
```

### Config-Based Operation

What gets scraped depends on your config file settings:

```yaml
# config-archive.yaml - Archive everything
video:
  enabled: true
comments:
  enabled: true
  fetch_all: true
  include_replies: true
transcript:
  enabled: true
  fmt: "json"
thumbnails:
  enabled: true
download:
  enabled: true
  format: "best"
```

### Output Structure

```
./output/
├── summary.json          # Summary of all operations
├── video.json            # Video metadata
├── comments.json         # Comments data
├── transcript.txt        # Caption transcript
├── thumbnails/           # Thumbnail images
│   ├── maxresdefault.jpg
│   ├── hqdefault.jpg
│   └── ...
└── VIDEO_ID.mp4          # Downloaded video (if enabled)
```

### Benefits

- **Single command** for complete archival
- **Respects config** - only runs enabled operations
- **Efficient** - reuses browser session across operations
- **Organized** - consistent output structure

## GUI (Electron + React)

A futuristic, professional GUI is now available:

```bash
cd gui
npm ci
npm run dev    # Development mode
npm run build  # Build for distribution
```

**GUI Features:**
- Cross-platform: Windows, macOS, Linux
- Modern React UI with Tailwind CSS + glassmorphism
- Real-time progress via WebSocket
- Batch processing with drag-and-drop
- Keyboard shortcuts (Cmd/Ctrl + N for new scrape, etc.)
- Dark/Light mode toggle

See [gui/README.md](gui/README.md) for full documentation.

## Documentation

- Architecture: [Documentation/architecture.md](Documentation/architecture.md)
- ADRs: [Documentation/adr/](Documentation/adr/)
- GUI: [gui/README.md](gui/README.md)

## Legal

Operators are responsible for compliance with YouTube terms and applicable law. This repository is a technical toolkit only.
