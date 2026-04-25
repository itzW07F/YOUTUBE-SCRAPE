#!/usr/bin/env bash
# Bootstrap a local development/runtime environment on Linux and macOS.
set -euo pipefail

readonly PYTHON_VERSION="${PYTHON_VERSION:-3.13}"
readonly MIN_NODE_MAJOR=18
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly GUI_DIR="$ROOT_DIR/gui"

SKIP_GUI=0
SKIP_BROWSER=0
SKIP_OS_DEPS=0

log() {
  printf '\n==> %s\n' "$1"
}

warn() {
  printf 'WARN: %s\n' "$1" >&2
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

has_command() {
  command -v "$1" >/dev/null 2>&1
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-gui)
        SKIP_GUI=1
        ;;
      --skip-browser)
        SKIP_BROWSER=1
        ;;
      --skip-os-deps)
        SKIP_OS_DEPS=1
        ;;
      -h|--help)
        printf 'Usage: ./setup.sh [--skip-gui] [--skip-browser] [--skip-os-deps]\n'
        exit 0
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
    shift
  done
}

ensure_uv() {
  if has_command uv; then
    return
  fi

  has_command curl || die "curl is required to install uv. Install curl, then rerun setup.sh."

  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

  has_command uv || die "uv installed, but it is not on PATH. Open a new terminal and rerun setup.sh."
}

install_linux_os_deps() {
  [[ "$SKIP_OS_DEPS" -eq 0 ]] || return

  if has_command apt-get; then
    log "Installing Linux browser/media system packages"
    sudo apt-get update
    sudo apt-get install -y \
      ca-certificates curl ffmpeg fonts-liberation \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2 || warn "Some OS packages were not installed; Camoufox may report missing libraries."
    return
  fi

  if has_command dnf; then
    log "Installing Linux browser/media system packages"
    sudo dnf install -y nodejs npm ffmpeg nss atk at-spi2-atk cups-libs libdrm \
      libxkbcommon libXcomposite libXdamage libXfixes libXrandr mesa-libgbm alsa-lib \
      || warn "Some OS packages were not installed; Camoufox may report missing libraries."
    return
  fi

  if has_command pacman; then
    log "Installing Linux browser/media system packages"
    sudo pacman -Sy --needed --noconfirm nodejs npm ffmpeg nss atk at-spi2-atk cups \
      libdrm libxkbcommon libxcomposite libxdamage libxfixes libxrandr mesa alsa-lib \
      || warn "Some OS packages were not installed; Camoufox may report missing libraries."
    return
  fi

  warn "Unsupported Linux package manager. Rerun Camoufox if it reports missing system libraries."
}

install_node_if_possible() {
  case "$(uname -s)" in
    Darwin)
      has_command brew || die "Node.js $MIN_NODE_MAJOR+ is required. Install Homebrew or Node.js, then rerun setup.sh."
      log "Installing Node.js with Homebrew"
      brew install node || brew upgrade node || true
      ;;
    Linux)
      if has_command apt-get; then
        log "Installing Node.js/npm with apt"
        sudo apt-get update
        sudo apt-get install -y nodejs npm
      elif has_command dnf; then
        log "Installing Node.js/npm with dnf"
        sudo dnf install -y nodejs npm
      elif has_command pacman; then
        log "Installing Node.js/npm with pacman"
        sudo pacman -Sy --needed --noconfirm nodejs npm
      else
        die "Node.js $MIN_NODE_MAJOR+ and npm are required. Install them, then rerun setup.sh."
      fi
      ;;
    *)
      die "Unsupported OS for setup.sh. Use setup.ps1 on Windows."
      ;;
  esac
}

ensure_node() {
  if ! has_command node || ! has_command npm; then
    install_node_if_possible
  fi

  has_command node || die "Node.js was not found after install."
  has_command npm || die "npm was not found after install."

  local node_major
  node_major="$(node -p "Number(process.versions.node.split('.')[0])")"
  if [[ "$node_major" -lt "$MIN_NODE_MAJOR" ]]; then
    die "Node.js $MIN_NODE_MAJOR+ is required; found $(node --version). Install a newer Node.js and rerun setup.sh."
  fi
}

setup_python() {
  log "Syncing Python environment with uv.lock"
  cd "$ROOT_DIR"
  uv python install "$PYTHON_VERSION"
  uv sync --extra dev --python "$PYTHON_VERSION"
}

fetch_browser() {
  [[ "$SKIP_BROWSER" -eq 0 ]] || return

  log "Downloading Camoufox browser payload"
  cd "$ROOT_DIR"
  uv run python -m camoufox fetch
}

setup_gui() {
  [[ "$SKIP_GUI" -eq 0 ]] || return

  ensure_node
  log "Installing Electron GUI dependencies from package-lock.json"
  cd "$GUI_DIR"
  npm ci
}

print_next_steps() {
  log "Setup complete"
  printf 'Run the CLI: %s\n' 'uv run youtube-scrape --help'
  printf 'Run the GUI: %s\n' './start-gui.sh'
}

parse_args "$@"
ensure_uv
if [[ "$(uname -s)" == "Linux" ]]; then
  install_linux_os_deps
fi
setup_python
fetch_browser
setup_gui
print_next_steps
