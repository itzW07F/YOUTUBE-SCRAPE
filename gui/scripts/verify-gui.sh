#!/usr/bin/env bash
# Full verification: Python API import, Vite + Electron dev server, Playwright capture.
# From repo: (cd gui && npm install && npm run verify:gui)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUI_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$GUI_DIR/.." && pwd)"
export PYTHON_PATH="${PYTHON_PATH:-$REPO_ROOT/.venv/bin/python}"

echo "== verify-gui: REPO=$REPO_ROOT GUI=$GUI_DIR =="

SERVER_PY="$REPO_ROOT/src/youtube_scrape/api/server.py"
if [[ ! -f "$SERVER_PY" ]]; then
  echo "Missing $SERVER_PY" >&2
  exit 1
fi

cd "$REPO_ROOT"
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  "$REPO_ROOT/.venv/bin/python" -c "import sys; sys.path.insert(0,'$REPO_ROOT/src'); from youtube_scrape.api.server import app; print('import_ok', app.title)"
else
  python3 -c "import sys; sys.path.insert(0,'$REPO_ROOT/src'); from youtube_scrape.api.server import app; print('import_ok', app.title)"
fi

cd "$GUI_DIR"
export NO_SANDBOX=1
export ELECTRON_DISABLE_GPU=1
rm -f "$GUI_DIR/verify-screenshot.png" "$GUI_DIR/.dev-electron.log"

LOG=/tmp/ytscrape-gui-verify-$$.log
if [[ -z "${DISPLAY:-}" && "$(uname -s)" == "Linux" && -x /usr/bin/xvfb-run ]]; then
  # Headless: virtual framebuffer for Electron; Vite is HTTP and does not need a display, but
  # `npm run dev` also launches Electron, which needs a DISPLAY under X.
  xvfb-run -a env npm run dev >"$LOG" 2>&1 &
else
  env npm run dev >"$LOG" 2>&1 &
fi
EV_PID=$!
echo "Started dev stack pid=$EV_PID (log $LOG)"
cleanup() {
  if kill -0 "$EV_PID" 2>/dev/null; then
    kill "$EV_PID" 2>/dev/null || true
    sleep 2
    kill -9 "$EV_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

VITE_OK=0
for i in $(seq 1 90); do
  if curl -sf "http://127.0.0.1:5173/" -o /dev/null; then
    echo "vite_ok after ${i}s"
    VITE_OK=1
    break
  fi
  if ! kill -0 "$EV_PID" 2>/dev/null; then
    echo "dev process exited early; tail $LOG" >&2
    tail -n 80 "$LOG" >&2
    exit 1
  fi
  sleep 1
done
if [[ "$VITE_OK" -ne 1 ]]; then
  echo "Timeout waiting for http://127.0.0.1:5173" >&2
  tail -n 100 "$LOG" >&2
  exit 1
fi

npx playwright install chromium
node "$SCRIPT_DIR/verify-renderer.mjs"

if [[ -f "$GUI_DIR/.dev-electron.log" ]]; then
  echo "---- tail gui/.dev-electron.log ----"
  tail -n 30 "$GUI_DIR/.dev-electron.log" || true
fi

echo "OK verify-gui: $GUI_DIR/verify-screenshot.png"
