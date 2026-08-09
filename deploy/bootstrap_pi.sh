#!/usr/bin/env bash
# One-time (and safe-to-re-run-after-git-pull) setup for wta-daily on a
# Raspberry Pi. Deliberately does NOT touch anything system-wide: no apt
# installs, no sudo, no system Python changes - just a project-local venv,
# exactly per the "isolated from Pi-hole and the OS" requirement.
#
# Usage (from the project root, after `git clone`/`git pull`):
#   bash deploy/bootstrap_pi.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "== wta-daily bootstrap =="
echo "Project root: $PROJECT_ROOT"
echo "Architecture: $(uname -m)"
# shellcheck disable=SC1091
echo "OS:           $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: $PYTHON_BIN not found on PATH." >&2
    exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "Python:       $PY_VERSION ($(command -v "$PYTHON_BIN"))"

PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo
    echo "WARNING: wta-daily targets Python >= 3.11, but $PYTHON_BIN is $PY_VERSION."
    echo "         This project is designed for a fresh Raspberry Pi OS Bookworm"
    echo "         or Trixie install (system Python 3.11+). See README.md's"
    echo "         'Raspberry Pi deployment' section before continuing on an"
    echo "         older OS release."
    echo
fi

if [ ! -d .venv ]; then
    echo "Creating virtual environment in .venv/ ..."
    "$PYTHON_BIN" -m venv .venv
else
    echo "Reusing existing .venv/"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "Upgrading pip..."
python -m pip install --upgrade pip --quiet

echo "Installing wta_daily and its dependencies (editable, so 'git pull' picks up code changes immediately)..."
python -m pip install -e . --quiet

mkdir -p data/cache output logs

if [ ! -f config/config.yaml ]; then
    echo "Creating config/config.yaml from config.example.yaml (edit this to taste)..."
    cp config/config.example.yaml config/config.yaml
else
    echo "config/config.yaml already exists; leaving it alone."
fi

if [ ! -f .env ]; then
    echo "Creating .env from .env.example (fill in any API keys you actually enable)..."
    cp .env.example .env
    chmod 600 .env
else
    echo ".env already exists; leaving it alone."
fi

echo
echo "== Done =="
echo "Next steps:"
echo "  1. Edit config/config.yaml and .env as needed."
echo "  2. Try a run:  .venv/bin/python -m wta_daily.cli --config config/config.yaml --verbose"
echo "  3. Schedule it - pick ONE:"
echo "       systemd (recommended): see deploy/systemd/wta-daily.{service,timer}"
echo "       cron:                  see deploy/cron/wta-daily.cron"
