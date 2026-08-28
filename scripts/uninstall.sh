#!/bin/bash

# Exit immediately if any command fails.
set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Library/Application Support/TimeFence"
LOG="$HOME/Library/Logs/TimeFence"
PL="$HOME/Library/LaunchAgents/com.user.timefence.plist"
SETUP_LOG="$LOG/uninstall.log"

mkdir -p "$LOG"
exec > >(tee -a "$SETUP_LOG") 2>&1

echo "==== $(date) ===="
echo "Logging to $SETUP_LOG"
echo "Uninstalling TimeFence"
echo "  app:             $APP"
echo "  config:          $APP/config"
echo "  state:           $APP/state"
echo "  launch agent:    $PL"
echo "  logs (retained): $LOG"

echo "Unloading $PL (if loaded)"
launchctl bootout gui/$(id -u) "$PL" 2>/dev/null || true

if [ -f "$PL" ]; then
    echo "Removing $PL"
    rm -f "$PL"
else
    echo "No LaunchAgent at $PL"
fi

if [ -d "$APP" ]; then
    echo "Removing $APP"
    rm -rf "$APP"
else
    echo "No app directory at $APP"
fi

echo "Removed TimeFence"
echo "  logs retained:   $LOG"
echo "  shortcuts:       $SRC/shortcuts"
echo "  uninstall log:   $SETUP_LOG"
echo "  stdout log:      $LOG/timefence.out.log"
echo "  stderr log:      $LOG/timefence.err.log"
