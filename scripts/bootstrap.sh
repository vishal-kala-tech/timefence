#!/bin/bash

# Install TimeFence on a Mac that may not have Python yet.
# Copies this folder's app, installs Python 3.13 from python.org if needed,
# then runs install.sh (LaunchAgent, config, notifier).
#
# Usage (from the TimeFence project folder):
#   ./scripts/bootstrap.sh
#
# Needs: macOS, internet (to download Python), and an administrator password
# if Python is not already installed.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib-python.sh
. "$SCRIPT_DIR/lib-python.sh"

PYTHON_VERSION="3.13.15"
PYTHON_PKG="python-${PYTHON_VERSION}-macos11.pkg"
PYTHON_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_PKG}"

export PATH="/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.13/bin:/opt/homebrew/bin:$PATH"

echo "==== $(date) ===="
echo "TimeFence bootstrap (from scratch)"
echo "  project: $SRC"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "TimeFence only runs on macOS." >&2
    exit 1
fi

if [ ! -d "$SRC/src/timefence" ] || [ ! -f "$SCRIPT_DIR/install.sh" ]; then
    echo "This script must be run from a complete TimeFence folder" >&2
    echo "(the one that contains src/ and scripts/)." >&2
    exit 1
fi

install_python_from_python_org() {
    local tmp pkg
    tmp="$(mktemp -d /tmp/timefence-python.XXXXXX)"
    pkg="$tmp/$PYTHON_PKG"
    echo "Downloading Python $PYTHON_VERSION from python.org"
    echo "  $PYTHON_URL"
    if ! curl -fL --progress-bar "$PYTHON_URL" -o "$pkg"; then
        echo "Download failed. Check the network and try again." >&2
        rm -rf "$tmp"
        exit 1
    fi
    echo "Installing Python $PYTHON_VERSION for all users on this Mac."
    echo "macOS will ask for the login password of this account:"
    echo "  user:  $(id -un)"
    echo "  (This is the same password you use to unlock the Mac.)"
    if ! id -Gn | tr ' ' '\n' | grep -qx admin; then
        echo "This account is not an administrator, so the password will be rejected." >&2
        echo "Sign in as an admin user (often a parent account), or run:" >&2
        echo "  su ADMIN_USERNAME" >&2
        echo "  $SCRIPT_DIR/bootstrap.sh" >&2
        rm -rf "$tmp"
        exit 1
    fi
    sudo installer -pkg "$pkg" -target /
    rm -rf "$tmp"
    hash -r 2>/dev/null || true
}

install_python_with_homebrew() {
    echo "Installing Python with Homebrew"
    brew install python@3.13 || brew install python3
    hash -r 2>/dev/null || true
}

PY="$(timefence_find_python || true)"
if [ -n "$PY" ]; then
    echo "Found Python: $PY"
    "$PY" -c 'import sys; print("  version:", sys.version.split()[0])'
else
    echo "No usable Python 3.10+ found."
    if command -v brew >/dev/null 2>&1; then
        install_python_with_homebrew
    else
        install_python_from_python_org
    fi
    PY="$(timefence_find_python || true)"
    if [ -z "$PY" ]; then
        echo "Python was installed but is not on PATH yet." >&2
        echo "Open a new Terminal window and run: $SCRIPT_DIR/install.sh" >&2
        exit 1
    fi
    echo "Using Python: $PY"
    "$PY" -c 'import sys; print("  version:", sys.version.split()[0])'
fi

echo "Installing TimeFence"
TIMEFENCE_PYTHON="$PY" "$SCRIPT_DIR/install.sh"

echo
echo "Bootstrap finished."
echo "  python:   $PY"
echo "  status:   $SCRIPT_DIR/status.sh"
echo "  budget:   $SCRIPT_DIR/budget.sh"
echo "  activity: $SCRIPT_DIR/activity.sh"
echo
echo "Keep this TimeFence folder. Helper scripts run from here."
echo "In Google Chrome, turn on View → Developer → Allow JavaScript from Apple Events"
echo "so paused YouTube videos are not billed."
