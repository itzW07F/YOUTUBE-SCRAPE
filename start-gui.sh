#!/usr/bin/env bash
# Start the Electron + Vite dev GUI (from repository root).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORTABLE_NODE="${XDG_DATA_HOME:-$HOME/.local/share}/youtube-scrape-tools/nodejs-current"
if [[ -x "$PORTABLE_NODE/bin/node" ]]; then
  export PATH="$PORTABLE_NODE/bin:$PATH"
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  export PYTHON_PATH="${PYTHON_PATH:-$ROOT/.venv/bin/python}"
fi

# electron-vite only passes --no-sandbox to the binary when NO_SANDBOX=1 or `dev --noSandbox` (ELECTRON_NO_SANDBOX is ignored).
export NO_SANDBOX="${NO_SANDBOX:-1}"

# On Linux, default to software GL path unless overridden (reduces blank window / GPU lockups)
if [[ "$(uname -s)" == "Linux" ]]; then
  export ELECTRON_DISABLE_GPU="${ELECTRON_DISABLE_GPU:-1}"
fi

if [[ ! -d "$ROOT/gui/node_modules" ]]; then
  echo "First run: installing GUI dependencies in gui/ ..."
  (cd "$ROOT/gui" && npm ci)
fi

cd "$ROOT/gui"
exec npm run dev
