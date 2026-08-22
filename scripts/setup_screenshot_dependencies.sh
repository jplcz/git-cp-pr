#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${GIT_CP_PR_SCREENSHOT_VENV:-$SCRIPT_DIR/.venv}"

if [[ "$(uname -s)" != "Linux" ]]; then
    printf '%s\n' "This helper installs Ubuntu/Linux dependencies with apt and cannot run on this operating system."
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    printf '%s\n' "apt-get was not found. Run this helper on Ubuntu or another Debian-based system."
    exit 1
fi

if [[ "${EUID}" -eq 0 ]]; then
    APT=(apt-get)
elif command -v sudo >/dev/null 2>&1; then
    APT=(sudo apt-get)
else
    printf '%s\n' "This helper needs root access. Install sudo or run it as root."
    exit 1
fi

printf '%s\n' "Installing Ubuntu system dependencies..."
"${APT[@]}" update
"${APT[@]}" install --yes python3 python3-tk python3-venv xvfb

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf '%s\n' "Python interpreter '$PYTHON_BIN' was not found. Set PYTHON_BIN to its command name."
    exit 1
fi

printf '%s\n' "Creating Python environment at '$VENV_DIR'..."
"$PYTHON_BIN" -m venv "$VENV_DIR"

printf '%s\n' "Installing developer screenshot dependencies..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --requirement "$SCRIPT_DIR/scripts/requirements-screenshots.txt"

printf '%s\n' "Dependencies are ready. Generate screenshots with:"
printf '%s\n' "  $VENV_DIR/bin/python $SCRIPT_DIR/scripts/generate_demo_screenshots.py"
