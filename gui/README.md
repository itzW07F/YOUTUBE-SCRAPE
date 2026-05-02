# YouTube Scrape Pro - Electron GUI

A futuristic, professional Electron-based GUI for the YouTube Scraper.

## Features

- **Cross-platform**: Windows, macOS, Linux
- **Modern UI**: React + Tailwind CSS with glassmorphism effects
- **Real-time updates**: WebSocket-based progress streaming
- **Keyboard shortcuts**: Efficient workflow with hotkeys
- **Batch processing**: Queue multiple URLs for processing
- **Dark/Light mode**: Choose your preferred theme

## Architecture

```
Electron App
├── Main Process (Node.js)
│   ├── Python Bridge - Spawns FastAPI server
│   └── IPC Handlers - Native APIs
├── Renderer Process (React)
│   ├── React Components - UI
│   ├── Tailwind CSS - Styling
│   └── Framer Motion - Animations
└── Python Backend (FastAPI)
    ├── Scrape Routes - Video, Comments, Transcripts
    ├── Download Routes - Media download
    ├── Config Routes - Settings management
    └── WebSocket - Real-time progress
```

## Development Setup

### Prerequisites

- Node.js 18+
- Python 3.12 or 3.13
- npm or yarn

### Installation

From the repository root, run the platform setup script:

```bash
./setup.sh --help   # options: --skip-gui, --skip-browser, --skip-os-deps, --skip-audit, --skip-preflight, --min-disk-gib N
./setup.sh
```

Windows: from the repository root, double-click `setup-windows.cmd`, or run:

```powershell
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

The setup script creates `.venv`, syncs Python dependencies from `uv.lock`, downloads Camoufox, and installs GUI dependencies with `npm ci`.

Manual Node dependency install, if needed:

```bash
cd gui
npm ci
```

Run in development mode:

- **Windows:** from the repository root, double-click `start-gui.cmd` (or run `.\start-gui.ps1` in PowerShell).
- **macOS/Linux:** from `gui/` run `npm run dev`.

```bash
cd gui
npm run dev
```

## Build Commands

```bash
# Build for current platform
npm run build

# Build unpack (for testing)
npm run build:unpack

# Build for specific platforms
npm run build:win    # Windows (NSIS installer)
npm run build:mac    # macOS (DMG)
npm run build:linux  # Linux (AppImage)
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + N` | New Scrape |
| `Cmd/Ctrl + J` | Open Jobs |
| `Cmd/Ctrl + R` | Open Results |
| `Cmd/Ctrl + ,` | Open Settings |
| `Cmd/Ctrl + D` | Open Debug |
| `Cmd/Ctrl + Shift + L` | Toggle Theme |
| `Cmd/Ctrl + F` | Search |
| `Esc` | Go Back |

## Project Structure

```
gui/
├── src/
│   ├── main/           # Electron main process
│   │   ├── index.ts    # Entry point
│   │   └── python-bridge.ts
│   ├── preload/        # IPC preload script
│   │   └── index.ts
│   └── renderer/       # React frontend
│       ├── components/ # UI components
│       ├── hooks/      # Custom hooks
│       ├── stores/     # Zustand stores
│       └── styles/     # Tailwind + CSS
├── build/              # Build resources
├── assets/             # Icons, images
└── package.json
```

## API Documentation

The Python FastAPI server exposes these endpoints:

- `GET /health` - Health check
- `POST /scrape/video` - Start video scrape
- `POST /scrape/comments` - Start comments scrape
- `POST /scrape/transcript` - Start transcript scrape
- `POST /download/video` - Download video
- `GET /download/formats` - List available formats
- `GET /config` - Get configuration
- `PUT /config` - Update configuration
- `POST /batch/start` - Start batch job
- `GET /batch/status/{id}` - Get batch status
- `WS /ws/progress/{job_id}` - WebSocket for real-time progress

## License

MIT
