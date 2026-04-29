#!/usr/bin/env bash
# One-shot checks before merge / handoff: Python tests + GUI typecheck + Vite/Electron bundle.
# Catches TS/syntax errors in main/preload (esbuild) that pytest alone will miss.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "== Python (pytest) =="
if command -v uv >/dev/null 2>&1; then
  uv run pytest -q
else
  python3 -m pytest -q
fi

echo "== GUI (typecheck + electron-vite build) =="
(
  cd "$ROOT/gui"
  npm run build
)

echo "OK verify.sh: Python tests + gui build passed."
