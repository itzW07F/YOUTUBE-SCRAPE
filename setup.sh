#!/usr/bin/env bash
# Bootstrap a local development/runtime environment on Linux and macOS.
# Mirrors setup.ps1: audit, preflight, retries, portable Node fallback, Python version fallbacks.
set -euo pipefail

readonly MIN_NODE_MAJOR=18
readonly ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly GUI_DIR="$ROOT_DIR/gui"
readonly PORTABLE_NODE_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/youtube-scrape-tools/nodejs-current"
readonly PYTHON_VERSION_DEFAULT="${PYTHON_VERSION:-3.13}"

SKIP_GUI=0
SKIP_BROWSER=0
SKIP_OS_DEPS=0
SKIP_AUDIT=0
SKIP_PREFLIGHT=0
MIN_DISK_GIB=4

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

retry_cmd() {
  local max=4 attempt=1 delay=2
  while [[ "$attempt" -le "$max" ]]; do
    if "$@"; then
      return 0
    fi
    if [[ "$attempt" -eq "$max" ]]; then
      return 1
    fi
    warn "Command failed (attempt ${attempt}/${max}); retrying in ${delay}s: $*"
    sleep "$delay"
    delay=$((delay * 2))
    attempt=$((attempt + 1))
  done
}

assert_repository_layout() {
  local m
  for m in "$ROOT_DIR/uv.lock" "$ROOT_DIR/pyproject.toml" "$ROOT_DIR/gui/package-lock.json"; do
    [[ -f "$m" ]] || die "Missing required file: $m. Clone the full repository and run ./setup.sh from the repo root."
  done
}

df_avail_kb() {
  # POSIX: 1024-byte units in column 4 for -P
  df -Pk "$ROOT_DIR" | awk 'NR==2 {print $4}'
}

check_disk_space() {
  local min_gib="$1"
  local avail_kb need_kb
  avail_kb="$(df_avail_kb 2>/dev/null)" || true
  [[ -n "${avail_kb:-}" ]] || {
    warn "Could not read free disk space; continuing."
    return 0
  }
  need_kb=$((min_gib * 1024 * 1024))
  if [[ "$avail_kb" -lt "$need_kb" ]]; then
    die "Insufficient free disk space on the filesystem containing the repo. Need at least ${min_gib} GiB (Python, Node modules, Camoufox)."
  fi
}

check_network_reachable() {
  has_command curl || die "curl is required for network checks and downloads."
  curl -Isf --max-time 15 -o /dev/null "https://nodejs.org/" || die "Network check failed: cannot reach https://nodejs.org/ (check internet, proxy, TLS)."
  curl -Isf --max-time 15 -o /dev/null "https://astral.sh/" || die "Network check failed: cannot reach https://astral.sh/ (check internet, proxy, TLS)."
}

node_archive_label() {
  case "$(uname -s)" in
    Linux)
      case "$(uname -m)" in
        x86_64) printf '%s' "linux-x64" ;;
        aarch64 | arm64) printf '%s' "linux-arm64" ;;
        *) printf '%s' "" ;;
      esac
      ;;
    Darwin)
      case "$(uname -m)" in
        x86_64) printf '%s' "darwin-x64" ;;
        arm64) printf '%s' "darwin-arm64" ;;
        *) printf '%s' "" ;;
      esac
      ;;
    *) printf '%s' "" ;;
  esac
}

parse_node_lts_version() {
  if has_command python3; then
    python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(x["version"] for x in d if x.get("lts")))'
    return
  fi
  if has_command jq; then
    jq -r '[.[] | select(.lts != false)][0].version'
    return
  fi
  return 1
}

get_resolved_node_tarball_url() {
  local label ver url
  label="$(node_archive_label)"
  [[ -n "$label" ]] || return 1
  has_command curl || return 1
  if ! ver="$(curl -fsSL --max-time 20 "https://nodejs.org/dist/index.json" | parse_node_lts_version)"; then
    return 1
  fi
  [[ -n "$ver" ]] || return 1
  url="https://nodejs.org/dist/${ver}/node-${ver}-${label}.tar.xz"
  printf '%s' "$url"
}

export_path_portable_if_exists() {
  if [[ -x "$PORTABLE_NODE_ROOT/bin/node" ]]; then
    export PATH="$PORTABLE_NODE_ROOT/bin:$PATH"
  fi
}

node_meets_minimum() {
  local maj
  has_command node && has_command npm || return 1
  maj="$(node -p "Number(process.versions.node.split('.')[0])" 2>/dev/null)" || return 1
  [[ "${maj:-0}" -ge "$MIN_NODE_MAJOR" ]]
}

write_setup_audit_report() {
  local url_line free_gib avail_kb
  log "Environment audit (read-only)"
  printf '  Kernel / machine : %s\n' "$(uname -srm)"
  if [[ -r /etc/os-release ]]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    printf '  OS               : %s\n' "${PRETTY_NAME:-$NAME ${VERSION}}"
    printf '  OS version id    : %s\n' "${VERSION_ID:-n/a}"
  elif [[ "$(uname -s)" == Darwin ]]; then
    printf '  OS               : macOS %s (build %s)\n' "$(sw_vers -productVersion 2>/dev/null || echo '?')" "$(sw_vers -buildVersion 2>/dev/null || echo '?')"
  fi
  lbl="$(node_archive_label)"
  [[ -n "$lbl" ]] || lbl="unsupported (install Node ${MIN_NODE_MAJOR}+ via distro or https://nodejs.org/)"
  printf '  CPU architecture : %s  (portable tarball label: %s)\n' "$(uname -m)" "$lbl"

  if avail_kb="$(df_avail_kb 2>/dev/null)"; then
    free_gib="$(awk -v k="$avail_kb" 'BEGIN { printf "%.2f", k/1024/1024 }')"
    printf '  Free space       : ~%s GiB on repo filesystem (this run requires >= %s GiB)\n' "$free_gib" "$MIN_DISK_GIB"
  else
    printf '  Free space       : (could not read)\n'
  fi

  printf '  Repository       : %s\n' "$ROOT_DIR"
  printf '  Portable Node dir: %s\n' "$PORTABLE_NODE_ROOT"

  printf '\n  Required / optional commands:\n'
  if has_command git; then
    printf '    git            : present (%s)\n' "$(git --version 2>&1)"
  else
    printf '    git            : not on PATH (optional to run; needed to clone/pull with git)\n'
  fi
  printf '    curl           : %s\n' "$(has_command curl && echo "present" || echo "MISSING (required)")"
  printf '    python3 / jq   : %s / %s (for LTS JSON; needed for portable Node fallback)\n' \
    "$(has_command python3 && echo yes || echo no)" \
    "$(has_command jq && echo yes || echo no)"
  printf '    uv             : %s\n' "$(has_command uv && echo "present ($(uv --version 2>&1))" || echo "missing (will install)")"

  export_path_portable_if_exists
  if ! has_command node; then
    printf '    node / npm     : missing on PATH\n'
  elif ! has_command npm; then
    printf '    node / npm     : node %s; npm missing\n' "$(node --version 2>/dev/null || true)"
  elif node_meets_minimum; then
    printf '    node / npm     : ok (node %s, npm %s)\n' \
      "$(node --version 2>/dev/null)" \
      "$(npm --version 2>/dev/null)"
  else
    printf '    node / npm     : below %s+ (%s); will upgrade/replace\n' "$MIN_NODE_MAJOR" "$(node --version 2>/dev/null || true)"
  fi

  printf '\n  Python           : not required pre-installed — uv will provision (%s preferred, then 3.12/3.13 fallbacks) and sync from uv.lock → .venv\n' \
    "$PYTHON_VERSION_DEFAULT"

  printf '\n  Download / sources:\n'
  printf '    uv bootstrap   : https://astral.sh/uv/install.sh\n'
  printf '    Node LTS list  : https://nodejs.org/dist/index.json\n'
  if url_line="$(get_resolved_node_tarball_url 2>/dev/null)"; then
    printf '    Node portable  : %s (if package managers do not yield Node %s+)\n' "$url_line" "$MIN_NODE_MAJOR"
  else
    printf '    Node portable  : (could not resolve URL yet — need curl and python3 or jq, and a supported CPU/OS tuple)\n'
  fi
  printf '    Camoufox       : uv run python -m camoufox fetch (after Python env exists)\n'
  printf '\n'
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
      --skip-audit)
        SKIP_AUDIT=1
        ;;
      --skip-preflight)
        SKIP_PREFLIGHT=1
        ;;
      --min-disk-gib=*)
        MIN_DISK_GIB="${1#*=}"
        ;;
      --min-disk-gib)
        MIN_DISK_GIB="${2:?--min-disk-gib requires a number}"
        shift
        ;;
      -h | --help)
        cat <<'USAGE'
Usage: ./setup.sh [options]

  --skip-gui           Skip npm ci in gui/
  --skip-browser       Skip Camoufox fetch
  --skip-os-deps       Skip apt/dnf/pacman system packages (Linux only)
  --skip-audit         Skip read-only environment report
  --skip-preflight     Skip disk + network checks (automation only)
  --min-disk-gib N     Minimum free GiB on repo filesystem (default: 4)

Environment:
  PYTHON_VERSION       Preferred Python for uv (default: 3.13)
USAGE
        exit 0
        ;;
      *)
        die "Unknown option: $1 (try --help)"
        ;;
    esac
    shift
  done
}

ensure_uv() {
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if has_command uv; then
    return 0
  fi

  has_command curl || die "curl is required to install uv."

  log "Installing uv"
  retry_cmd bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' || die "uv installation failed after retries."

  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  has_command uv || die "uv installed, but it is not on PATH. Open a new terminal and rerun ./setup.sh."
}

install_linux_os_deps() {
  [[ "$SKIP_OS_DEPS" -eq 0 ]] || return 0
  [[ "$(uname -s)" == Linux ]] || return 0

  if has_command apt-get; then
    log "Installing Linux browser/media system packages (apt)"
    sudo apt-get update
    sudo apt-get install -y \
      ca-certificates curl ffmpeg fonts-liberation \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libasound2 \
      || warn "Some OS packages were not installed; Camoufox may report missing libraries."
    return 0
  fi

  if has_command dnf; then
    log "Installing Linux browser/media + Node stack (dnf)"
    sudo dnf install -y nodejs npm ffmpeg nss atk at-spi2-atk cups-libs libdrm \
      libxkbcommon libXcomposite libXdamage libXfixes libXrandr mesa-libgbm alsa-lib \
      || warn "Some OS packages were not installed; Camoufox may report missing libraries."
    return 0
  fi

  if has_command pacman; then
    log "Installing Linux browser/media + Node stack (pacman)"
    sudo pacman -Sy --needed --noconfirm nodejs npm ffmpeg nss atk at-spi2-atk cups \
      libdrm libxkbcommon libxcomposite libxdamage libxfixes libxrandr mesa alsa-lib \
      || warn "Some OS packages were not installed; Camoufox may report missing libraries."
    return 0
  fi

  warn "No apt-get, dnf, or pacman detected. Install browser libraries manually if Camoufox fails."
}

install_node_via_package_manager() {
  case "$(uname -s)" in
    Darwin)
      if ! has_command brew; then
        warn "Homebrew not found; will use portable Node if needed."
        return 1
      fi
      log "Installing Node.js with Homebrew"
      brew install node 2>/dev/null || brew upgrade node 2>/dev/null || true
      ;;
    Linux)
      if has_command apt-get; then
        log "Installing Node.js/npm with apt"
        sudo apt-get update
        sudo apt-get install -y nodejs npm || return 1
      elif has_command dnf; then
        log "Installing Node.js/npm with dnf (if not already in OS deps step)"
        sudo dnf install -y nodejs npm || return 1
      elif has_command pacman; then
        log "Installing Node.js/npm with pacman"
        sudo pacman -Sy --needed --noconfirm nodejs npm || return 1
      else
        warn "No supported package manager for Node; will try portable archive."
        return 1
      fi
      ;;
    *)
      return 1
      ;;
  esac
  has_command node && has_command npm
}

install_node_portable_tarball() {
  local label ver url tarname dest parent stage inner
  label="$(node_archive_label)"
  [[ -n "$label" ]] || die "Portable Node is not supported on this OS/CPU. Install Node.js ${MIN_NODE_MAJOR}+ manually."

  has_command curl || die "curl is required for portable Node install."
  has_command python3 || has_command jq || die "Portable Node requires python3 or jq to read https://nodejs.org/dist/index.json."

  ver="$(curl -fsSL --max-time 30 "https://nodejs.org/dist/index.json" | parse_node_lts_version)" \
    || die "Could not determine Node LTS version from nodejs.org."
  [[ -n "$ver" ]] || die "Empty Node LTS version from nodejs.org."

  tarname="node-${ver}-${label}.tar.xz"
  url="https://nodejs.org/dist/${ver}/${tarname}"
  parent="$(dirname "$PORTABLE_NODE_ROOT")"
  mkdir -p "$parent"

  stage="$(mktemp -d)"
  log "Downloading portable Node.js LTS (${tarname})"
  curl -fsSL --max-time 900 -o "$stage/$tarname" "$url" || die "Download failed: $url"

  tar -xJf "$stage/$tarname" -C "$stage" || die "Extract failed for $tarname (install xz if tar cannot read .tar.xz)."
  shopt -s nullglob
  inner=( "$stage"/node-v* )
  shopt -u nullglob
  [[ "${#inner[@]}" -eq 1 ]] || die "Unexpected layout inside Node archive."

  rm -rf "$PORTABLE_NODE_ROOT"
  mkdir -p "$parent"
  mv "${inner[0]}" "$PORTABLE_NODE_ROOT"

  rm -rf "$stage"
  export PATH="$PORTABLE_NODE_ROOT/bin:$PATH"
  has_command node && has_command npm || die "Portable Node install did not expose node/npm."
}

ensure_node() {
  export_path_portable_if_exists

  if node_meets_minimum; then
    return 0
  fi

  if has_command node && has_command npm; then
    warn "Node.js on PATH is below ${MIN_NODE_MAJOR}+ ($(node --version 2>/dev/null || true)); trying package managers, then portable LTS."
  fi

  if install_node_via_package_manager; then
    export_path_portable_if_exists
    node_meets_minimum && return 0
  fi

  install_node_portable_tarball
  export_path_portable_if_exists
  node_meets_minimum || die "Node.js ${MIN_NODE_MAJOR}+ is required. Remove obsolete Node from PATH or install manually. Portable path: $PORTABLE_NODE_ROOT"
}

setup_python_one() {
  local ver="$1"
  log "Syncing Python ${ver} environment with uv.lock"
  (
    cd "$ROOT_DIR"
    uv python install "$ver"
    uv sync --extra dev --python "$ver"
  )
}

setup_python_with_fallback() {
  local ver ok=0 seen="|" versions=()
  for ver in "$PYTHON_VERSION_DEFAULT" 3.12 3.13; do
    case "$seen" in
      *"|$ver|"*) continue ;;
    esac
    seen="${seen}${ver}|"
    versions+=("$ver")
  done
  for ver in "${versions[@]}"; do
    if retry_cmd setup_python_one "$ver"; then
      ok=1
      break
    fi
    warn "Python setup with ${ver} failed; trying next pinned version if any."
  done
  [[ "$ok" -eq 1 ]] || die "Could not create the Python virtual environment with uv (tried ${PYTHON_VERSION_DEFAULT} / 3.12 / 3.13 fallbacks)."
}

fetch_browser() {
  [[ "$SKIP_BROWSER" -eq 0 ]] || return 0

  log "Downloading Camoufox browser payload (large; may take several minutes)"
  (
    cd "$ROOT_DIR"
    retry_cmd uv run python -m camoufox fetch
  ) || die "camoufox fetch failed after retries."
}

setup_gui() {
  [[ "$SKIP_GUI" -eq 0 ]] || return 0

  ensure_node
  log "Installing Electron GUI dependencies (npm ci)"
  (
    cd "$GUI_DIR"
    retry_cmd npm ci
  ) || die "npm ci failed after retries."
}

print_next_steps() {
  log "Setup complete"
  printf 'Run the CLI: %s\n' 'uv run youtube-scrape --help'
  printf 'Run the GUI: %s\n' './start-gui.sh'
}

# --- main ---
parse_args "$@"
assert_repository_layout

[[ "$SKIP_AUDIT" -eq 0 ]] && write_setup_audit_report

if [[ "$SKIP_PREFLIGHT" -eq 0 ]]; then
  check_disk_space "$MIN_DISK_GIB"
  check_network_reachable
  has_command git || warn "Git is not on PATH. You can run the app; install git only if you need clone/pull workflows."
fi

ensure_uv
install_linux_os_deps
setup_python_with_fallback
fetch_browser
setup_gui
print_next_steps
