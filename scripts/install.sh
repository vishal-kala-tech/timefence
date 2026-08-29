#!/bin/bash

# Exit immediately if any command fails.
set -e

# Resolve project source directory and installation paths.
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Library/Application Support/TimeFence"
LOG="$HOME/Library/Logs/TimeFence"
AGENTS="$HOME/Library/LaunchAgents"
PL="$AGENTS/com.user.timefence.plist"
PY="$(command -v python3)"
RULES="$APP/config/rules.json"
EXAMPLE="$APP/config/rules.example.json"
TEMPLATE="$SRC/launchd/com.user.timefence.plist.template"
SETUP_LOG="$LOG/install.log"

mkdir -p "$LOG"
exec > >(tee -a "$SETUP_LOG") 2>&1

echo "==== $(date) ===="
echo "Logging to $SETUP_LOG"
echo "Installing TimeFence"
echo "  source:          $SRC"
echo "  python:          $PY"
echo "  app:             $APP"
echo "  config:          $APP/config"
echo "  state:           $APP/state"
echo "  logs:            $LOG"
echo "  launch agent:    $PL"

echo "Creating $APP"
mkdir -p "$APP"
echo "Creating $LOG"
mkdir -p "$LOG"
echo "Creating $AGENTS"
mkdir -p "$AGENTS"

echo "Copying $SRC/src -> $APP/src"
cp -R "$SRC/src" "$APP/"

echo "Creating $APP/config"
mkdir -p "$APP/config"
echo "Creating $APP/state"
mkdir -p "$APP/state"

echo "Copying $SRC/config/rules.example.json -> $EXAMPLE"
cp "$SRC/config/rules.example.json" "$EXAMPLE"

if [ -f "$RULES" ]; then
    echo "Keeping existing $RULES"
else
    echo "Copying $SRC/config/rules.json -> $RULES"
    cp "$SRC/config/rules.json" "$RULES"
fi

echo "Building $APP/TimeFenceNotifier.app"
rm -rf "$APP/TimeFenceNotifier.app"
osacompile -o "$APP/TimeFenceNotifier.app" "$SRC/launchd/notify.applescript"
INFO="$APP/TimeFenceNotifier.app/Contents/Info.plist"
plutil -replace LSUIElement -bool true "$INFO"
plutil -replace CFBundleName -string "TimeFence" "$INFO"
plutil -replace CFBundleIdentifier -string "com.user.timefence.notify" "$INFO"
plutil -replace NSUserNotificationAlertStyle -string "alert" "$INFO"

echo "Writing $PL from $TEMPLATE"
sed -e "s|__APP_DIR__|$APP|g" -e "s|__LOG_DIR__|$LOG|g" -e "s|__PYTHON__|$PY|g" "$TEMPLATE" > "$PL"

echo "Validating $PL"
plutil -lint "$PL"

echo "Unloading $PL (if loaded)"
launchctl bootout gui/$(id -u) "$PL" 2>/dev/null || true

echo "Loading $PL"
launchctl bootstrap gui/$(id -u) "$PL"

"$SRC/scripts/link-shortcuts.sh"

echo "Installed TimeFence"
echo "  rules:           $RULES"
echo "  notifier:        $APP/TimeFenceNotifier.app"
echo "  shortcuts:       $SRC/shortcuts"
echo "  install log:     $SETUP_LOG"
echo "  stdout log:      $LOG/timefence.out.log"
echo "  stderr log:      $LOG/timefence.err.log"
