#!/bin/bash

# Show a test TimeFence dialog without waiting for usage limits.
# Run this while logged in as the child (the same account the agent uses).
# Uses this repo's Python package when run from the project, so you do not
# need to reinstall just to try a notification change.

set -e

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Library/Application Support/TimeFence"

if [ -d "$SRC/src/timefence" ]; then
    export PYTHONPATH="$SRC/src"
    echo "Using project code: $SRC/src"
else
    export PYTHONPATH="${PYTHONPATH:-$APP/src}"
    echo "Using installed code: $PYTHONPATH"
fi

export TIME_FENCE_HOME="${TIME_FENCE_HOME:-$APP}"

echo "TIME_FENCE_HOME=$TIME_FENCE_HOME"
if [ -x "$TIME_FENCE_HOME/TimeFenceNotifier.app/Contents/MacOS/TimeFenceNotifier" ]; then
    echo "Notifier app: $TIME_FENCE_HOME/TimeFenceNotifier.app"
elif [ -x "$TIME_FENCE_HOME/TimeFenceNotifier.app/Contents/MacOS/applet" ]; then
    echo "Notifier app: $TIME_FENCE_HOME/TimeFenceNotifier.app (legacy applet; reinstall)"
else
    echo "Notifier app: not installed (System Events dialog only)"
fi
echo "Notifier log: $HOME/Library/Logs/TimeFence/notifier.log"

python3 - "$1" <<'PY'
import logging
import sys
import timefence.notifications as n

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
print("module:", n.__file__)
if sys.argv[1] == "--countdown":
    print("Showing a 6-second block dialog, then exiting.")
    ok = n.show_block_countdown("TimeFence", "YouTube has no time remaining today.")
else:
    print("Showing a 6-second warning dialog.")
    ok = n.show_notification("TimeFence", "Test notification from TimeFence.")
print("sent" if ok else "failed")
raise SystemExit(0 if ok else 1)
PY
