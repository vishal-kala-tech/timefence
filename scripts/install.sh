#!/bin/bash

# Exit immediately if any command fails.
set -e

# Resolve project source directory and installation paths.
SRC="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib-python.sh
. "$SCRIPT_DIR/lib-python.sh"
APP="$HOME/Library/Application Support/TimeFence"
LOG="$HOME/Library/Logs/TimeFence"
AGENTS="$HOME/Library/LaunchAgents"
PL="$AGENTS/com.user.timefence.plist"
if [ -n "${TIMEFENCE_PYTHON:-}" ] && timefence_python_ok "$TIMEFENCE_PYTHON"; then
    PY="$TIMEFENCE_PYTHON"
elif PY="$(timefence_find_python)"; then
    :
else
    echo "Python 3.10 or newer is required and was not found." >&2
    echo "On a Mac with no Python, run: $SCRIPT_DIR/bootstrap.sh" >&2
    exit 1
fi
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
    echo "  (install does not overwrite parent-edited rules; copy new apps/bundle_ids from $EXAMPLE if needed)"
else
    echo "Copying $SRC/config/rules.json -> $RULES"
    cp "$SRC/config/rules.json" "$RULES"
fi

echo "Building $APP/TimeFenceNotifier.app"
rm -rf "$APP/TimeFenceNotifier.app"
NOTIFIER="$APP/TimeFenceNotifier.app"
mkdir -p "$NOTIFIER/Contents/MacOS" "$NOTIFIER/Contents/Resources"
cp "$SRC/launchd/TimeFenceNotifier.plist" "$NOTIFIER/Contents/Info.plist"
cp "$SRC/launchd/TimeFenceNotifier.py" "$NOTIFIER/Contents/Resources/TimeFenceNotifier.py"
cp "$SRC/launchd/TimeFenceNotifier.sh" "$NOTIFIER/Contents/MacOS/TimeFenceNotifier"
printf '%s\n' "$PY" > "$NOTIFIER/Contents/Resources/python.path"
chmod +x "$NOTIFIER/Contents/MacOS/TimeFenceNotifier"
xattr -dr com.apple.quarantine "$NOTIFIER" 2>/dev/null || true

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
echo "  kid status page: http://127.0.0.1:8743/"
echo "  parent setup:    http://127.0.0.1:8743/setup"
echo "  shortcuts:       $SRC/shortcuts"
echo "  install log:     $SETUP_LOG"
echo "  stdout log:      $LOG/timefence.out.log"
echo "  stderr log:      $LOG/timefence.err.log"
