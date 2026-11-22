#!/usr/bin/env bash
# FakerAlpha - local setup in one command (Linux, macOS, WSL).
#
#   ./setup.sh                 Python environment + models + analyst panel
#   ./setup.sh --demo          ... and load the demo dataset (8 invented cases, no network)
#   ./setup.sh --playwright    ... and headless Chromium for rendering live pages (optional, ~300 MB)
#   ./setup.sh --no-web        skip the panel build (CLI only; no Node needed)
#
# Safe to run again: finished steps are skipped or only refreshed.
# Without Python / Node on the machine use Docker instead: docker compose up --build   (see README.md)
set -euo pipefail
cd "$(dirname "$0")"

DEMO=0; PLAYWRIGHT=0; WEB=1
for arg in "$@"; do
  case "$arg" in
    --demo) DEMO=1 ;;
    --playwright) PLAYWRIGHT=1 ;;
    --no-web) WEB=0 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see ./setup.sh --help)" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
T0=$(date +%s)

# ------------------------------------------------------------------ prerequisites
say "Checking prerequisites"
PY=""
if have uv; then
  echo "uv:      $(uv --version)"
else
  for c in python3.12 python3.13 python3; do
    if have "$c" && "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] in ((3, 12), (3, 13)) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  [ -n "$PY" ] || die "need uv (https://docs.astral.sh/uv/) or Python 3.12 / 3.13 on PATH.
       Install uv:  curl -LsSf https://astral.sh/uv/install.sh | sh
       or use Docker: docker compose up --build"
  echo "python:  $("$PY" --version) (uv not found - using venv + pip, slower)"
fi
if [ "$WEB" = 1 ]; then
  have node && have npm || die "the analyst panel needs Node >= 20 with npm (https://nodejs.org/).
       Install it, or run ./setup.sh --no-web for the CLI only, or use Docker: docker compose up --build"
  NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
  [ "$NODE_MAJOR" -ge 20 ] || die "Node $(node --version) is too old; the panel build needs Node >= 20"
  echo "node:    $(node --version)"
fi
if have ffmpeg && have ffprobe; then
  echo "ffmpeg:  found"
else
  warn "ffmpeg / ffprobe not found - video files will be analysed without keyframes.
         Install: sudo apt install ffmpeg   |   brew install ffmpeg"
fi

# ------------------------------------------------------------------ Python environment
say "Python environment (.venv) and libraries"
if have uv; then
  [ -x .venv/bin/python ] || uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements.txt
else
  [ -x .venv/bin/python ] || "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

# ------------------------------------------------------------------ models
say "Models (~310 MB ONNX + ~30 MB OCR; files already present are skipped)"
.venv/bin/python tools/download_models.py

# ------------------------------------------------------------------ analyst panel
if [ "$WEB" = 1 ]; then
  say "Analyst panel (web/dist)"
  (cd web && npm ci --no-audit --no-fund && npm run build)
fi

# ------------------------------------------------------------------ optional parts
if [ "$PLAYWRIGHT" = 1 ]; then
  say "Headless Chromium (Playwright)"
  if have uv; then uv pip install --python .venv/bin/python playwright; else .venv/bin/python -m pip install playwright; fi
  .venv/bin/playwright install chromium
fi
if [ "$DEMO" = 1 ]; then
  say "Demo dataset"
  .venv/bin/python -m ftf demo
fi

# ------------------------------------------------------------------ done
say "Ready in $(( $(date +%s) - T0 )) s"
cat <<'EOF'
Next steps:
  .venv/bin/python -m ftf demo                        # demo dataset: 8 invented cases, a few seconds, no network
  .venv/bin/python -m ftf ingest <dataset folder>     # your own cases: every subfolder is one case
  .venv/bin/python -m ftf serve                       # analyst panel: http://127.0.0.1:8765
A dataset can also be imported in the panel (start page or "Analizuj materiał").
Face reference persons work out of the box; tools/build_face_gallery.py is only for adding persons.
EOF
