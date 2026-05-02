#!/usr/bin/env bash
# Build self-contained distributables (Electron + PyInstaller API + Camoufox payload).
# - Linux (on Linux): AppImage under gui/dist/
# - Windows (on Windows Git Bash/MSYS): NSIS installer .exe under gui/dist/
# - macOS (on macOS): DMG under gui/dist/
#
# Cross-building Windows installers from Linux is not supported here (needs Wine/CI).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET=""
SKIP_CLEAN=0
SKIP_CAMOUFOX=0
PYINSTALLER_VERSION="6.16.0"

log() { printf '\n==> %s\n' "$1"; }
warn() { printf 'WARN: %s\n' "$1" >&2; }
die() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

usage() {
  cat <<'EOF'
Build self-contained distributables (Electron + PyInstaller API + Camoufox).

Usage: ./scripts/package-standalone.sh [options]

  --target linux|windows|mac   Artifact (default: detect host OS)
  --no-clean                   Keep gui/out, gui/dist, pyinstaller work dirs
  --skip-camoufox-fetch        Skip "uv run python -m camoufox fetch"

Windows installers must be built on Windows. Linux AppImage on Linux (recommended).
EOF
}

host_family() {
  case "$(uname -s)" in
    Linux*) echo linux ;;
    Darwin*) echo mac ;;
    MINGW* | MSYS* | CYGWIN*) echo windows ;;
    *) echo unknown ;;
  esac
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --target=*)
      TARGET="${1#*=}"
      ;;
    --target)
      TARGET="${2:?}"
      shift
      ;;
    --no-clean) SKIP_CLEAN=1 ;;
    --skip-camoufox-fetch) SKIP_CAMOUFOX=1 ;;
    *) die "Unknown option: $1 (use --help)" ;;
  esac
  shift
done

[[ -n "$TARGET" ]] || TARGET="$(host_family)"
[[ "$TARGET" != unknown ]] || die "Could not detect OS; pass --target linux|windows|mac"

if [[ "$TARGET" == windows ]]; then
  case "$(host_family)" in
    windows) ;;
    *) die "Windows installer must be built on Windows (Git Bash / PowerShell). Detected host: $(host_family)." ;;
  esac
fi

if [[ "$TARGET" == linux ]]; then
  case "$(host_family)" in
    linux) ;;
    *)
      warn "Linux AppImage builds are intended to run on Linux hosts (you are on $(host_family))."
      warn "Continuing anyway; electron-builder may fail without a Linux toolchain."
      ;;
  esac
fi

clean_artifacts() {
  [[ "$SKIP_CLEAN" -eq 0 ]] || return 0
  log "Cleaning previous packaging outputs"
  rm -rf "$ROOT/gui/dist" "$ROOT/gui/out" "$ROOT/build/pyinstaller"
  mkdir -p "$ROOT/gui/resources/python" "$ROOT/gui/resources/camoufox" "$ROOT/output"
  find "$ROOT/gui/resources/python" -mindepth 1 -delete 2>/dev/null || true
  find "$ROOT/gui/resources/camoufox" -mindepth 1 -delete 2>/dev/null || true
}

ensure_node() {
  command -v node >/dev/null 2>&1 || die "node is not on PATH"
  command -v npm >/dev/null 2>&1 || die "npm is not on PATH"
}

run_gui_install_and_vite_build() {
  log "Installing GUI dependencies (npm ci)"
  (cd "$ROOT/gui" && npm ci)
  log "electron-vite production build"
  (cd "$ROOT/gui" && npm run build)
}

run_pyinstaller_bundle() {
  log "PyInstaller API bundle + Camoufox copy (scripts/build-python.py)"
  uv run --with "pyinstaller==${PYINSTALLER_VERSION}" python "$ROOT/scripts/build-python.py"
}

fetch_camoufox_if_needed() {
  [[ "$SKIP_CAMOUFOX" -eq 0 ]] || return 0
  log "Fetching Camoufox payload (large)"
  (cd "$ROOT" && uv run python -m camoufox fetch)
}

run_electron_builder() {
  case "$TARGET" in
    linux)
      log "electron-builder: Linux AppImage"
      (cd "$ROOT/gui" && npx electron-builder --linux AppImage)
      ;;
    windows)
      log "electron-builder: Windows NSIS (x64)"
      (cd "$ROOT/gui" && npx electron-builder --win nsis --x64)
      ;;
    mac)
      log "electron-builder: macOS DMG (arm64 + x64)"
      (cd "$ROOT/gui" && npx electron-builder --mac dmg)
      ;;
    *) die "Internal: bad target $TARGET" ;;
  esac
}

summarize_output() {
  log "Artifacts under $ROOT/gui/dist/:"
  if [[ -d "$ROOT/gui/dist" ]]; then
    ls -la "$ROOT/gui/dist" || true
  else
    warn "gui/dist missing — build may have failed."
  fi
}

# --- main ---
clean_artifacts
ensure_node

command -v uv >/dev/null 2>&1 || die "uv is not on PATH (install from https://docs.astral.sh/uv/)"
log "Ensuring Python env is synced (uv sync)"
uv sync --extra dev

fetch_camoufox_if_needed
run_pyinstaller_bundle
run_gui_install_and_vite_build
run_electron_builder
summarize_output

log "Packaging complete. Ship files from gui/dist/ for your testers."
