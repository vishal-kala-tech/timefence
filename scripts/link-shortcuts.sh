#!/bin/bash

# Exit immediately if any command fails.
set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Library/Application Support/TimeFence"
LOG="$HOME/Library/Logs/TimeFence"
PL="$HOME/Library/LaunchAgents/com.user.timefence.plist"
DEST="$SRC/shortcuts"

echo "Creating shortcuts in $DEST"
mkdir -p "$DEST"

link() {
    local target="$1"
    local name="$2"
    ln -sfn "$target" "$DEST/$name"
    echo "  $DEST/$name -> $target"
}

link "$APP" "app"
link "$APP/config" "config"
link "$APP/config/rules.json" "rules.json"
link "$APP/config/rules.example.json" "rules.example.json"
link "$APP/state" "state"
link "$APP/src" "installed-src"
link "$LOG" "logs"
link "$LOG/install.log" "install.log"
link "$LOG/uninstall.log" "uninstall.log"
link "$LOG/timefence.out.log" "timefence.out.log"
link "$LOG/timefence.err.log" "timefence.err.log"
link "$PL" "com.user.timefence.plist"
link "$APP/TimeFenceNotifier.app" "TimeFenceNotifier.app"
link "$APP/status.html" "status.html"
