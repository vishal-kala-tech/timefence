#!/bin/bash

# Exit immediately if any command fails.
set -e

# Resolve project source directory and installation paths.
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Library/Application Support/TimeFence"
LOG="$HOME/Library/Logs/TimeFence"
PL="$HOME/Library/LaunchAgents/com.user.timefence.plist"
PY="$(command -v python3)"

# Create application, log, and LaunchAgent directories.
mkdir -p "$APP" "$LOG" "$HOME/Library/LaunchAgents"

# Install the TimeFence Python source code.
cp -R "$SRC/src" "$APP/"

# Create configuration and runtime state directories.
mkdir -p "$APP/config" "$APP/state"

# Install the example configuration.
cp "$SRC/config/rules.example.json" "$APP/config/rules.example.json"

# Install the default rules only if rules.json does not already exist.
# This preserves any existing user configuration during upgrades.
[ -f "$APP/config/rules.json" ] || cp "$SRC/config/rules.json" "$APP/config/rules.json"

# Generate the LaunchAgent plist with the actual installation paths.
sed -e "s|__APP_DIR__|$APP|g" -e "s|__LOG_DIR__|$LOG|g" -e "s|__PYTHON__|$PY|g" "$SRC/launchd/com.user.timefence.plist.template" > "$PL"

# Validate the generated plist before loading it.
plutil -lint "$PL"

# Unload the existing TimeFence LaunchAgent if it is already running.
launchctl bootout gui/$(id -u) "$PL" 2>/dev/null || true

# Load and start the TimeFence LaunchAgent.
launchctl bootstrap gui/$(id -u) "$PL"

echo "Installed TimeFence"